from app.workers.celery_app import celery_app


@celery_app.task(name="static_analysis.run", bind=True, max_retries=3)
def run_static_analysis(self: object, analysis_id: str) -> dict[str, str]:
    return {"status": "not_implemented", "analysis_id": analysis_id}
