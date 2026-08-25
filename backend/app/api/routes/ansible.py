import uuid

from fastapi import HTTPException
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.engine_routes import get_target_for_user
from app.api.mappers import (
    to_ansible_finding_public,
    to_ansible_project_public,
    to_ansible_scan_public,
)
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE
from app.models import (
    AnsibleFilePublic,
    AnsibleFinding,
    AnsibleFindingPublic,
    AnsibleProject,
    AnsibleProjectCreate,
    AnsibleProjectPublic,
    AnsibleScan,
    AnsibleScanPublic,
    Repository,
    UsageEngine,
)
from app.services.ansible.discovery import classify_ansible_file
from app.services.billing.quota import enforce_quota
from app.services.engines import ANSIBLE_ENGINE
from app.services.github.fetch import fetch_ansible_files as _fetch_ansible_files
from app.workers.tasks.ansible_analysis import run_ansible_scan

# `project_id` rather than `target_id` or `root_id`: `api/router.ORG_RESOLVERS`
# is keyed by path-parameter *name*, and those two are already taken by Docker
# and Terraform. Reusing one would resolve this engine's role checks against
# the wrong table.
router = RoleRouter(prefix="/ansible-projects", tags=["ansible"])


@router.post("/", role=Role.user, response_model=AnsibleProjectPublic, status_code=201)
def create_ansible_project(
    project_in: AnsibleProjectCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> AnsibleProjectPublic:
    repo = authorize_repo(session, current_user, project_in.repo_id)
    # Normalize so "infra", "/infra", "infra/" and "/infra/" all address the
    # same project — otherwise the (repo_id, root_path) uniqueness constraint
    # would let a user create near-duplicates that mean the same thing.
    #
    # Unlike Terraform, "" is allowed and means the repository root: an Ansible
    # project frequently *is* the whole repo, with playbooks/ and roles/ at the
    # top level.
    normalized_path = project_in.root_path.strip("/")

    existing = session.exec(
        select(AnsibleProject)
        .where(AnsibleProject.repo_id == repo.id)
        .where(AnsibleProject.root_path == normalized_path)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="This project path is already configured"
        )

    project = AnsibleProject(repo_id=repo.id, root_path=normalized_path)
    session.add(project)
    session.commit()
    session.refresh(project)
    return to_ansible_project_public(project)


@router.get("/", role=Role.user, response_model=list[AnsibleProjectPublic])
def list_ansible_projects(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
) -> list[AnsibleProjectPublic]:
    """List Ansible projects. Omit ``repo_id`` for the org-wide Infrastructure
    page (every project across every repo the user can access); pass it to
    scope to one repo."""
    if repo_id:
        authorize_repo(session, current_user, repo_id)
        query = select(AnsibleProject).where(AnsibleProject.repo_id == repo_id)
    else:
        query = select(AnsibleProject)
        if not current_user.is_superuser:
            query = query.join(
                Repository,
                AnsibleProject.repo_id == Repository.id,  # type: ignore[arg-type]
            ).where(Repository.org_id.in_(user_org_ids(session, current_user)))  # type: ignore[attr-defined]
    projects = session.exec(query.order_by(col(AnsibleProject.root_path))).all()
    return [to_ansible_project_public(p) for p in projects]


@router.patch("/{project_id}/toggle", role=Role.org_admin)
def toggle_ansible_project(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    enabled: bool,
) -> dict[str, str | bool]:
    project = get_target_for_user(ANSIBLE_ENGINE, project_id, session, current_user)
    project.enabled = enabled
    session.add(project)
    session.commit()
    return {"ansible_project_id": str(project_id), "enabled": enabled}


@router.delete("/{project_id}", role=Role.org_admin, status_code=204)
def delete_ansible_project(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    project = get_target_for_user(ANSIBLE_ENGINE, project_id, session, current_user)
    # Cascades to its scans/findings — the user is removing this project, not
    # just disabling it.
    session.delete(project)
    session.commit()


@router.post(
    "/{project_id}/scan",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_ansible_scan(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> dict[str, str]:
    project = get_target_for_user(ANSIBLE_ENGINE, project_id, session, current_user)
    if not project.enabled:
        raise HTTPException(status_code=403, detail="Ansible project is disabled")
    repo = get_or_404(
        session, Repository, project.repo_id, detail="Repository not found"
    )
    # Fail fast with a precise 402 rather than letting the user watch a job
    # disappear. The worker re-checks — that gate is the one that holds.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "analyses",
        engine=UsageEngine.ansible,
    )
    run_ansible_scan.delay(
        ansible_project_id=str(project.id),
        branch=branch or "",
        trigger="manual",
    )
    return {"status": "queued", "ansible_project_id": str(project_id)}


@router.get(
    "/{project_id}/scans",
    role=Role.org_member,
    response_model=list[AnsibleScanPublic],
)
def list_ansible_scans(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[AnsibleScanPublic]:
    get_target_for_user(ANSIBLE_ENGINE, project_id, session, current_user)
    scans = session.exec(
        select(AnsibleScan)
        .where(AnsibleScan.ansible_project_id == project_id)
        .order_by(col(AnsibleScan.created_at).desc())
        .limit(50)
    ).all()
    return [to_ansible_scan_public(s) for s in scans]


@router.get(
    "/{project_id}/findings",
    role=Role.org_member,
    response_model=list[AnsibleFindingPublic],
)
def list_ansible_findings(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[AnsibleFindingPublic]:
    get_target_for_user(ANSIBLE_ENGINE, project_id, session, current_user)
    query = select(AnsibleFinding).where(
        AnsibleFinding.ansible_project_id == project_id
    )
    if not include_resolved:
        query = query.where(col(AnsibleFinding.resolved_at).is_(None))
    # By file then line, the way the Docker list orders: a reader works through
    # one file at a time, and a play reads top to bottom.
    findings = session.exec(
        query.order_by(col(AnsibleFinding.file_path), col(AnsibleFinding.line_start))
    ).all()
    return [to_ansible_finding_public(f) for f in findings]


@router.get(
    "/{project_id}/files",
    role=Role.org_member,
    response_model=list[AnsibleFilePublic],
)
def list_ansible_files(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None = None,
) -> list[AnsibleFilePublic]:
    """The project's live Ansible source, fetched from GitHub on demand.

    Ansible files aren't persisted (unlike WorkflowFile), so this fetches them
    the same way the scan worker does — which lets the UI show source with the
    findings annotated inline.

    Each file carries the ``kind`` the classifier assigned it, so the frontend
    can label a playbook differently from a variables file without re-deriving
    the classification it has no way to compute.
    """
    project = get_target_for_user(ANSIBLE_ENGINE, project_id, session, current_user)
    repo = get_or_404(
        session, Repository, project.repo_id, detail="Repository not found"
    )
    try:
        fetched = _fetch_ansible_files(repo, project.root_path, ref=ref)
    except Exception as exc:  # network / GitHub failures are transient
        raise HTTPException(
            status_code=502, detail="Failed to fetch Ansible files from GitHub"
        ) from exc
    return [
        AnsibleFilePublic(
            path=f.path,
            raw_content=f.content,
            # The fetcher already classified these to decide they were worth
            # returning; re-running it is cheap and keeps the wire shape honest
            # rather than threading the kind through the transport type.
            kind=classify_ansible_file(f.path, f.content) or "tasks",
        )
        for f in sorted(fetched, key=lambda f: f.path)
    ]
