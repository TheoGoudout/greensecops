from typing import Any

from app.services.engines import TERRAFORM_ENGINE
from app.services.file_fix_delivery import FixFetchError, deliver_file_fixes
from app.workers.celery_app import celery_app
from app.workers.tasks.terraform_analysis import _fetch_terraform_files


@celery_app.task(name="terraform_fix_delivery.deliver", bind=True, max_retries=3)
def deliver_terraform_fixes(
    self: Any,  # celery bound task instance
    terraform_root_id: str,
    force: bool = False,
) -> dict[str, str]:
    """Deliver a Terraform root's ready fixes as one PR (one file change each)."""
    try:
        return deliver_file_fixes(
            TERRAFORM_ENGINE,
            terraform_root_id,
            force,
            # Passed in rather than held on the spec: this module-level name is
            # the seam the tests patch, and a reference stored on the spec would
            # not see that patch.
            _fetch_terraform_files,
        )
    except FixFetchError as exc:
        raise self.retry(exc=exc, countdown=30) from exc
