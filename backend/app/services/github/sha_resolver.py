import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_ACTION_USE_RE = re.compile(r"uses:\s+([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)@([^\s#]+)")

# Actions commonly introduced by the LLM when fixing workflows.
# Pre-resolving their SHAs prevents the LLM from inventing hashes.
WELL_KNOWN_ACTIONS: list[tuple[str, str]] = [
    ("actions/cache", "v4"),
    ("actions/cache", "v3"),
    ("actions/upload-artifact", "v4"),
    ("actions/download-artifact", "v4"),
]


def _parse_action_refs(workflow_content: str) -> set[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for match in _ACTION_USE_RE.finditer(workflow_content):
        repo, ref = match.group(1), match.group(2)
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            continue
        refs.add((repo, ref))
    return refs


async def _resolve_ref_to_sha(
    client: httpx.AsyncClient, repo: str, ref: str
) -> str | None:
    for url in [
        f"https://api.github.com/repos/{repo}/git/ref/tags/{ref}",
        f"https://api.github.com/repos/{repo}/git/ref/heads/{ref}",
    ]:
        try:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code != 200:
                continue
            data: dict[str, Any] = resp.json()
            obj = data.get("object", {})
            sha: str = obj.get("sha", "")
            if obj.get("type") == "tag":
                tag_resp = await client.get(obj.get("url", ""), timeout=10.0)
                if tag_resp.status_code == 200:
                    sha = tag_resp.json().get("object", {}).get("sha", sha)
            return sha or None
        except Exception as exc:
            logger.warning("Failed to resolve SHA for %s@%s: %s", repo, ref, exc)
    return None


async def resolve_extra_shas(existing_map: dict[str, str]) -> dict[str, str]:
    """Extend existing_map with SHAs for well-known actions not already resolved."""
    needed = [
        (repo, ref)
        for repo, ref in WELL_KNOWN_ACTIONS
        if f"{repo}@{ref}" not in existing_map
    ]
    if not needed:
        return existing_map

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    result = dict(existing_map)
    async with httpx.AsyncClient(headers=headers) as client:
        for repo, ref in needed:
            sha = await _resolve_ref_to_sha(client, repo, ref)
            if sha:
                result[f"{repo}@{ref}"] = sha
    return result


async def resolve_action_shas(workflow_content: str) -> dict[str, str]:
    """Return map of 'owner/repo@ref' -> commit SHA for all pinnable actions."""
    refs = _parse_action_refs(workflow_content)
    if not refs:
        return {}

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    sha_map: dict[str, str] = {}
    async with httpx.AsyncClient(headers=headers) as client:
        for repo, ref in refs:
            sha = await _resolve_ref_to_sha(client, repo, ref)
            if sha:
                sha_map[f"{repo}@{ref}"] = sha

    return sha_map
