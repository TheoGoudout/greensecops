import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    GitHubOidcClaims,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.engine_routes import (
    enabled_targets_for_claims,
    get_finding_for_user,
    get_target_for_user,
    ignore_finding_for_user,
    list_fixes_for_repo,
    prepare_pending_fix,
    require_target_idle,
    sarif_for_claims,
    target_activities,
    target_activity,
    unignore_finding_for_user,
)
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
    Repository,
    ScanTargetUpdate,
    TargetAction,
    TargetActivity,
    TerraformFilePublic,
    TerraformFinding,
    TerraformFindingPublic,
    TerraformFix,
    TerraformFixPublic,
    TerraformRoot,
    TerraformRootCreate,
    TerraformRootPublic,
    TerraformScan,
    TerraformScanPublic,
    UsageEngine,
)
from app.services.billing.quota import enforce_quota
from app.services.delivery_pr import tf_fix_branch
from app.services.engines import TERRAFORM_ENGINE
from app.services.github.fetch import (
    fetch_terraform_files as _fetch_terraform_files,
)
from app.workers.tasks.fix_generation import resolve_llm_provider
from app.workers.tasks.terraform_analysis import run_terraform_scan
from app.workers.tasks.terraform_fix_delivery import deliver_terraform_fixes
from app.workers.tasks.terraform_fix_generation import run_terraform_fix_generation

router = RoleRouter(prefix="/terraform", tags=["terraform"])


class TerraformFixGenerateRequest(BaseModel):
    # Optional subset of finding ids to fix; omit to fix every open finding in
    # the root. Findings are grouped by file into one whole-file fix each.
    finding_ids: list[uuid.UUID] | None = None


