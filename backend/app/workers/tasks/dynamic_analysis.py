from app.workers.celery_app import celery_app


@celery_app.task(name="dynamic_analysis.run", bind=True, max_retries=3)
def run_dynamic_analysis(self: object, telemetry_run_id: str) -> dict[str, str]:
    return {"status": "not_implemented", "telemetry_run_id": telemetry_run_id}
