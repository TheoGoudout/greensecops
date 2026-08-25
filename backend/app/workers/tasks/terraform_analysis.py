from __future__ import annotations

import asyncio
from typing import Any

from app.services.engines import TERRAFORM_ENGINE
from app.services.github.fetch import fetch_terraform_files as _fetch_terraform_files
from app.services.opa.evaluator import evaluate_terraform
from app.services.scan_runner import ScanFetchError, run_file_scan
from app.services.scan_support import scan_lock
from app.services.terraform.hcl_parser import merge_terraform_configs
from app.workers.celery_app import celery_app

# Kept as this module's own name so `patch("…terraform_analysis.TerraformFetchError")`
# and the retry below both still refer to one exception.
TerraformFetchError = ScanFetchError


def _analyse(fetched: Any) -> Any:
    """Merge the fetched .tf files into one document and evaluate it."""
    return asyncio.run(
        _evaluate(merge_terraform_configs([(f.path, f.content) for f in fetched]))
    )


async def _evaluate(parsed_config: dict[str, Any]) -> Any:

    return await evaluate_terraform(parsed_config)


def _run_terraform_scan_impl(
    terraform_root_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:
    # `_fetch_terraform_files` and `_analyse` are read from this module's globals
    # at call time, so the tests that patch them here still take effect.
    return run_file_scan(
        TERRAFORM_ENGINE,
        terraform_root_id,
        branch=branch,
        commit_sha=commit_sha,
        trigger=trigger,
        billable=billable,
        fetch_files=_fetch_terraform_files,
        analyse=_analyse,
    )


@celery_app.task(name="terraform_analysis.run", bind=True, max_retries=3)
def run_terraform_scan(
    self: Any,  # celery bound task instance
    terraform_root_id: str,
    branch: str = "",
    commit_sha: str = "",
    trigger: str = "manual",
    billable: bool = True,
) -> dict[str, str | int | float]:

    # Per-root lock: concurrent scans of the same root race on TerraformFinding
    # upserts and duplicate TerraformScan rows.
    with scan_lock(f"terraform_scan:{terraform_root_id}") as acquired:
        if not acquired:
            raise self.retry(countdown=30, max_retries=10)
        try:
            return _run_terraform_scan_impl(
                billable=billable,
                terraform_root_id=terraform_root_id,
                branch=branch,
                commit_sha=commit_sha,
                trigger=trigger,
            )
        except TerraformFetchError as exc:
            raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))
