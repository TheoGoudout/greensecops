import uuid

from fastapi import APIRouter, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_or_404
from app.api.mappers import to_analysis_public
from app.models import (
    Analysis,
    AnalysisPublic,
    AnalysisStatus,
    Repository,
)
from app.workers.tasks.static_analysis import run_static_analysis

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.get("/", response_model=list[AnalysisPublic])
def list_analyses(
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    grade: str | None = None,
    status: AnalysisStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[AnalysisPublic]:
    query = select(Analysis)
    if repo_id:
        query = query.where(Analysis.repo_id == repo_id)
    if branch:
        query = query.where(Analysis.branch == branch)
    if grade:
        query = query.where(Analysis.grade == grade)
    if status:
        query = query.where(Analysis.status == status)
    query = query.order_by(Analysis.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    return [to_analysis_public(a) for a in session.exec(query).all()]


@router.get("/{analysis_id}", response_model=AnalysisPublic)
def get_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> AnalysisPublic:
    return to_analysis_public(get_or_404(session, Analysis, analysis_id))


@router.post("/trigger/{repo_id}", status_code=202)
def trigger_analysis(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    branch: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    repo = get_or_404(session, Repository, repo_id)
    run_static_analysis.delay(
        repo_id=str(repo_id),
        branch=branch or repo.default_branch,
        trigger="manual",
        force=force,
    )
    return {"status": "queued", "repo_id": str(repo_id)}
