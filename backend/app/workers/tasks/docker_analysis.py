from __future__ import annotations

import asyncio
from typing import Any

from app.services.docker.merge import merge_docker_files
from app.services.engines import DOCKER_ENGINE
from app.services.github.fetch import fetch_docker_files as _fetch_docker_files
from app.services.scan_runner import ScanFetchError, run_file_scan
from app.workers.celery_app import celery_app

# Kept as this module's own name so the retry below and any caller catching it
# both still refer to one exception.
DockerFetchError = ScanFetchError


def _analyse(fetched: Any) -> Any:
    """Merge the fetched Dockerfiles and Compose files, then evaluate them."""
    return asyncio.run(
        _evaluate(merge_docker_files([(f.path, f.content) for f in fetched]))
    )


async def _evaluate(merged_document: dict[str, Any]) -> Any:
    from app.services.opa.evaluator import evaluate_docker

    return await evaluate_docker(merged_document)


def _run_docker_scan_impl(
    docker_target_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    # `_fetch_docker_files` and `_analyse` are read from this module's globals at
    # call time, so the tests that patch them here still take effect.
    return run_file_scan(
        DOCKER_ENGINE,
        docker_target_id,
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger,
        billable=billable,
        fetch_files=_fetch_docker_files,
        analyse=_analyse,
    )


@celery_app.task(name="docker_analysis.run", bind=True, max_retries=3)
def run_docker_scan(
    self: Any,  # celery bound task instance
    docker_target_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    from app.services.scan_support import scan_lock

    # Per-target lock: concurrent scans of the same target race on DockerFinding
    # upserts and duplicate DockerScan rows.
    with scan_lock(f"docker_scan:{docker_target_id}") as acquired:
        if not acquired:
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_docker_scan_impl(
                billable=billable,
                docker_target_id=docker_target_id,
                branch=branch,
                commit_sha=commit_sha,
                trigger=trigger,
            )
        except DockerFetchError as exc:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
