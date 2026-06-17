import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Analysis,
    AnalysisStatus,
    OrgMember,
    Repository,
    RepositoryPublic,
    User,
)
from app.services.scoring import score_to_grade

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _user_org_ids(session: SessionDep, user: User) -> set[uuid.UUID]:
    return set(
        session.exec(select(OrgMember.org_id).where(OrgMember.user_id == user.id)).all()
    )


def _compute_repo_grade(
    session: Session, repo_id: uuid.UUID
) -> tuple[float | None, str | None, int]:
    """Return (avg_score, grade, workflow_count) from latest analyses per workflow file."""
    analyses = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(Analysis.workflow_file_id, Analysis.created_at.desc())  # type: ignore[arg-type]
    ).all()

    seen: set[uuid.UUID] = set()
    latest_per_file: list[Analysis] = []
    for a in analyses:
        if a.workflow_file_id not in seen:
            seen.add(a.workflow_file_id)
            latest_per_file.append(a)

    if not latest_per_file:
        return None, None, 0

    avg = sum(a.score for a in latest_per_file if a.score is not None) / len(  # type: ignore[arg-type]
        latest_per_file
    )
    return round(avg, 1), score_to_grade(avg), len(latest_per_file)


def _compute_grades_batch(
    session: Session, repo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[float | None, str | None]]:
    """Batch-compute (avg_score, grade) for multiple repos in a single query."""
    if not repo_ids:
        return {}

    analyses = session.exec(
        select(Analysis)
        .where(Analysis.repo_id.in_(repo_ids))  # type: ignore[attr-defined]
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(Analysis.workflow_file_id, Analysis.created_at.desc())  # type: ignore[arg-type]
    ).all()

    seen: set[uuid.UUID] = set()
    scores_by_repo: dict[uuid.UUID, list[float]] = defaultdict(list)
    for a in analyses:
        if a.workflow_file_id not in seen:
            seen.add(a.workflow_file_id)
            if a.score is not None:
                scores_by_repo[a.repo_id].append(a.score)  # type: ignore[arg-type]

    result: dict[uuid.UUID, tuple[float | None, str | None]] = {}
    for repo_id in repo_ids:
        scores = scores_by_repo.get(repo_id, [])
        if scores:
            avg = round(sum(scores) / len(scores), 1)
            result[repo_id] = (avg, score_to_grade(avg))
        else:
            result[repo_id] = (None, None)
    return result


def _to_public(
    repo: Repository, avg_score: float | None, grade: str | None
) -> RepositoryPublic:
    return RepositoryPublic(
        id=repo.id,
        full_name=repo.full_name,
        enabled=repo.enabled,
        default_branch=repo.default_branch,
        created_at=repo.created_at,
        avg_score=avg_score,
        grade=grade,
    )


@router.get("/", response_model=list[RepositoryPublic])
def list_repositories(
    session: SessionDep,
    current_user: CurrentUser,
    org_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[RepositoryPublic]:
    query = select(Repository)
    if not current_user.is_superuser:
        query = query.where(
            Repository.org_id.in_(  # type: ignore[attr-defined]
                select(OrgMember.org_id).where(OrgMember.user_id == current_user.id)
            )
        )
    if org_id:
        query = query.where(Repository.org_id == org_id)
    if enabled is not None:
        query = query.where(Repository.enabled == enabled)
    query = query.order_by(Repository.full_name).offset(skip).limit(limit)  # type: ignore[arg-type]
    repos = list(session.exec(query).all())
    grades = _compute_grades_batch(session, [r.id for r in repos])
    return [_to_public(r, *grades.get(r.id, (None, None))) for r in repos]


@router.get("/{repo_id}", response_model=RepositoryPublic)
def get_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> RepositoryPublic:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not current_user.is_superuser and repo.org_id not in _user_org_ids(
        session, current_user
    ):
        raise HTTPException(status_code=404, detail="Repository not found")
    avg_score, grade, _ = _compute_repo_grade(session, repo_id)
    return _to_public(repo, avg_score, grade)


@router.patch("/{repo_id}/toggle")
def toggle_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    enabled: bool,
) -> dict[str, str | bool]:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not current_user.is_superuser and repo.org_id not in _user_org_ids(
        session, current_user
    ):
        raise HTTPException(status_code=404, detail="Repository not found")
    repo.enabled = enabled
    session.add(repo)
    session.commit()
    return {"repo_id": str(repo_id), "enabled": enabled}
