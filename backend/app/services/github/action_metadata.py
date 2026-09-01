"""Resolve what GitHub knows about each action a workflow pins.

Five rules need facts no workflow file contains: whether a pinned SHA is a
commit of the repository it names, whether it is still reachable, whether the
version comment beside it is true, whether the action is archived, and whether a
symbolic ref names both a branch and a tag at once. This module answers those
questions and nothing else; the rules read the answers out of
``input.__actions__``.

The governing invariant is that **an unanswered question must never become a
finding**. Every entry carries a ``lookup`` status, and every rule requires it to
be ``ok`` before reading anything else. Without that, a private or renamed
repository — which the API reports the same way as a missing commit — would fire
``stale_action_ref`` on every internal composite action on every scan. Rules key
on present-and-wrong, never on absent, which is the constraint
``docs/rule-authoring.rst`` records as the sharpest one on the AWS rules; it is
paid up front here rather than inherited.
"""

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import redis.asyncio as aioredis
from github import Github
from github.GithubException import GithubException, UnknownObjectException

from app.services.ref_cache import cached_fetch, close_cache, open_cache

logger = logging.getLogger(__name__)

# `uses: owner/repo[/subpath]@ref`, excluding local (`./…`) and Docker
# (`docker://…`) references, which name nothing on GitHub.
_USES_RE = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)(?:/[^@]*)?@(?P<ref>.+)$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_META_CACHE_PREFIX = "action_meta:"
_OK_TTL = 24 * 60 * 60

# A failed lookup is cached briefly and nothing more. Caching it for a day would
# let one rate-limit window or one network blip silence these rules until
# tomorrow, which is the failure mode nobody would notice.
_FAILURE_TTL = 300

# Stop before the installation token's budget is gone; other work in the same
# scan needs it.
_RATE_LIMIT_FLOOR = 200

# Enumeration caps. Past these the answer becomes "undetermined" rather than a
# guess — a wrong "unreachable" is a critical-looking finding about a healthy
# pin.
_MAX_TAGS = 100
_MAX_BRANCHES = 30


@dataclass(frozen=True)
class ActionMetadata:
    """What GitHub says about one `owner/repo@ref`."""

    lookup: str  # ok | repo_not_found | forbidden | rate_limited | error
    ref_kind: str  # sha | symbolic
    archived: bool | None = None
    commit_exists: bool | None = None
    reachability: str = "undetermined"  # reachable | unreachable | undetermined
    tags_at_sha: list[str] = field(default_factory=list)
    tag_lookup: str = "partial"  # complete | partial
    default_branch: str | None = None
    # For a symbolic ref only: which kinds of ref actually carry that name
    # upstream. Empty when the question was not asked or could not be answered,
    # which is what keeps `ref_confusion` silent rather than guessing.
    symbolic_ref_kinds: list[str] = field(default_factory=list)  # branch | tag


def parse_uses(uses: str) -> tuple[str, str] | None:
    """``owner/repo@ref`` → (``owner/repo``, ``ref``), or None if not resolvable."""
    if uses.startswith("./") or uses.startswith("docker://"):
        return None
    match = _USES_RE.match(uses)
    if not match:
        return None
    return f"{match.group('owner')}/{match.group('repo')}", match.group("ref")


