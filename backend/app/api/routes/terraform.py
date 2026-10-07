import uuid
from typing import Any

from fastapi import Query

from app.api import engine_routes as shared
from app.api.deps import CurrentUser, GitHubOidcClaims, SessionDep
from app.api.mappers import (
    to_terraform_finding_public,
    to_terraform_fix_public,
    to_terraform_root_public,
    to_terraform_scan_public,
)
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE, LIMIT_INGEST
from app.models import (
    Engine,
    FindingUpdate,
    FixGenerateRequest,
    ScanTargetUpdate,
    TerraformFilePublic,
    TerraformFindingPublic,
    TerraformFixPublic,
    TerraformRootCreate,
    TerraformRootPublic,
    TerraformScanPublic,
)
from app.services.engines import TERRAFORM_ENGINE as SPEC
from app.services.github.fetch import (
    fetch_terraform_files as _fetch_terraform_files,
)
from app.workers.tasks.terraform_analysis import run_terraform_scan
from app.workers.tasks.terraform_fix_delivery import deliver_terraform_fixes
from app.workers.tasks.terraform_fix_generation import run_terraform_fix_generation

# The bodies live in api/engine_routes.py, shared with Docker and Ansible. The
# functions stay one per endpoint here because their names become the OpenAPI
# operation ids, and so the generated clients' method names.
router = RoleRouter(prefix="/terraform", tags=["terraform"])


@router.post(
    "/roots", role=Role.user, response_model=TerraformRootPublic, status_code=201
)
def create_root(
    root_in: TerraformRootCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformRootPublic:
    # A Terraform root must name a folder: the repository root is not one.
    root = shared.create_target(
        SPEC,
        session,
        current_user,
        root_in.repo_id,
        root_in.root_path,
        allow_repo_root=False,
    )
    return to_terraform_root_public(root)


@router.get("/roots", role=Role.user, response_model=list[TerraformRootPublic])
def list_roots(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
) -> list[TerraformRootPublic]:
    """List Terraform roots. Omit ``repo_id`` for the org-wide Infrastructure
    page (every root across every repo the user can access); pass it to
    scope to one repo."""
    return [
        to_terraform_root_public(root, activity)
        for root, activity in shared.list_targets(SPEC, session, current_user, repo_id)
    ]


@router.patch(
    "/roots/{root_id}", role=Role.org_admin, response_model=TerraformRootPublic
)
def update_root(
    root_id: uuid.UUID,
    body: ScanTargetUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformRootPublic:
    return to_terraform_root_public(
        *shared.update_target(SPEC, root_id, body, session, current_user)
    )


@router.delete("/roots/{root_id}", role=Role.org_admin, status_code=204)
def delete_root(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    shared.delete_target(SPEC, root_id, session, current_user)


@router.post(
    "/roots/{root_id}/scans",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_scan(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> dict[str, str]:
    return shared.trigger_target_scan(
        SPEC, run_terraform_scan, root_id, session, current_user, branch
    )


@router.get(
    "/roots/{root_id}/scans",
    role=Role.org_member,
    response_model=list[TerraformScanPublic],
)
def list_scans(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TerraformScanPublic]:
    return [
        to_terraform_scan_public(s)
        for s in shared.list_target_scans(SPEC, root_id, session, current_user, limit)
    ]


@router.get(
    "/roots/{root_id}/findings",
    role=Role.org_member,
    response_model=list[TerraformFindingPublic],
)
def list_findings(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[TerraformFindingPublic]:
    return [
        to_terraform_finding_public(f)
        for f in shared.list_target_findings(
            SPEC, root_id, session, current_user, include_resolved
        )
    ]


@router.get(
    "/findings/{terraform_finding_id}",
    role=Role.org_member,
    response_model=TerraformFindingPublic,
)
def get_finding(
    terraform_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformFindingPublic:
    return to_terraform_finding_public(
        shared.get_finding_for_user(SPEC, terraform_finding_id, session, current_user)
    )


@router.patch(
    "/findings/{terraform_finding_id}",
    role=Role.org_admin,
    response_model=TerraformFindingPublic,
)
def update_finding(
    terraform_finding_id: uuid.UUID,
    body: FindingUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformFindingPublic:
    return to_terraform_finding_public(
        shared.update_finding_for_user(
            SPEC, terraform_finding_id, body, session, current_user
        )
    )


@router.get(
    "/roots/{root_id}/files",
    role=Role.org_member,
    response_model=list[TerraformFilePublic],
)
def list_files(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None = None,
) -> list[TerraformFilePublic]:
    """The root's live ``.tf`` source, fetched from GitHub on demand."""
    return [
        TerraformFilePublic(path=f.path, raw_content=f.content)
        for f in shared.fetch_target_files(
            SPEC, root_id, session, current_user, ref, _fetch_terraform_files
        )
    ]


@router.get("/fixes", role=Role.user, response_model=list[TerraformFixPublic])
def list_repository_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID,
) -> list[TerraformFixPublic]:
    """Every fix across a repository's Terraform roots.

    The pull-requests tab reads it to decide whether "Update PR" may be
    pressed, without a request per card.
    """
    return [
        to_terraform_fix_public(f)
        for f in shared.list_fixes_for_repo(SPEC, session, current_user, repo_id)
    ]


@router.get(
    "/roots/{root_id}/fixes",
    role=Role.org_member,
    response_model=list[TerraformFixPublic],
)
def list_fixes(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[TerraformFixPublic]:
    return [
        to_terraform_fix_public(f)
        for f in shared.list_target_fixes(SPEC, root_id, session, current_user)
    ]


@router.post(
    "/roots/{root_id}/fixes",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def generate_fixes(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: FixGenerateRequest | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate LLM fixes for a root's open findings, one whole-file fix each."""
    return shared.generate_target_fixes(
        SPEC,
        run_terraform_fix_generation,
        root_id,
        session,
        current_user,
        body.finding_ids if body else None,
        force,
    )


@router.post(
    "/roots/{root_id}/deliveries",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def deliver_fixes(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver the root's ready fixes as a single PR (branch per root)."""
    return shared.deliver_target_fixes(
        SPEC, deliver_terraform_fixes, root_id, session, current_user, force
    )


@router.get("/sarif", role=Role.service, limit=LIMIT_INGEST)
def get_sarif(
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, Any]:
    """This repository's open Terraform findings as a SARIF 2.1.0 log.

    For a workflow that runs ``upload-sarif`` on its own runner, so a team can
    read GreenSecOps findings in the security tab and on the PR diff without
    installing the App. Authenticated by the run's GitHub OIDC token: the
    repository comes from the signed claim, so no id is needed and none would
    be honoured.
    """
    return shared.sarif_for_claims(Engine.terraform, session, claims)


@router.post("/scans", role=Role.service, limit=LIMIT_EXPENSIVE, status_code=202)
def trigger_scans_for_code_scanning(
    session: SessionDep,
    claims: GitHubOidcClaims,
    branch: str | None = None,
) -> dict[str, str]:
    """Re-scan every enabled Terraform root in the calling repository.

    Authenticated by the run's GitHub OIDC token, so the repository is the one
    the token was minted for and cannot be chosen by the caller.
    """
    return shared.trigger_code_scanning_scans(
        SPEC, run_terraform_scan, session, claims, branch
    )
