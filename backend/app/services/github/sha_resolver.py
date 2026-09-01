import asyncio
import logging
import re

import redis.asyncio as aioredis
from github import Github
from github.GithubException import GithubException, UnknownObjectException

from app.services.ref_cache import (
    cached_fetch,
    close_cache,
    open_cache,
)

logger = logging.getLogger(__name__)

_ACTION_USE_RE = re.compile(r"uses:\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)@([^\s#]+)")

# Actions commonly introduced by the LLM when fixing workflows. Their latest
# versions are resolved online so the LLM never invents hashes or pins to a
# stale hardcoded tag.
WELL_KNOWN_ACTIONS: list[str] = [
    "actions/checkout",
    "actions/setup-python",
    "actions/cache",
    "actions/upload-artifact",
    "actions/download-artifact",
]

# GitHub tags and release history are effectively immutable, so these take the
# shared cache's day-long default TTL (see ``ref_cache``).
_SHA_CACHE_PREFIX = "action_sha:"
_VERSION_CACHE_PREFIX = "action_version:latest:"


def _parse_action_refs(workflow_content: str) -> set[tuple[str, str]]:
    """Refs that still need resolving — i.e. everything not already a SHA."""
    refs: set[tuple[str, str]] = set()
    for match in _ACTION_USE_RE.finditer(workflow_content):
        repo, ref = match.group(1), match.group(2)
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            continue
        refs.add((repo, ref))
    return refs


def _referenced_repos(workflow_content: str) -> set[str]:
    """Every repository the workflow uses, however it is pinned.

    Deliberately not derived from ``_parse_action_refs``: that drops refs which
    are already SHA-pinned, so in a fully pinned workflow it returns nothing and
    every well-known action looks absent. The "latest version" defaults below
    were then offered to the LLM for actions the workflow was already using, and
    it swapped the existing pins for them — which is how a fix PR moved
    actions/checkout from v7.0.1 back to v7.0.0, and three others with it.
    """
    return {match.group(1) for match in _ACTION_USE_RE.finditer(workflow_content)}


def _resolve_ref_to_sha_sync(gh: Github, repo_name: str, ref: str) -> str | None:
    try:
        repo = gh.get_repo(repo_name)
    except (GithubException, UnknownObjectException) as exc:
        logger.warning("Failed to get repo %s: %s", repo_name, exc)
        return None

    for ref_path in [f"tags/{ref}", f"heads/{ref}"]:
        try:
            git_ref = repo.get_git_ref(ref_path)
            sha = git_ref.object.sha
            if git_ref.object.type == "tag":
                sha = repo.get_git_tag(sha).object.sha
            return sha
        except (GithubException, UnknownObjectException):
            continue
        except Exception as exc:
            logger.warning("Failed to resolve SHA for %s@%s: %s", repo_name, ref, exc)
    return None


def _get_latest_version_sync(gh: Github, repo_name: str) -> str | None:
    """Latest release tag of an action repo, falling back to the newest tag."""
    try:
        repo = gh.get_repo(repo_name)
    except (GithubException, UnknownObjectException) as exc:
        logger.warning("Failed to get repo %s: %s", repo_name, exc)
        return None

    try:
        return repo.get_latest_release().tag_name
    except GithubException:
        pass

    try:
        tag = next(iter(repo.get_tags()), None)
        return tag.name if tag else None
    except Exception as exc:
        logger.warning("Failed to resolve latest version for %s: %s", repo_name, exc)
    return None


async def _cached_resolve_ref_to_sha(
    gh: Github, cache: aioredis.Redis | None, repo: str, ref: str
) -> str | None:
    return await cached_fetch(
        cache,
        f"{_SHA_CACHE_PREFIX}{repo}@{ref}",
        lambda: asyncio.to_thread(_resolve_ref_to_sha_sync, gh, repo, ref),
    )


