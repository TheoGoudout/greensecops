from fastapi import APIRouter, Request

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("/ingest")
async def ingest_telemetry(request: Request) -> dict[str, str]:
    return {"message": "Telemetry ingestion - not yet implemented"}
