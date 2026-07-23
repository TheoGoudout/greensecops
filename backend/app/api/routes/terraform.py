import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_or_404,
)
from app.api.mappers import (
    to_terraform_finding_public,
    to_terraform_root_public,
    to_terraform_scan_public,
)
from app.models import (
    TerraformFinding,
    TerraformFindingPublic,
    TerraformRoot,
    TerraformRootCreate,
    TerraformRootPublic,
    TerraformScan,
    TerraformScanPublic,
)
from app.workers.tasks.terraform_analysis import run_terraform_scan

router = APIRouter(prefix="/terraform-roots", tags=["terraform"])


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
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[TerraformRootPublic]:
    authorize_repo(session, current_user, repo_id)
    roots = session.exec(
        select(TerraformRoot).where(TerraformRoot.repo_id == repo_id)
    ).all()
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