def _describe_sync(gh: Github, repo_name: str, ref: str) -> ActionMetadata:
    """One `owner/repo@ref`, cheapest API call first."""
    is_sha = bool(_SHA_RE.match(ref))
    ref_kind = "sha" if is_sha else "symbolic"

    try:
        repo = gh.get_repo(repo_name)
    except UnknownObjectException:
        return ActionMetadata(lookup="repo_not_found", ref_kind=ref_kind)
    except GithubException as exc:
        status = getattr(exc, "status", None)
        if status == 403:
            return ActionMetadata(lookup="forbidden", ref_kind=ref_kind)
        if status == 404:
            return ActionMetadata(lookup="repo_not_found", ref_kind=ref_kind)
        logger.warning("Failed to read %s: %s", repo_name, exc)
        return ActionMetadata(lookup="error", ref_kind=ref_kind)

    archived = bool(repo.archived)
    default_branch = repo.default_branch

    if not is_sha:
        # A symbolic ref moves by definition; the pinning rules own that, and
        # reachability is not a question worth asking about it. What *is* worth
        # asking is whether the name is unambiguous upstream — see
        # `_symbolic_ref_kinds`.
        return ActionMetadata(
            lookup="ok",
            ref_kind=ref_kind,
            archived=archived,
            default_branch=default_branch,
            symbolic_ref_kinds=_symbolic_ref_kinds(repo, ref),
        )

    try:
        repo.get_commit(ref)
    except (UnknownObjectException, GithubException):
        # The object is not in this repository's network at all.
        return ActionMetadata(
            lookup="ok",
            ref_kind=ref_kind,
            archived=archived,
            commit_exists=False,
            reachability="undetermined",
            default_branch=default_branch,
        )

    reachability, tags_at_sha, tag_lookup = _reachability(repo, ref, default_branch)
    return ActionMetadata(
        lookup="ok",
        ref_kind=ref_kind,
        archived=archived,
        commit_exists=True,
        reachability=reachability,
        tags_at_sha=tags_at_sha,
        tag_lookup=tag_lookup,
        default_branch=default_branch,
    )


def _symbolic_ref_kinds(repo: Any, ref: str) -> list[str]:
    """Which kinds of ref carry the name ``ref`` in ``repo``: branch, tag, both.

    Git resolves an ambiguous name by a precedence rule rather than by asking,
    so an action pinned to a name that is both a branch and a tag runs whichever
    one that rule picks — not necessarily the one the author meant. Answering
    this costs two cheap ref lookups and only for symbolic refs, which are a
    minority of `uses:` in any repository that pins.

    Returns ``[]`` on any error rather than a partial answer. `ref_confusion`
    requires *both* kinds to be present before it reports, so an empty or
    one-element list is silent — the same present-and-wrong discipline the rest
    of this module keeps.
    """
    kinds: list[str] = []
    try:
        repo.get_branch(ref)
        kinds.append("branch")
    except (UnknownObjectException, GithubException):
        pass
    except Exception:  # a lookup must never fail a scan
        return []

    try:
        repo.get_git_ref(f"tags/{ref}")
        kinds.append("tag")
    except (UnknownObjectException, GithubException):
        pass
    except Exception:  # a lookup must never fail a scan
        return []

    return kinds


def _tags_at_sha(repo: Any, sha: str) -> tuple[list[str], str]:
    """Which of ``repo``'s tags point at ``sha``, and was the scan exhaustive?

    Returns the lookup state alongside the tags: ``complete`` when every tag was
    examined, ``partial`` when ``_MAX_TAGS`` cut the scan short, and ``failed``
    when GitHub refused — which the caller must not read as "no tags", since an
    unanswered question and a negative answer are different facts here.
    """
    tags_at_sha: list[str] = []
    try:
        seen = 0
        for tag in repo.get_tags():
            seen += 1
            if seen > _MAX_TAGS:
                return tags_at_sha, "partial"
            if tag.commit.sha == sha:
                tags_at_sha.append(tag.name)
    except GithubException:
        return tags_at_sha, "failed"
    return tags_at_sha, "complete"


