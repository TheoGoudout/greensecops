import secrets
import uuid

from fastapi import APIRouter, HTTPException
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_org,
    get_or_404,
    user_org_ids,
)
from app.api.mappers import (
    to_cloud_account_public,
    to_cloud_finding_public,
    to_cloud_scan_public,
)
from app.models import (
    CloudAccount,
    CloudAccountCreate,
    CloudAccountPublic,
    CloudAccountStatus,
    CloudFinding,
    CloudFindingPublic,
    CloudScan,
    CloudScanPublic,
)
from app.services import state_machines as sm
from app.workers.tasks.cloud_scan import run_cloud_scan

router = APIRouter(prefix="/cloud-accounts", tags=["cloud"])

# Length of the generated external_id — long enough to be infeasible to
# guess/replay against another customer's role trust policy.
_EXTERNAL_ID_LENGTH = 32


def _get_account_for_user(
    account_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> CloudAccount:
    account = get_or_404(
        session, CloudAccount, account_id, detail="Cloud account not found"
    )
    authorize_org(
        session, current_user, account.org_id, detail="Cloud account not found"
    )
    return account


@router.post("/", response_model=CloudAccountPublic, status_code=201)
def create_cloud_account(
    account_in: CloudAccountCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> CloudAccountPublic:
    authorize_org(session, current_user, account_in.org_id)
    account = CloudAccount(
        org_id=account_in.org_id,
        display_name=account_in.display_name,
        role_arn=account_in.role_arn,
        external_id=secrets.token_hex(_EXTERNAL_ID_LENGTH),
        regions=",".join(account_in.regions),
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return to_cloud_account_public(account)


@router.get("/", response_model=list[CloudAccountPublic])
def list_cloud_accounts(
    session: SessionDep,
    current_user: CurrentUser,
    org_id: uuid.UUID | None = None,
) -> list[CloudAccountPublic]:
    """List cloud accounts. Omit ``org_id`` for every org the user can access;
    pass it to scope to one org."""
    if org_id:
        authorize_org(session, current_user, org_id)
        query = select(CloudAccount).where(CloudAccount.org_id == org_id)
    else:
        query = select(CloudAccount)
        if not current_user.is_superuser:
            query = query.where(
                col(CloudAccount.org_id).in_(user_org_ids(session, current_user))
            )
    accounts = session.exec(query.order_by(col(CloudAccount.display_name))).all()
    return [to_cloud_account_public(a) for a in accounts]


@router.patch("/{account_id}/toggle")
def toggle_cloud_account(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    enabled: bool,
) -> dict[str, str | bool]:
    account = _get_account_for_user(account_id, session, current_user)
    event = "enable" if enabled else "disable"
    if not sm.try_advance(account, sm.CloudAccountMachine, event):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {event} account in its current state",
        )
    session.add(account)
    session.commit()
    return {"cloud_account_id": str(account_id), "enabled": enabled}


@router.delete("/{account_id}", status_code=204)
def delete_cloud_account(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    account = _get_account_for_user(account_id, session, current_user)
    # Cascades to its scans/findings (ondelete="CASCADE" on both FKs) — the
    # user is deliberately removing this account, not just disabling it.
    session.delete(account)
    session.commit()


@router.post("/{account_id}/scan", status_code=202)
def trigger_cloud_scan(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str]:
    account = _get_account_for_user(account_id, session, current_user)
    if account.status == CloudAccountStatus.disabled:
        raise HTTPException(status_code=403, detail="Cloud account is disabled")
    run_cloud_scan.delay(cloud_account_id=str(account.id), trigger="manual")
    return {"status": "queued", "cloud_account_id": str(account_id)}


@router.get("/{account_id}/scans", response_model=list[CloudScanPublic])
def list_cloud_scans(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[CloudScanPublic]:
    _get_account_for_user(account_id, session, current_user)
    scans = session.exec(
        select(CloudScan)
        .where(CloudScan.cloud_account_id == account_id)
        .order_by(col(CloudScan.created_at).desc())
        .limit(50)
    ).all()
    return [to_cloud_scan_public(s) for s in scans]


@router.get("/{account_id}/findings", response_model=list[CloudFindingPublic])
def list_cloud_findings(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[CloudFindingPublic]:
    _get_account_for_user(account_id, session, current_user)
    query = select(CloudFinding).where(CloudFinding.cloud_account_id == account_id)
    if not include_resolved:
        query = query.where(col(CloudFinding.resolved_at).is_(None))
    findings = session.exec(query.order_by(col(CloudFinding.created_at).desc())).all()
    return [to_cloud_finding_public(f) for f in findings]
