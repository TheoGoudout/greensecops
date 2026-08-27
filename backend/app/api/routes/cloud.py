import secrets
import uuid

from fastapi import HTTPException
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
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE
from app.models import (
    CloudAccount,
    CloudAccountCreate,
    CloudAccountPublic,
    CloudAccountStatus,
    CloudFinding,
    CloudFindingPublic,
    CloudScan,
    CloudScanPublic,
    ScanTargetUpdate,
    UsageEngine,
)
from app.services import state_machines as sm
from app.services.billing.quota import enforce_quota
from app.workers.tasks.cloud_scan import run_cloud_scan

router = RoleRouter(prefix="/cloud", tags=["cloud"])

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


@router.post(
    "/accounts",
    role=Role.user,
    limit=LIMIT_EXPENSIVE,
    response_model=CloudAccountPublic,
    status_code=201,
)
def create_account(
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


@router.get("/accounts", role=Role.user, response_model=list[CloudAccountPublic])
def list_accounts(
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


@router.patch(
    "/accounts/{account_id}", role=Role.org_admin, response_model=CloudAccountPublic
)
def update_account(
    account_id: uuid.UUID,
    body: ScanTargetUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> CloudAccountPublic:
    account = _get_account_for_user(account_id, session, current_user)
    if body.enabled is not None:
        event = "enable" if body.enabled else "disable"
        if not sm.try_advance(account, sm.CloudAccountMachine, event):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot {event} account in its current state",
            )
    session.add(account)
    session.commit()
    session.refresh(account)
    return to_cloud_account_public(account)


@router.delete("/accounts/{account_id}", role=Role.org_admin, status_code=204)
def delete_account(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    account = _get_account_for_user(account_id, session, current_user)
    # Cascades to its scans/findings (ondelete="CASCADE" on both FKs) — the
    # user is deliberately removing this account, not just disabling it.
    session.delete(account)
    session.commit()


@router.post(
    "/accounts/{account_id}/scans",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_scan(
    account_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str]:
    account = _get_account_for_user(account_id, session, current_user)
    if account.status == CloudAccountStatus.disabled:
        raise HTTPException(status_code=403, detail="Cloud account is disabled")
    # Fail fast with a precise 402; the worker re-checks before assuming the
    # cross-account role, which is the gate that actually holds.
    enforce_quota(
        session, current_user, account.org_id, "analyses", engine=UsageEngine.cloud
    )
    run_cloud_scan.delay(cloud_account_id=str(account.id), trigger="manual")
    return {"status": "queued", "cloud_account_id": str(account_id)}


@router.get(
    "/accounts/{account_id}/scans",
    role=Role.org_member,
    response_model=list[CloudScanPublic],
)
def list_scans(
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


@router.get(
    "/accounts/{account_id}/findings",
    role=Role.org_member,
    response_model=list[CloudFindingPublic],
)
def list_findings(
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


def _get_finding_for_user(
    finding_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> CloudFinding:
    """Load a cloud finding the user may see, or 404.

    Cloud isn't in ``EngineSpec`` (no files, no fixes, no repository — see
    ``services/engines.py``), so this stays a standalone mirror of
    ``engine_routes.get_finding_for_user`` rather than sharing its body.
    """
    finding = get_or_404(
        session, CloudFinding, finding_id, detail="Cloud finding not found"
    )
    _get_account_for_user(finding.cloud_account_id, session, current_user)
    return finding


@router.get(
    "/findings/{cloud_finding_id}",
    role=Role.org_member,
    response_model=CloudFindingPublic,
)
def get_finding(
    cloud_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> CloudFindingPublic:
    finding = _get_finding_for_user(cloud_finding_id, session, current_user)
    return to_cloud_finding_public(finding)


@router.put(
    "/findings/{cloud_finding_id}/ignore",
    role=Role.org_admin,
    response_model=CloudFindingPublic,
)
def ignore_finding(
    cloud_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> CloudFindingPublic:
    finding = _get_finding_for_user(cloud_finding_id, session, current_user)
    if sm.try_advance(finding, sm.FindingMachine, "ignore"):
        session.add(finding)
        session.commit()
        session.refresh(finding)
    return to_cloud_finding_public(finding)


@router.delete(
    "/findings/{cloud_finding_id}/ignore",
    role=Role.org_admin,
    response_model=CloudFindingPublic,
)
def unignore_finding(
    cloud_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> CloudFindingPublic:
    finding = _get_finding_for_user(cloud_finding_id, session, current_user)
    if sm.try_advance(finding, sm.FindingMachine, "unignore"):
        session.add(finding)
        session.commit()
        session.refresh(finding)
    return to_cloud_finding_public(finding)