def _reachability(
    repo: Any, sha: str, default_branch: str
) -> tuple[str, list[str], str]:
    """Is ``sha`` on a branch or tag of ``repo``, and which tags point at it?

    Forks share an object store with their parent, so a commit pushed only to a
    fork answers 200 from the parent's URL while belonging to no ref of it. That
    gap is the whole point of the check — but it also means the only honest
    answers are "definitely reachable" and "definitely not among what we
    enumerated", so enumeration limits produce ``undetermined`` rather than a
    guess.
    """
    try:
        comparison = repo.compare(default_branch, sha)
        if comparison.status in ("identical", "behind"):
            return "reachable", [], "partial"
    except GithubException:
        pass

    tags_at_sha, tag_lookup = _tags_at_sha(repo, sha)
    if tag_lookup == "failed":
        return "undetermined", tags_at_sha, "partial"
    if tags_at_sha:
        return "reachable", tags_at_sha, tag_lookup

    try:
        branches = list(repo.get_branches()[:_MAX_BRANCHES])
        if len(branches) >= _MAX_BRANCHES:
            return "undetermined", tags_at_sha, tag_lookup
        for branch in branches:
            comparison = repo.compare(branch.name, sha)
            if comparison.status in ("identical", "behind"):
                return "reachable", tags_at_sha, tag_lookup
    except GithubException:
        return "undetermined", tags_at_sha, tag_lookup

    return "unreachable", tags_at_sha, tag_lookup


def _budget_exhausted(gh: Github) -> bool:
    try:
        remaining, _ = gh.rate_limiting
    except Exception:  # never let bookkeeping fail a scan
        return False
    return bool(remaining) and remaining < _RATE_LIMIT_FLOOR


async def _describe_cached(
    gh: Github, cache: aioredis.Redis | None, repo_name: str, ref: str
) -> dict[str, Any]:
    async def fetch() -> str | None:
        meta = await asyncio.to_thread(_describe_sync, gh, repo_name, ref)
        return json.dumps(asdict(meta))

    raw = await cached_fetch(
        cache,
        f"{_META_CACHE_PREFIX}{repo_name}@{ref}",
        fetch,
        ttl_for=lambda value: _OK_TTL if '"lookup": "ok"' in value else _FAILURE_TTL,
    )
    if not raw:
        return asdict(ActionMetadata(lookup="error", ref_kind="sha"))
    return dict(json.loads(raw))


async def collect_action_metadata(
    workflow_contents: Sequence[str],
    gh: Github | None = None,
    *,
    budget_seconds: float = 20.0,
) -> dict[str, dict[str, Any]]:
    """Resolve every ``uses:`` across ``workflow_contents``. Never raises.

    Whatever is resolved inside ``budget_seconds`` is returned; the rest is
    simply absent, and an absent entry makes the four rules that read this
    silent for that action. A scan must never fail because GitHub was slow, and
    it must never report because GitHub was unreadable.

    Without an authenticated client the anonymous budget is 60 requests an hour,
    which would be spent producing mostly ``rate_limited`` entries — so this
    returns nothing at all rather than half an answer.
    """
    if gh is None:
        logger.info("No authenticated GitHub client; skipping action metadata")
        return {}

    refs: set[str] = set()
    for content in workflow_contents:
        for match in re.finditer(r"uses:\s*(\S+)", content):
            refs.add(match.group(1).strip("\"'"))

    resolved: dict[str, dict[str, Any]] = {}
    cache = open_cache()

    async def run() -> None:
        for uses in sorted(refs):
            parsed = parse_uses(uses)
            if parsed is None:
                continue
            if _budget_exhausted(gh):
                logger.warning("GitHub rate limit floor reached; stopping enrichment")
                return
            repo_name, ref = parsed
            resolved[uses] = await _describe_cached(gh, cache, repo_name, ref)

    try:
        # `resolved` is owned here and mutated in place, so a timeout keeps
        # everything already answered instead of discarding the batch.
        await asyncio.wait_for(run(), timeout=budget_seconds)
    except TimeoutError:
        logger.warning("Action metadata budget exhausted after %ss", budget_seconds)
    except Exception:  # enrichment is best-effort by contract
        logger.warning("Action metadata collection failed", exc_info=True)
    finally:
        await close_cache(cache)

    return resolved
