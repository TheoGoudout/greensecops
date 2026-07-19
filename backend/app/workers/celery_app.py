from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "greensecops",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.tasks.static_analysis",
        "app.workers.tasks.dynamic_analysis",
        "app.workers.tasks.fix_generation",
        "app.workers.tasks.fix_delivery",
        "app.workers.tasks.installation_sync",
        "app.workers.tasks.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue="default",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "static_analysis.*": {"queue": "analysis"},
        "dynamic_analysis.*": {"queue": "analysis"},
        "fix_generation.*": {"queue": "fixes"},
        "fix_delivery.*": {"queue": "fixes"},
        "maintenance.*": {"queue": "analysis"},
        "app.workers.tasks.installation_sync.*": {"queue": "analysis"},
    },
    beat_schedule={
        # Fail analyses/fixes stuck in transient states after worker crashes.
        "sweep-stuck-states": {
            "task": "maintenance.sweep_stuck_states",
            "schedule": crontab(minute=5),  # hourly
        },
        # Recover PR open/closed/merged transitions from missed webhooks.
        "sync-open-pr-states": {
            "task": "maintenance.sync_open_pr_states",
            "schedule": crontab(minute=35, hour="*/6"),
        },
        # Nightly reconciliation pass; content dedup keeps unchanged repos cheap.
        "nightly-reanalysis": {
            "task": "static_analysis.reanalyze_all",
            "schedule": crontab(minute=17, hour=3),
            "kwargs": {"force": False},
        },
        # Re-run recent transient analysis failures (OPA timeouts, network
        # errors) without waiting for the next push; bounded per content hash.
        "retry-transient-analyses": {
            "task": "maintenance.retry_transient_analyses",
            "schedule": crontab(minute=50),  # hourly
        },
    },
)