async def _cached_get_latest_version(
    gh: Github, cache: aioredis.Redis | None, repo: str
) -> str | None:
    return await cached_fetch(
        cache,
        f"{_VERSION_CACHE_PREFIX}{repo}",
        lambda: asyncio.to_thread(_get_latest_version_sync, gh, repo),
    )


async def resolve_action_shas(
    workflow_content: str, gh: Github | None = None
) -> dict[str, str]:
    """Return a map of 'owner/repo@ref' -> commit SHA for the LLM prompt.

    Resolves every ref already present in the workflow to its exact commit SHA
    — never a newer version — so the fix keeps the version pinned as-is
    (upgrades are Dependabot's job, not ours). For well-known actions the LLM
    might introduce fresh (not already referenced anywhere in the workflow),
    the latest version is also resolved so the LLM has a sensible default to
    pin to. All lookups are cached in Redis with a 24-hour TTL; on cache
    failure the resolver falls back to direct API calls.

    Pass an authenticated ``gh`` instance (e.g. built from a GitHub App
    installation token) to use the 5 000 req/h authenticated rate limit instead
    of the 60 req/h unauthenticated limit. When omitted an unauthenticated
    client is created as a fallback.
    """
    refs = _parse_action_refs(workflow_content)
    new_well_known_repos = set(WELL_KNOWN_ACTIONS) - _referenced_repos(workflow_content)

    cache = open_cache()
    if gh is None:
        gh = Github()

    sha_map: dict[str, str] = {}
    try:
        for repo in sorted(new_well_known_repos):
            latest = await _cached_get_latest_version(gh, cache, repo)
            if latest:
                refs.add((repo, latest))
        for repo, ref in sorted(refs):
            sha = await _cached_resolve_ref_to_sha(gh, cache, repo, ref)
            if sha:
                sha_map[f"{repo}@{ref}"] = sha
    finally:
        await close_cache(cache)

    return sha_map


async def resolve_and_pin_refs(content: str, gh: Github | None = None) -> str:
    """Pin every unpinned ``uses: owner/repo@tag`` reference in ``content`` to
    its commit SHA, appending the original tag as a comment.

    This is the deterministic backstop for actions the fix-generation LLM adds
    that aren't in ``WELL_KNOWN_ACTIONS`` or the workflow's own pre-existing
    refs (so the LLM had no SHA to pin to and left it as a mutable tag,
    tripping ``unpinned_actions`` right back). A ref that
    doesn't resolve (private repo, unknown tag, network failure) is left
    untouched — this never invents a SHA.
    """
    refs = _parse_action_refs(content)
    if not refs:
        return content

    cache = open_cache()
    if gh is None:
        gh = Github()

    pinned = content
    try:
        for repo, ref in sorted(refs):
            sha = await _cached_resolve_ref_to_sha(gh, cache, repo, ref)
            if not sha:
                continue
            pattern = re.compile(
                rf"uses:(\s+){re.escape(repo)}@{re.escape(ref)}(?=\s|$)"
            )
            pinned = pattern.sub(rf"uses:\g<1>{repo}@{sha} # {ref}", pinned)
    finally:
        await close_cache(cache)

    return pinned


async def resolve_pinned_ref(ref: str, gh: Github | None = None) -> str:
    """Resolve a single ``owner/repo@tag`` ref to ``owner/repo@sha # tag``.

    Returns ``ref`` unchanged if it's already a commit SHA or can't be
    resolved (private repo, unknown tag, network failure) — this never
    invents a SHA, matching ``resolve_and_pin_refs``.
    """
    match = re.fullmatch(r"([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)@(.+)", ref)
    if not match:
        return ref
    repo, tag = match.group(1), match.group(2)
    if re.fullmatch(r"[0-9a-f]{40}", tag):
        return ref

    cache = open_cache()
    if gh is None:
        gh = Github()
    try:
        sha = await _cached_resolve_ref_to_sha(gh, cache, repo, tag)
    finally:
        await close_cache(cache)

    return f"{repo}@{sha} # {tag}" if sha else ref
