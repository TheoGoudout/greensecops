import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.models import (
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    User,
    UserCreate,
    UserUpdate,
)
from app.services import state_machines as sm


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


# ─── Organizations / installations ────────────────────────────────────────────


def upsert_organization(
    *,
    session: Session,
    github_org_id: int | None,
    name: str,
    installation_id: int | None,
) -> Organization:
    """Find an org by github_org_id (then installation_id), else create it.

    Keyed on unique columns so it is safe under webhook replay / Celery retry.
    """
    org: Organization | None = None
    if github_org_id is not None:
        org = session.exec(
            select(Organization).where(Organization.github_org_id == github_org_id)
        ).first()
    if org is None and installation_id is not None:
        org = session.exec(
            select(Organization).where(Organization.installation_id == installation_id)
        ).first()

    if org is None:
        org = Organization(
            github_org_id=github_org_id,
            name=name,
            installation_id=installation_id,
        )
        session.add(org)
    else:
        org.name = name
        if github_org_id is not None:
            org.github_org_id = github_org_id
        if installation_id is not None:
            org.installation_id = installation_id
        session.add(org)
    session.commit()
    session.refresh(org)
    return org


def add_org_owner(
    *, session: Session, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrgMember:
    """Idempotently link a user as an owner of an organization."""
    member = session.get(OrgMember, (org_id, user_id))
    if member is None:
        member = OrgMember(org_id=org_id, user_id=user_id, role=OrgRole.owner)
        session.add(member)
        session.commit()
        session.refresh(member)
    return member


def upsert_repository(
    *,
    session: Session,
    org_id: uuid.UUID,
    github_repo_id: int,
    full_name: str,
    installation_id: int,
    default_branch: str,
    is_private: bool = False,
) -> Repository:
    """Upsert a repository by its unique github_repo_id; preserves enabled state on update."""
    stmt = (
        pg_insert(Repository)
        .values(
            id=uuid.uuid4(),
            org_id=org_id,
            github_repo_id=github_repo_id,
            full_name=full_name,
            installation_id=installation_id,
            default_branch=default_branch,
            enabled=False,
            is_private=is_private,
        )
        .on_conflict_do_update(
            index_elements=["github_repo_id"],
            set_={
                "org_id": org_id,
                "full_name": full_name,
                "installation_id": installation_id,
                "default_branch": default_branch,
                "is_private": is_private,
            },
        )
        .returning(Repository)
    )
    repo = session.scalars(stmt).one()
    session.commit()
    return repo


def disable_repositories_by_github_ids(
    *, session: Session, github_repo_ids: list[int]
) -> int:
    """Repos removed from an installation: clear ``enabled`` and drive the
    RepositoryMachine to ``inaccessible`` (syncing ``is_accessible``)."""
    if not github_repo_ids:
        return 0
    repos = session.exec(
        select(Repository).where(Repository.github_repo_id.in_(github_repo_ids))  # type: ignore[attr-defined]
    ).all()
    for repo in repos:
        repo.enabled = False
        sm.try_advance(repo, sm.RepositoryMachine, "lose_access")
        sm.sync_access_flag(repo)
        session.add(repo)
    session.commit()
    return len(repos)


def mark_repositories_inaccessible_by_installation_id(
    *, session: Session, installation_id: int, event: str = "lose_access"
) -> list[Repository]:
    """Drive repos of a deleted/suspended installation off ``active``.

    ``event`` selects the cause: ``suspend`` (installation suspended, reversible
    via ``unsuspend``) or ``lose_access`` (installation deleted). ``enabled`` is
    cleared for both; ``is_accessible`` is synced from the new status.
    """
    repos = list(
        session.exec(
            select(Repository).where(Repository.installation_id == installation_id)
        ).all()
    )
    for repo in repos:
        repo.enabled = False
        sm.try_advance(repo, sm.RepositoryMachine, event)
        sm.sync_access_flag(repo)
        session.add(repo)
    session.commit()
    return repos


def restore_repositories_accessibility_by_installation_id(
    *, session: Session, installation_id: int
) -> list[Repository]:
    """Restore accessibility for repos under a reinstated (unsuspended)
    installation: drive the machine back to ``active`` and sync
    ``is_accessible``. ``enabled`` (user opt-in) is intentionally left as-is."""
    repos = list(
        session.exec(
            select(Repository).where(Repository.installation_id == installation_id)
        ).all()
    )
    for repo in repos:
        # A suspended repo unsuspends; an inaccessible one (edge case) regains
        # access — try both so accessibility is restored either way.
        if not sm.try_advance(repo, sm.RepositoryMachine, "unsuspend"):
            sm.try_advance(repo, sm.RepositoryMachine, "regain_access")
        sm.sync_access_flag(repo)
        session.add(repo)
    session.commit()
    return repos
