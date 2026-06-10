from app.workers.celery_app import celery_app


@celery_app.task(name="fix_generation.run", bind=True, max_retries=3)
def run_fix_generation(self: object, issue_id: str) -> dict[str, str]:
    return {"status": "not_implemented", "issue_id": issue_id}