@router.post(
    "/roots", role=Role.user, response_model=TerraformRootPublic, status_code=201
)
def create_root(
    root_in: TerraformRootCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformRootPublic:
    repo = authorize_repo(session, current_user, root_in.repo_id)
    # Normalize so "infra", "/infra", "infra/" and "/infra/" all address the
    # same root — otherwise the uniqueness constraint (repo_id, root_path)
    # would let a user create near-duplicate roots that mean the same thing.
    normalized_path = root_in.root_path.strip("/")
    if not normalized_path:
        raise HTTPException(status_code=422, detail="root_path must not be empty")

    existing = session.exec(
        select(TerraformRoot)
        .where(TerraformRoot.repo_id == repo.id)
        .where(TerraformRoot.root_path == normalized_path)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="This root path is already configured"
        )

    root = TerraformRoot(repo_id=repo.id, root_path=normalized_path)
    session.add(root)
    session.commit()
    session.refresh(root)
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
    if repo_id:
        authorize_repo(session, current_user, repo_id)
        query = select(TerraformRoot).where(TerraformRoot.repo_id == repo_id)
    else:
        query = select(TerraformRoot)
        if not current_user.is_superuser:
            query = query.join(
                Repository,
                TerraformRoot.repo_id == Repository.id,  # type: ignore[arg-type]
            ).where(Repository.org_id.in_(user_org_ids(session, current_user)))  # type: ignore[attr-defined]
    roots = session.exec(query.order_by(col(TerraformRoot.root_path))).all()
    # One batched read for the whole page: every row publishes what it is busy
    # with, so the list can grey its own actions without fetching each root's
    # fixes to work it out.
    activities = target_activities(TERRAFORM_ENGINE, session, [r.id for r in roots])
    return [
        to_terraform_root_public(r, activities.get(r.id, TargetActivity.idle))
        for r in roots
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
    root = get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    if body.enabled is not None:
        root.enabled = body.enabled
    session.add(root)
    session.commit()
    session.refresh(root)
    return to_terraform_root_public(
        root, target_activity(TERRAFORM_ENGINE, session, root.id)
    )


@router.delete("/roots/{root_id}", role=Role.org_admin, status_code=204)
def delete_root(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    root = get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    # Cascades to its scans/findings (ondelete="CASCADE" on both FKs) — the
    # user is deliberately removing this root, not just disabling it. Which is
    # also why it needs the guard the disable switch does not: a worker still
    # holding one of those rows would be writing into a deleted tree.
    require_target_idle(TERRAFORM_ENGINE, session, root_id, TargetAction.remove)
    session.delete(root)
    session.commit()


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
    root = get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    if not root.enabled:
        raise HTTPException(status_code=403, detail="Terraform root is disabled")
    require_target_idle(TERRAFORM_ENGINE, session, root_id, TargetAction.scan)
    repo = get_or_404(session, Repository, root.repo_id, detail="Repository not found")
    # Fail fast with a precise 402 rather than letting the user watch a job
    # disappear. The worker re-checks — that gate is the one that holds.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "analyses",
        engine=UsageEngine.terraform,
    )
    run_terraform_scan.delay(
        terraform_root_id=str(root.id),
        branch=branch or "",
        trigger="manual",
    )
    return {"status": "queued", "terraform_root_id": str(root_id)}


@router.get(
    "/roots/{root_id}/scans",
    role=Role.org_member,
    response_model=list[TerraformScanPublic],
)
def list_scans(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[TerraformScanPublic]:
    get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    scans = session.exec(
        select(TerraformScan)
        .where(TerraformScan.terraform_root_id == root_id)
        .order_by(col(TerraformScan.created_at).desc())
        .limit(50)
    ).all()
    return [to_terraform_scan_public(s) for s in scans]


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
    get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    query = select(TerraformFinding).where(
        TerraformFinding.terraform_root_id == root_id
    )
    if not include_resolved:
        query = query.where(col(TerraformFinding.resolved_at).is_(None))
    findings = session.exec(
        query.order_by(col(TerraformFinding.created_at).desc())
    ).all()
    return [to_terraform_finding_public(f) for f in findings]


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
    finding = get_finding_for_user(
        TERRAFORM_ENGINE, terraform_finding_id, session, current_user
    )
    return to_terraform_finding_public(finding)


@router.put(
    "/findings/{terraform_finding_id}/ignore",
    role=Role.org_admin,
    response_model=TerraformFindingPublic,
)
def ignore_finding(
    terraform_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformFindingPublic:
    finding = ignore_finding_for_user(
        TERRAFORM_ENGINE, terraform_finding_id, session, current_user
    )
    return to_terraform_finding_public(finding)


@router.delete(
    "/findings/{terraform_finding_id}/ignore",
    role=Role.org_admin,
    response_model=TerraformFindingPublic,
)
def unignore_finding(
    terraform_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> TerraformFindingPublic:
    finding = unignore_finding_for_user(
        TERRAFORM_ENGINE, terraform_finding_id, session, current_user
    )
    return to_terraform_finding_public(finding)


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
    """The root's live ``.tf`` source, fetched from GitHub on demand.

    Terraform files aren't persisted (unlike WorkflowFile), so this fetches
    them the same way the scan worker does — lets the UI show source with the
    findings annotated inline.
    """
    root = get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    repo = get_or_404(session, Repository, root.repo_id, detail="Repository not found")
    try:
        fetched = _fetch_terraform_files(repo, root.root_path, ref=ref)
    except Exception as exc:  # network / GitHub failures are transient
        raise HTTPException(
            status_code=502, detail="Failed to fetch Terraform files from GitHub"
        ) from exc
    return [
        TerraformFilePublic(path=f.path, raw_content=f.content)
        for f in sorted(fetched, key=lambda f: f.path)
    ]


@router.get("/fixes", role=Role.user, response_model=list[TerraformFixPublic])
def list_repository_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID,
) -> list[TerraformFixPublic]:
    """Every fix across a repository's Terraform roots.

    The cross-target read beside the per-target one, matching
    ``GET /workflow/fixes``. The pull-requests tab reads it to decide whether
    "Update PR" may be pressed: a delivery already in flight, or a fix still
    being generated, refuses one — and asking per target would be a request per
    card on a page that already lists them all.
    """
    return [
        to_terraform_fix_public(f)
        for f in list_fixes_for_repo(TERRAFORM_ENGINE, session, current_user, repo_id)
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
    get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    fixes = session.exec(
        select(TerraformFix)
        .where(TerraformFix.terraform_root_id == root_id)
        .order_by(col(TerraformFix.created_at).desc())
    ).all()
    return [to_terraform_fix_public(f) for f in fixes]


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
    body: TerraformFixGenerateRequest | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate LLM fixes for a root's open findings, one whole-file fix each."""
    root = get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    require_target_idle(TERRAFORM_ENGINE, session, root_id, TargetAction.generate)
    repo = get_or_404(session, Repository, root.repo_id, detail="Repository not found")

    query = (
        select(TerraformFinding)
        .where(TerraformFinding.terraform_root_id == root_id)
        .where(col(TerraformFinding.resolved_at).is_(None))
        .where(col(TerraformFinding.ignored_at).is_(None))
    )
    if body and body.finding_ids:
        query = query.where(col(TerraformFinding.id).in_(body.finding_ids))
    findings = list(session.exec(query).all())
    if not findings:
        return {"status": "no_findings", "queued": 0}

    by_file: dict[str, list[TerraformFinding]] = defaultdict(list)
    for finding in findings:
        by_file[finding.file_path].append(finding)

    # One whole-file LLM rewrite per file, so the request costs as many fix
    # generations as there are files. This route had no quota check at all
    # before: Terraform fixes were the same LLM spend as workflow fixes and
    # were metered against nobody.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "fixes",
        requested=len(by_file),
        engine=UsageEngine.terraform,
    )

    provider_str, model_str = resolve_llm_provider(repo)
    queued = 0
    for file_path, group in by_file.items():
        fix = prepare_pending_fix(
            TERRAFORM_ENGINE,
            session,
            root_id,
            file_path,
            provider_str,
            model_str,
            force,
            repo=repo,
        )
        if fix is None:
            continue
        session.flush()
        for finding in group:
            finding.fix_id = fix.id
            session.add(finding)
        session.commit()
        run_terraform_fix_generation.delay(finding_ids=[str(f.id) for f in group])
        queued += 1

    return {"status": "queued", "queued": queued}


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
    root = get_target_for_user(TERRAFORM_ENGINE, root_id, session, current_user)
    require_target_idle(TERRAFORM_ENGINE, session, root_id, TargetAction.deliver)
    deliver_terraform_fixes.delay(terraform_root_id=str(root.id), force=force)
    return {
        "status": "queued",
        "terraform_root_id": str(root_id),
        "pr_branch": tf_fix_branch(root.id),
    }


@router.get("/sarif", role=Role.service, limit=LIMIT_INGEST)
def get_sarif(
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, Any]:
    """This repository's open Terraform findings as a SARIF 2.1.0 log.

    For a workflow that runs ``upload-sarif`` on its own runner, so a team can
    read GreenSecOps findings in the security tab and on the PR diff alongside
    whatever else they scan with — the same findings, in the format GitHub
    reads, without installing the App.

    Authenticated by the run's GitHub OIDC token: the repository comes from the
    signed claim, so no id is needed and none would be honoured.
    """
    return sarif_for_claims(Engine.terraform, session, claims)


@router.post("/scans", role=Role.service, limit=LIMIT_EXPENSIVE, status_code=202)
def trigger_scans_for_code_scanning(
    session: SessionDep,
    claims: GitHubOidcClaims,
    branch: str | None = None,
) -> dict[str, str]:
    """Re-scan every enabled Terraform target in the calling repository.

    The first half of the Code Scanning flow: a workflow asks for fresh
    analysis and then fetches ``GET /terraform/sarif``. Without it a team using
    the workflows rather than the App would only ever publish whatever the last
    scan found — nothing at all, on a repository the App has never touched.

    Authenticated by the run's GitHub OIDC token, so the repository is the one
    the token was minted for and cannot be chosen by the caller. Quota is
    charged to the org's billing owner, exactly as a dashboard-triggered scan
    is; there is no user to attribute it to.
    """
    repo, targets = enabled_targets_for_claims(TERRAFORM_ENGINE, session, claims)
    if not targets:
        return {"status": "no_targets", "queued": "0"}
    enforce_quota(
        session,
        None,
        repo.org_id,
        "analyses",
        requested=len(targets),
        engine=UsageEngine.terraform,
    )
    for target in targets:
        run_terraform_scan.delay(
            terraform_root_id=str(target.id),
            branch=branch or "",
            trigger="code_scanning",
        )
    return {"status": "queued", "queued": str(len(targets))}
