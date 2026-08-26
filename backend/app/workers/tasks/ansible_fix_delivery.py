from typing import Any

from app.services.engines import ANSIBLE_ENGINE
from app.services.file_fix_delivery import FixFetchError, deliver_file_fixes
from app.services.github.fetch import fetch_ansible_files as _fetch_ansible_files
from app.workers.celery_app import celery_app


@celery_app.task(name="ansible_fix_delivery.deliver", bind=True, max_retries=3)
def deliver_ansible_fixes(
    self: Any,  # celery bound task instance
    ansible_project_id: str,
    force: bool = False,
) -> dict[str, str]:
    """Deliver a project's ready fixes as one PR (one file change each)."""
    try:
        return deliver_file_fixes(
            ANSIBLE_ENGINE,
            ansible_project_id,
            force,
            # Passed in rather than held on the spec: this module-level name is
            # the seam the tests patch, and a reference stored on the spec would
            # not see that patch.
            _fetch_ansible_files,
        )
    except FixFetchError as exc:
        raise self.retry(exc=exc, countdown=30) from exc
