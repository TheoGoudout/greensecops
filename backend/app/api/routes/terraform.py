import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.mappers import (
    to_terraform_finding_public,
    to_terraform_fix_public,
    to_terraform_root_public,
    to_terraform_scan_public,
)
from app.models import (
    LLMProvider,
    Repository,
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
)
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.delivery_pr import tf_fix_branch
from app.workers.tasks.fix_generation import resolve_llm_provider
from app.workers.tasks.terraform_analysis import (
    _fetch_terraform_files,
    run_terraform_scan,
)
from app.workers.tasks.terraform_fix_delivery import deliver_terraform_fixes
from app.workers.tasks.terraform_fix_generation import run_terraform_fix_generation

router = APIRouter(prefix="/terraform-roots", tags=["terraform"])

# Fix statuses a worker is actively processing — a fix here must not be reset
# out from under the worker (mirrors fixes.IN_FLIGHT_STATUSES).
_IN_FLIGHT_FIX_STATUSES = (
    FixStatus.pending,
    FixStatus.generating,
    FixStatus.delivering,
)


class TerraformFixGenerateRequest(BaseModel):
    # Optional subset of finding ids to fix; omit to fix every open finding in
    # the root. Findings are grouped by file into one whole-file fix each.
    finding_ids: list[uuid.UUID] | None = None


def _get_root_for_user(
    root_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> TerraformRoot:
    root = get_or_404(
        session, TerraformRoot, root_id, detail="Terraform root not found"
    )
    authorize_repo(
        session, current_user, root.repo_id, detail="Terraform root not found"
    )
    return root


@router.post("/", response_model=TerraformRootPublic, status_code=201)
def create_terraform_root(
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


@router.get("/", response_model=list[TerraformRootPublic])
def list_terraform_roots(
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
    return [to_terraform_root_public(r) for r in roots]


@router.patch("/{root_id}/toggle")
def toggle_terraform_root(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    enabled: bool,
) -> dict[str, str | bool]:
    root = _get_root_for_user(root_id, session, current_user)
    root.enabled = enabled
    session.add(root)
    session.commit()
    return {"terraform_root_id": str(root_id), "enabled": enabled}


@router.delete("/{root_id}", status_code=204)
def delete_terraform_root(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    root = _get_root_for_user(root_id, session, current_user)
    # Cascades to its scans/findings (ondelete="CASCADE" on both FKs) — the
    # user is deliberately removing this root, not just disabling it.
    session.delete(root)
    session.commit()


@router.post("/{root_id}/scan", status_code=202)
def trigger_terraform_scan(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> dict[str, str]:
    root = _get_root_for_user(root_id, session, current_user)
    if not root.enabled:
        raise HTTPException(status_code=403, detail="Terraform root is disabled")
    run_terraform_scan.delay(
        terraform_root_id=str(root.id),
        branch=branch or "",
        trigger="manual",
    )
    return {"status": "queued", "terraform_root_id": str(root_id)}


@router.get("/{root_id}/scans", response_model=list[TerraformScanPublic])
def list_terraform_scans(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[TerraformScanPublic]:
    _get_root_for_user(root_id, session, current_user)
    scans = session.exec(
        select(TerraformScan)
        .where(TerraformScan.terraform_root_id == root_id)
        .order_by(col(TerraformScan.created_at).desc())
        .limit(50)
    ).all()
    return [to_terraform_scan_public(s) for s in scans]


@router.get("/{root_id}/findings", response_model=list[TerraformFindingPublic])
def list_terraform_findings(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[TerraformFindingPublic]:
    _get_root_for_user(root_id, session, current_user)
    query = select(TerraformFinding).where(
        TerraformFinding.terraform_root_id == root_id
    )
    if not include_resolved:
        query = query.where(col(TerraformFinding.resolved_at).is_(None))
    findings = session.exec(
        query.order_by(col(TerraformFinding.created_at).desc())
    ).all()
    return [to_terraform_finding_public(f) for f in findings]


@router.get("/{root_id}/files", response_model=list[TerraformFilePublic])
def list_terraform_files(
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
    root = _get_root_for_user(root_id, session, current_user)
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


@router.get("/{root_id}/fixes", response_model=list[TerraformFixPublic])
def list_terraform_fixes(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[TerraformFixPublic]:
    _get_root_for_user(root_id, session, current_user)
    fixes = session.exec(
        select(TerraformFix)
        .where(TerraformFix.terraform_root_id == root_id)
        .order_by(col(TerraformFix.created_at).desc())
    ).all()
    return [to_terraform_fix_public(f) for f in fixes]


@router.post("/{root_id}/fixes", status_code=202)
def trigger_terraform_fix_generation(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: TerraformFixGenerateRequest | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate LLM fixes for a root's open findings, one whole-file fix each."""
    root = _get_root_for_user(root_id, session, current_user)
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

    provider_str, model_str = resolve_llm_provider(repo)
    queued = 0
    for file_path, group in by_file.items():
        fix = _prepare_pending_fix(
            session, root_id, file_path, provider_str, model_str, force
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


def _prepare_pending_fix(
    session: SessionDep,
    root_id: uuid.UUID,
    file_path: str,
    provider_str: str,
    model_str: str,
    force: bool,
) -> TerraformFix | None:
    """Create or reuse the single (root, file) fix row, leaving it ``pending``.

    Returns ``None`` when a fix is already in flight, or already resolved and
    not being forced — nothing to (re)queue.
    """
    existing = session.exec(
        select(TerraformFix)
        .where(TerraformFix.terraform_root_id == root_id)
        .where(TerraformFix.file_path == file_path)
    ).first()
    if existing is not None:
        if existing.status in _IN_FLIGHT_FIX_STATUSES:
            return None
        if not force and existing.status != FixStatus.failed:
            return None
        # Reuse the row (the unique constraint allows only one per file): hard
        # reset to pending for a fresh generation.
        sm.force_to(existing, sm.FixMachine, FixStatus.pending)
        existing.full_content = None
        existing.error_message = None
        existing.pr_id = None
        existing.llm_provider = LLMProvider(provider_str)
        existing.llm_model = model_str
        session.add(existing)
        return existing

    fix = TerraformFix(
        terraform_root_id=root_id,
        file_path=file_path,
        llm_provider=LLMProvider(provider_str),
        llm_model=model_str,
        status=FixStatus.pending,
    )
    session.add(fix)
    return fix


@router.post("/{root_id}/deliver", status_code=202)
def trigger_terraform_delivery(
    root_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver the root's ready fixes as a single PR (branch per root)."""
    root = _get_root_for_user(root_id, session, current_user)
    deliver_terraform_fixes.delay(terraform_root_id=str(root.id), force=force)
    return {
        "status": "queued",
        "terraform_root_id": str(root_id),
        "pr_branch": tf_fix_branch(root.id),
    }
