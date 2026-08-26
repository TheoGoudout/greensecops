from __future__ import annotations

import asyncio
from typing import Any

from app.services.ansible.parser import merge_ansible_files
from app.services.engines import ANSIBLE_ENGINE
from app.services.github.fetch import fetch_ansible_files as _fetch_ansible_files
from app.services.opa.evaluator import evaluate_ansible
from app.services.scan_runner import ScanFetchError, run_file_scan
from app.services.scan_support import scan_lock
from app.workers.celery_app import celery_app

# Kept as this module's own name so `patch("…ansible_analysis.AnsibleFetchError")`
# and the retry below both still refer to one exception.
AnsibleFetchError = ScanFetchError


def _analyse(fetched: Any) -> Any:
    """Build the envelope document from the fetched files and evaluate it."""
    return asyncio.run(
        _evaluate(merge_ansible_files([(f.path, f.content) for f in fetched]))
    )


async def _evaluate(document: dict[str, Any]) -> Any:
    return await evaluate_ansible(document)


def _run_ansible_scan_impl(
    ansible_project_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    # `_fetch_ansible_files` and `_analyse` are read from this module's globals
    # at call time, so the tests that patch them here still take effect.
    return run_file_scan(
        ANSIBLE_ENGINE,
        ansible_project_id,
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger,
        billable=billable,
        fetch_files=_fetch_ansible_files,
        analyse=_analyse,
    )


@celery_app.task(name="ansible_analysis.run", bind=True, max_retries=3)
def run_ansible_scan(
    self: Any,  # celery bound task instance
    ansible_project_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    # Per-project lock: concurrent scans of the same project race on
    # AnsibleFinding upserts and duplicate AnsibleScan rows.
    with scan_lock(f"ansible_scan:{ansible_project_id}") as acquired:
        if not acquired:
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_ansible_scan_impl(
                billable=billable,
                ansible_project_id=ansible_project_id,
                branch=branch,
                commit_sha=commit_sha,
                trigger=trigger,
            )
        except AnsibleFetchError as exc:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
