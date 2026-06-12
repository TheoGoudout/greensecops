import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import OrgMember, Repository, RepositoryPublic, User

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _user_org_ids(session: SessionDep, user: User) -> set[uuid.UUID]:
    return set(
        session.exec(select(OrgMember.org_id).where(OrgMember.user_id == user.id)).all()
    )


@router.get("/", response_model=list[RepositoryPublic])
def list_repositories(
    session: SessionDep,
    current_user: CurrentUser,
    org_id: uuid.UUID | None = None,
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[Repository]:
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
    return list(session.exec(query).all())


@router.get("/{repo_id}", response_model=RepositoryPublic)
def get_repository(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Repository:
    repo = session.get(Repository, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not current_user.is_superuser and repo.org_id not in _user_org_ids(
        session, current_user
    ):
        # Avoid leaking existence of repos the caller cannot access.
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo


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
