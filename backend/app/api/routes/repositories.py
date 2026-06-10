import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import Repository, RepositoryPublic

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("/", response_model=list[RepositoryPublic])
def list_repositories(
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    org_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[Repository]:
    query = select(Repository)
    if org_id:
        query = query.where(Repository.org_id == org_id)
    if enabled is not None:
        query = query.where(Repository.enabled == enabled)
    query = query.order_by(Repository.full_name).offset(skip).limit(limit)  # type: ignore[arg-type]
    return list(session.exec(query).all())


@router.get("/{repo_id}", response_model=RepositoryPublic)
def get_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> Repository:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


@router.patch("/{repo_id}/toggle")
def toggle_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    enabled: bool,
) -> dict[str, str | bool]:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    repo.enabled = enabled
    session.add(repo)
    session.commit()
    return {"repo_id": str(repo_id), "enabled": enabled}
