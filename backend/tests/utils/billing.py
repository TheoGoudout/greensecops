"""Fixtures shared by the billing test modules.

Billing is measured against an org's *billing owner*, so almost every test
needs the same four rows before it can assert anything: a user, an org, an
owner membership linking them, and a repository the usage hangs off. Building
that inline in five test modules is how the assertions get lost in the setup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Session

from app.models import (
    BillingSubscription,
    BillingUsageRecord,
    CloudAccount,
    DockerScan,
    DockerTarget,
    FixStatus,
    LLMProvider,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    ScanStatus,
    SubscriptionStatus,
    TerraformRoot,
    TerraformScan,
    UsageEngine,
    UsageMeter,
    User,
    UserTier,
    WorkflowFile,
    WorkflowFix,
    WorkflowScan,
)


def make_user(
    db: Session, *, tier: UserTier = UserTier.free, is_superuser: bool = False
) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_superuser=is_superuser,
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_org(db: Session) -> Organization:
    org = Organization(name=f"org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def link_owner(
    db: Session, org: Organization, user: User, *, joined_at: datetime | None = None
) -> OrgMember:
    member = OrgMember(
        org_id=org.id,
        user_id=user.id,
        role=OrgRole.owner,
        joined_at=joined_at or datetime.now(timezone.utc),
    )
    db.add(member)
    db.commit()
    return member


def make_repo(db: Session, org: Organization, *, enabled: bool = True) -> Repository:
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"owner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=99999,
        enabled=enabled,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return repo


def make_account(
    db: Session, org: Organization, user: User
) -> tuple[User, Organization, Repository]:
    """The whole owner-linked setup in one call: user, org, and one repo."""
    link_owner(db, org, user)
    return user, org, make_repo(db, org)


def owned_setup(
    db: Session, *, tier: UserTier = UserTier.free
) -> tuple[User, Organization, Repository]:
    """A user who is the billing owner of an org with one enabled repo."""
    user = make_user(db, tier=tier)
    org = make_org(db)
    link_owner(db, org, user)
    return user, org, make_repo(db, org)


def make_workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=f".github/workflows/{uuid.uuid4().hex[:6]}.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="name: CI\non: push\njobs: {}\n",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def make_analysis(
    db: Session,
    repo: Repository,
    wf: WorkflowFile,
    *,
    status: ScanStatus = ScanStatus.completed,
) -> WorkflowScan:
    analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=status,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def make_fix(db: Session, wf: WorkflowFile) -> WorkflowFix:
    fix = WorkflowFix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o",
        status=FixStatus.ready,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def make_terraform_root(db: Session, repo: Repository) -> TerraformRoot:
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:6]}")
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


def make_terraform_scan(
    db: Session, root: TerraformRoot, *, status: ScanStatus = ScanStatus.completed
) -> TerraformScan:
    scan = TerraformScan(terraform_root_id=root.id, status=status)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def make_docker_target(db: Session, repo: Repository) -> DockerTarget:
    target = DockerTarget(repo_id=repo.id, root_path=uuid.uuid4().hex[:6])
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


def make_docker_scan(
    db: Session, target: DockerTarget, *, status: ScanStatus = ScanStatus.completed
) -> DockerScan:
    scan = DockerScan(docker_target_id=target.id, status=status)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def make_cloud_account(db: Session, org: Organization) -> CloudAccount:
    account = CloudAccount(
        org_id=org.id,
        display_name=f"aws-{uuid.uuid4().hex[:6]}",
        external_id=uuid.uuid4().hex,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def record_usage(
    db: Session,
    user: User,
    org: Organization,
    *,
    meter: UsageMeter = UsageMeter.analyses,
    engine: UsageEngine = UsageEngine.workflow,
    quantity: int = 1,
    occurred_at: datetime | None = None,
    repo: Repository | None = None,
) -> BillingUsageRecord:
    """Append a ledger entry directly, for tests about reading the ledger."""
    record = BillingUsageRecord(
        user_id=user.id,
        org_id=org.id,
        repo_id=repo.id if repo else None,
        meter=meter,
        engine=engine,
        quantity=quantity,
        source_type="test",
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_subscription(
    db: Session,
    user: User,
    *,
    tier: UserTier = UserTier.free,
    status: SubscriptionStatus = SubscriptionStatus.active,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> BillingSubscription:
    sub = BillingSubscription(
        user_id=user.id,
        tier=tier,
        status=status,
        period_start=period_start,
        period_end=period_end,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub
