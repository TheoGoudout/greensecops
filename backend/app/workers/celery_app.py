from celery import Celery

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
        "app.workers.tasks.installation_sync.*": {"queue": "analysis"},
    },
)
