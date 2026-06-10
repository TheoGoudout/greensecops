from app.workers.celery_app import celery_app


@celery_app.task(name="fix_delivery.deliver", bind=True, max_retries=3)
def deliver_fix(self: object, fix_id: str) -> dict[str, str]:
    return {"status": "not_implemented", "fix_id": fix_id}
