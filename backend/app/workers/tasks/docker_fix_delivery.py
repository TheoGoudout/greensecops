from typing import Any

from app.services.engines import DOCKER_ENGINE
from app.services.file_fix_delivery import FixFetchError, deliver_file_fixes
from app.workers.celery_app import celery_app
from app.workers.tasks.docker_analysis import _fetch_docker_files


@celery_app.task(name="docker_fix_delivery.deliver", bind=True, max_retries=3)
def deliver_docker_fixes(
    self: Any,  # noqa: ANN401 — celery bound task instance
    docker_target_id: str,
    force: bool = False,
) -> dict[str, str]:
    """Deliver a Docker target's ready fixes as one PR (one file change each)."""
    try:
        return deliver_file_fixes(
            DOCKER_ENGINE,
            docker_target_id,
            force,
            # Passed in rather than held on the spec: this module-level name is
            # the seam the tests patch, and a reference stored on the spec would
            # not see that patch.
            _fetch_docker_files,
        )
    except FixFetchError as exc:
        raise self.retry(exc=exc, countdown=30) from exc
