import uuid
from typing import Any

from fastapi import Query

from app.api import engine_routes as shared
from app.api.deps import CurrentUser, GitHubOidcClaims, SessionDep
from app.api.mappers import (
    to_ansible_finding_public,
    to_ansible_fix_public,
    to_ansible_project_public,
    to_ansible_scan_public,
)
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE, LIMIT_INGEST
from app.models import (
    AnsibleFilePublic,
    AnsibleFindingPublic,
    AnsibleFixPublic,
    AnsibleProjectCreate,
    AnsibleProjectPublic,
    AnsibleScanPublic,
    Engine,
    FindingUpdate,
    FixGenerateRequest,
    ScanTargetUpdate,
)
from app.services.ansible.discovery import classify_ansible_file
from app.services.engines import ANSIBLE_ENGINE as SPEC
from app.services.github.fetch import (
    fetch_ansible_files as _fetch_ansible_files,
)
from app.workers.tasks.ansible_analysis import run_ansible_scan
from app.workers.tasks.ansible_fix_delivery import deliver_ansible_fixes
from app.workers.tasks.ansible_fix_generation import run_ansible_fix_generation

# `project_id` rather than `target_id` or `root_id`: `api/router.ORG_RESOLVERS`
# is keyed by path-parameter *name*, and those two are already taken by Docker
# and Terraform. Reusing one would resolve this engine's role checks against
# the wrong table.
#
# The bodies live in api/engine_routes.py, shared with Terraform and Docker. The
# functions stay one per endpoint here because their names become the OpenAPI
# operation ids, and so the generated clients' method names.
router = RoleRouter(prefix="/ansible", tags=["ansible"])


