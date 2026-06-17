import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Analysis,
    AnalysisPublic,
    AnalysisStatus,
    Repository,
)
from app.workers.tasks.static_analysis import run_static_analysis

router = APIRouter(prefix="/analyses", tags=["analyses"])


def _to_analysis_public(analysis: Analysis) -> AnalysisPublic:
    return AnalysisPublic(
        id=analysis.id,
        repo_id=analysis.repo_id,
        workflow_file_id=analysis.workflow_file_id,
        workflow_file_path=(
            analysis.workflow_file.path if analysis.workflow_file else None
        ),
        repo_full_name=(analysis.repository.full_name if analysis.repository else None),
        content_hash=analysis.content_hash,
        status=analysis.status,
        score=analysis.score,
        grade=analysis.grade,
        triggered_by=analysis.triggered_by,
        branch=analysis.branch,
        commit_sha=analysis.commit_sha,
        created_at=analysis.created_at,
        completed_at=analysis.completed_at,
    )


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
    return [_to_analysis_public(a) for a in session.exec(query).all()]


@router.get("/{analysis_id}", response_model=AnalysisPublic)
def get_analysis(
    analysis_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> AnalysisPublic:
    analysis = session.get(Analysis, analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _to_analysis_public(analysis)


@router.post("/trigger/{repo_id}", status_code=202)
def trigger_analysis(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    branch: str | None = None,
) -> dict[str, str]:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    run_static_analysis.delay(
        repo_id=str(repo_id),
        branch=branch or repo.default_branch,
        trigger="manual",
    )
    return {"status": "queued", "repo_id": str(repo_id)}
