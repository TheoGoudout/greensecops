import uuid

from fastapi import APIRouter, Depends, Query
from sqlmodel import select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_current_active_superuser,
    get_or_404,
    user_org_ids,
)
from app.api.mappers import to_analysis_public
from app.models import (
    Analysis,
    AnalysisPublic,
    AnalysisStatus,
    Repository,
)
from app.services.events import publisher as events_pub
from app.services.events import schemas as ev
from app.workers.tasks.static_analysis import (
    reanalyze_all_repositories,
    run_static_analysis,
)

router = APIRouter(prefix="/analyses", tags=["analyses"])


@router.get("/", response_model=list[AnalysisPublic])
def list_analyses(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
    branch: str | None = None,
    grade: str | None = None,
    status: AnalysisStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[AnalysisPublic]:
    query = select(Analysis)
    if not current_user.is_superuser:
        query = query.where(
            Analysis.repo_id.in_(  # type: ignore[attr-defined]
                select(Repository.id).where(
                    Repository.org_id.in_(user_org_ids(session, current_user))  # type: ignore[attr-defined]
                )
            )
        )
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
    current_user: CurrentUser,
) -> AnalysisPublic:
    analysis = get_or_404(session, Analysis, analysis_id)
    if not current_user.is_superuser:
        authorize_repo(
            session, current_user, analysis.repo_id, detail="Analysis not found"
        )
    return to_analysis_public(analysis)


@router.post("/trigger/{repo_id}", status_code=202)
def trigger_analysis(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
    force: bool = True,
) -> dict[str, str]:
    repo = authorize_repo(session, current_user, repo_id)
    from app.api.routes.billing import enforce_quota

    enforce_quota(session, current_user, "analyses")
    effective_branch = branch or repo.default_branch
    run_static_analysis.delay(
        repo_id=str(repo_id),
        branch=effective_branch,
        trigger="manual",
        force=force,
    )
    events_pub.publish_event(
        ev.analysis_queued(str(repo.org_id), str(repo_id), effective_branch, "manual")
    )
    return {"status": "queued", "repo_id": str(repo_id)}


@router.post(
    "/reanalyze-all",
    status_code=202,
    dependencies=[Depends(get_current_active_superuser)],
)
def reanalyze_all() -> dict[str, str]:
    """Fan out a fresh static analysis across all enabled repositories.

    Same mechanism used automatically when a release ships new rules; exposed
    so operators can re-apply rules on demand without a redeploy.
    """
    reanalyze_all_repositories.delay()
    return {"status": "queued"}