@router.post(
    "/projects", role=Role.user, response_model=AnsibleProjectPublic, status_code=201
)
def create_project(
    project_in: AnsibleProjectCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> AnsibleProjectPublic:
    # The repository root is allowed: an Ansible project frequently *is* the
    # whole repository, with playbooks/ and roles/ at the top level.
    project = shared.create_target(
        SPEC,
        session,
        current_user,
        project_in.repo_id,
        project_in.root_path,
        allow_repo_root=True,
    )
    return to_ansible_project_public(project)


@router.get("/projects", role=Role.user, response_model=list[AnsibleProjectPublic])
def list_projects(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
) -> list[AnsibleProjectPublic]:
    """List Ansible projects. Omit ``repo_id`` for the org-wide Infrastructure
    page (every project across every repo the user can access); pass it to
    scope to one repo."""
    return [
        to_ansible_project_public(project, activity)
        for project, activity in shared.list_targets(
            SPEC, session, current_user, repo_id
        )
    ]


@router.patch(
    "/projects/{project_id}", role=Role.org_admin, response_model=AnsibleProjectPublic
)
def update_project(
    project_id: uuid.UUID,
    body: ScanTargetUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> AnsibleProjectPublic:
    return to_ansible_project_public(
        *shared.update_target(SPEC, project_id, body, session, current_user)
    )


@router.delete("/projects/{project_id}", role=Role.org_admin, status_code=204)
def delete_project(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    shared.delete_target(SPEC, project_id, session, current_user)


@router.post(
    "/projects/{project_id}/scans",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_scan(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> dict[str, str]:
    return shared.trigger_target_scan(
        SPEC, run_ansible_scan, project_id, session, current_user, branch
    )


@router.get(
    "/projects/{project_id}/scans",
    role=Role.org_member,
    response_model=list[AnsibleScanPublic],
)
def list_scans(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AnsibleScanPublic]:
    return [
        to_ansible_scan_public(s)
        for s in shared.list_target_scans(
            SPEC, project_id, session, current_user, limit
        )
    ]


@router.get(
    "/projects/{project_id}/findings",
    role=Role.org_member,
    response_model=list[AnsibleFindingPublic],
)
def list_findings(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[AnsibleFindingPublic]:
    return [
        to_ansible_finding_public(f)
        for f in shared.list_target_findings(
            SPEC, project_id, session, current_user, include_resolved
        )
    ]


@router.get(
    "/findings/{ansible_finding_id}",
    role=Role.org_member,
    response_model=AnsibleFindingPublic,
)
def get_finding(
    ansible_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> AnsibleFindingPublic:
    return to_ansible_finding_public(
        shared.get_finding_for_user(SPEC, ansible_finding_id, session, current_user)
    )


@router.patch(
    "/findings/{ansible_finding_id}",
    role=Role.org_admin,
    response_model=AnsibleFindingPublic,
)
def update_finding(
    ansible_finding_id: uuid.UUID,
    body: FindingUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> AnsibleFindingPublic:
    return to_ansible_finding_public(
        shared.update_finding_for_user(
            SPEC, ansible_finding_id, body, session, current_user
        )
    )


@router.get(
    "/projects/{project_id}/files",
    role=Role.org_member,
    response_model=list[AnsibleFilePublic],
)
def list_files(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None = None,
) -> list[AnsibleFilePublic]:
    """The project's live Ansible source, fetched from GitHub on demand.

    Each file carries the ``kind`` the classifier assigned it, so the frontend
    can label a playbook differently from a variables file without re-deriving
    a classification it has no way to compute.
    """
    return [
        AnsibleFilePublic(
            path=f.path,
            raw_content=f.content,
            kind=classify_ansible_file(f.path, f.content) or "tasks",
        )
        for f in shared.fetch_target_files(
            SPEC, project_id, session, current_user, ref, _fetch_ansible_files
        )
    ]


@router.get("/fixes", role=Role.user, response_model=list[AnsibleFixPublic])
def list_repository_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID,
) -> list[AnsibleFixPublic]:
    """Every fix across a repository's Ansible projects.

    The pull-requests tab reads it to decide whether "Update PR" may be
    pressed, without a request per card.
    """
    return [
        to_ansible_fix_public(f)
        for f in shared.list_fixes_for_repo(SPEC, session, current_user, repo_id)
    ]


@router.get(
    "/projects/{project_id}/fixes",
    role=Role.org_member,
    response_model=list[AnsibleFixPublic],
)
def list_fixes(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[AnsibleFixPublic]:
    return [
        to_ansible_fix_public(f)
        for f in shared.list_target_fixes(SPEC, project_id, session, current_user)
    ]


@router.post(
    "/projects/{project_id}/fixes",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def generate_fixes(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: FixGenerateRequest | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate LLM fixes for a project's open findings, one whole-file fix each."""
    return shared.generate_target_fixes(
        SPEC,
        run_ansible_fix_generation,
        project_id,
        session,
        current_user,
        body.finding_ids if body else None,
        force,
    )


@router.post(
    "/projects/{project_id}/deliveries",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def deliver_fixes(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver the project's ready fixes as a single PR (branch per project)."""
    return shared.deliver_target_fixes(
        SPEC, deliver_ansible_fixes, project_id, session, current_user, force
    )


@router.get("/sarif", role=Role.service, limit=LIMIT_INGEST)
def get_sarif(
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, Any]:
    """This repository's open Ansible findings as a SARIF 2.1.0 log.

    For a workflow that runs ``upload-sarif`` on its own runner, so a team can
    read GreenSecOps findings in the security tab and on the PR diff without
    installing the App. Authenticated by the run's GitHub OIDC token: the
    repository comes from the signed claim, so no id is needed and none would
    be honoured.
    """
    return shared.sarif_for_claims(Engine.ansible, session, claims)


@router.post("/scans", role=Role.service, limit=LIMIT_EXPENSIVE, status_code=202)
def trigger_scans_for_code_scanning(
    session: SessionDep,
    claims: GitHubOidcClaims,
    branch: str | None = None,
) -> dict[str, str]:
    """Re-scan every enabled Ansible project in the calling repository.

    Authenticated by the run's GitHub OIDC token, so the repository is the one
    the token was minted for and cannot be chosen by the caller.
    """
    return shared.trigger_code_scanning_scans(
        SPEC, run_ansible_scan, session, claims, branch
    )
