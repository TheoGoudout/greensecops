"""Fetching an engine's files from GitHub, synchronously, from worker code.

``GitHubAppClient`` is async and needs a Redis connection for its installation-token
cache. Celery tasks and route handlers are sync, so every caller wrapped it the same
way: open a redis client, build a ``GitHubAppClient``, ``await`` one method, close the
client in a ``finally``, and run the whole thing through ``asyncio.run``. That wrapper
was written out five times — once per calling module — and each copy carried its own
``# type: ignore[no-untyped-call]`` for ``aioredis.from_url``.

Worse, four of those copies did not write it at all: they imported
``_fetch_docker_files`` or ``_fetch_terraform_files`` *by their private name* from a
sibling worker module, so ``api/routes/docker.py`` depended on an underscore-prefixed
detail of ``workers/tasks/docker_analysis.py``.

The wrapper lives here once, public. Callers still bind a module-level alias::

    from app.services.github.fetch import fetch_docker_files as _fetch_docker_files

which keeps each module's own patchable seam — the tests replace that attribute per
module, and they still can — while the body they share is written down once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, TypeVar

import redis.asyncio as aioredis

from app.core.config import settings
from app.services.github.app_client import GitHubAppClient

if TYPE_CHECKING:
    from app.models import Repository
    from app.services.github.app_client import (
        DockerFileContent,
        GitHubAppClient,
        TerraformFileContent,
    )

T = TypeVar("T")


def with_client(call: Callable[[GitHubAppClient], Awaitable[Iterable[T]]]) -> list[T]:
    """Run one client call to completion, from sync code.

    The redis client is closed on every path, including when ``call`` raises — a
    leaked connection per failed scan is how a worker runs out of them.
    """

    async def _run() -> list[T]:
        redis_client = aioredis.from_url(settings.REDIS_URL)  # type: ignore[no-untyped-call]
        try:
            return list(await call(GitHubAppClient(redis_client=redis_client)))
        finally:
            await redis_client.aclose()

    return asyncio.run(_run())


def fetch_terraform_files(
    repo: Repository, root_path: str, ref: str | None = None
) -> list[TerraformFileContent]:
    """The ``.tf``/``.tf.json`` files under ``root_path`` at ``ref``."""
    return with_client(
        lambda client: client.fetch_terraform_files(
            repo.installation_id, repo.full_name, root_path, ref=ref
        )
    )


def fetch_docker_files(
    repo: Repository, root_path: str, ref: str | None = None
) -> list[DockerFileContent]:
    """The Dockerfiles and Compose files under ``root_path`` at ``ref``."""
    return with_client(
        lambda client: client.fetch_docker_files(
            repo.installation_id, repo.full_name, root_path, ref=ref
        )
    )
