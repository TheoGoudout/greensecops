"""Tests for the /api/v1/overview/ cross-engine dashboard endpoint.

Every counting test here runs as a **normal user in a freshly created org**,
never as the superuser. The ``db`` fixture is session-scoped and shared across
the whole suite (tests/conftest.py:15-23), so a superuser call to an org-wide
aggregate sees every other test module's rows and no exact count is assertable.
Scoping to a private org is what makes the numbers deterministic.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    CloudAccount,
    CloudAccountStatus,
    CloudFinding,
    CloudProvider,
    CloudScan,
    DockerFinding,
    DockerFix,
    DockerScan,
    DockerTarget,
    FindingStatus,
    FixStatus,
    Issue,
    LLMProvider,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformRoot,
    TerraformScan,
    User,
    UserTier,
    WorkflowFile,
)
from tests.utils.user import create_random_user, user_authentication_headers
from tests.utils.utils import random_lower_string

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"ovw-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def member(db: Session, client: TestClient, org: Organization) -> dict[str, str]:
    """A user who belongs to ``org`` and nothing else, plus its auth headers."""
    password = random_lower_string()
    user = create_random_user(db)
    user.hashed_password = get_password_hash(password)
    db.add(user)
    db.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"ovwowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=98765,
        default_branch="main",
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def docker_target(db: Session, repo: Repository) -> DockerTarget:
    target = DockerTarget(repo_id=repo.id, root_path=f"svc/{uuid.uuid4().hex[:8]}")
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


@pytest.fixture()
def docker_rule(db: Session) -> Rule:
    rule = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.container_docker)
    ).first()
    assert rule is not None
    return rule


@pytest.fixture()
def workflow_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.ci_workflow)).first()
    assert rule is not None
    return rule


# ─── Builders ────────────────────────────────────────────────────────────────


def _docker_scan(
    db: Session,
    target: DockerTarget,
    *,
    status: ScanStatus = ScanStatus.completed,
    score: float | None = 72.0,
    grade: str | None = "B",
    created_at: datetime | None = None,
) -> DockerScan:
    scan = DockerScan(
        docker_target_id=target.id,
        status=status,
        triggered_by=AnalysisTrigger.manual,
        score=score,
        grade=grade,
        file_count=1,
    )
    if created_at is not None:
        scan.created_at = created_at
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


def _docker_finding(
    db: Session,
    target: DockerTarget,
    scan: DockerScan,
    rule: Rule,
    *,
    severity: str | None = None,
    category: str | None = None,
    resolved_at: datetime | None = None,
    ignored_at: datetime | None = None,
    fix_id: uuid.UUID | None = None,
) -> DockerFinding:
    finding = DockerFinding(
        scan_id=scan.id,
        docker_target_id=target.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=severity or rule.severity,
        category=category or rule.category,
        status=FindingStatus.resolved if resolved_at else FindingStatus.open,
        message="finding",
        resolved_at=resolved_at,
        ignored_at=ignored_at,
        fix_id=fix_id,
        file_path="Dockerfile",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


def _docker_fix(db: Session, target: DockerTarget, status: FixStatus) -> DockerFix:
    fix = DockerFix(
        docker_target_id=target.id,
        file_path=f"Dockerfile.{uuid.uuid4().hex[:6]}",
        llm_provider=LLMProvider.anthropic,
        llm_model="claude",
        status=status,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    return fix


def _engine(body: dict, key: str) -> dict:
    (found,) = [e for e in body["engines"] if e["engine"] == key]
    return found


def _fetch(client: TestClient, headers: dict[str, str], **params: object) -> dict:
    response = client.get(
        f"{settings.API_V1_STR}/overview/", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


# ─── Shape and auth ──────────────────────────────────────────────────────────


def test_overview_requires_authentication(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/overview/")
    assert response.status_code == 401


def test_overview_reports_every_engine_under_its_section(
    client: TestClient, member: dict[str, str]
) -> None:
    body = _fetch(client, member)

    sections = {e["engine"]: e["section"] for e in body["engines"]}
    assert sections == {
        "workflow": "ci",
        "docker": "docker",
        # Terraform and cloud posture share the Infrastructure section, the way
        # the Infrastructure page already shows them as sibling tabs.
        "terraform": "infra",
        "cloud": "infra",
    }


def test_an_empty_org_gets_zeroed_engines_not_an_error(
    client: TestClient, member: dict[str, str]
) -> None:
    body = _fetch(client, member)

    for engine in body["engines"]:
        assert engine["coverage"]["total"] == 0
        assert engine["findings"]["open"] == 0
        assert engine["score"]["avg_score"] is None
    assert body["totals"]["avg_score"] is None
    assert body["totals"]["engines_with_data"] == 0


# ─── Tenant isolation ────────────────────────────────────────────────────────


def test_another_orgs_data_is_invisible(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_rule: Rule,
) -> None:
    other_org = Organization(name=f"ovw-other-{uuid.uuid4().hex[:8]}")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)
    other_repo = Repository(
        org_id=other_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"other/repo-{uuid.uuid4().hex[:8]}",
        installation_id=1,
    )
    db.add(other_repo)
    db.commit()
    db.refresh(other_repo)
    other_target = DockerTarget(repo_id=other_repo.id, root_path="")
    db.add(other_target)
    db.commit()
    db.refresh(other_target)
    scan = _docker_scan(db, other_target)
    _docker_finding(db, other_target, scan, docker_rule)

    body = _fetch(client, member)

    docker = _engine(body, "docker")
    assert docker["coverage"]["total"] == 0
    assert docker["findings"]["open"] == 0


def test_org_id_scopes_to_one_org_and_rejects_non_members(
    client: TestClient, db: Session, member: dict[str, str], org: Organization
) -> None:
    body = _fetch(client, member, org_id=str(org.id))
    assert body["totals"]["targets"] == 0

    stranger = Organization(name=f"ovw-stranger-{uuid.uuid4().hex[:8]}")
    db.add(stranger)
    db.commit()
    db.refresh(stranger)

    response = client.get(
        f"{settings.API_V1_STR}/overview/",
        headers=member,
        params={"org_id": str(stranger.id)},
    )
    assert response.status_code == 404


# ─── Coverage ────────────────────────────────────────────────────────────────


def test_coverage_separates_scanned_from_never_scanned(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    repo: Repository,
    docker_target: DockerTarget,
) -> None:
    _docker_scan(db, docker_target)
    unscanned = DockerTarget(repo_id=repo.id, root_path="never-scanned")
    db.add(unscanned)
    db.commit()

    docker = _engine(_fetch(client, member), "docker")

    assert docker["coverage"]["total"] == 2
    assert docker["coverage"]["scanned"] == 1
    assert docker["coverage"]["never_scanned"] == 1


def test_a_disabled_target_still_counts_toward_total(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
) -> None:
    docker_target.enabled = False
    db.add(docker_target)
    db.commit()

    docker = _engine(_fetch(client, member), "docker")

    assert docker["coverage"]["total"] == 1
    assert docker["coverage"]["enabled"] == 0


def test_a_failed_latest_scan_does_not_erase_the_last_good_grade(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
) -> None:
    """The grade comes from the latest *completed* scan; the failure is
    reported separately so the dashboard can show both facts at once."""
    now = datetime.now(timezone.utc)
    _docker_scan(
        db, docker_target, grade="B", score=72.0, created_at=now - timedelta(hours=2)
    )
    _docker_scan(
        db,
        docker_target,
        status=ScanStatus.failed,
        score=None,
        grade=None,
        created_at=now,
    )

    docker = _engine(_fetch(client, member), "docker")

    assert docker["score"]["grade"] == "B"
    assert docker["score"]["avg_score"] == 72.0
    assert docker["coverage"]["latest_scan_failed"] == 1
    assert docker["coverage"]["scanned"] == 1


def test_grade_distribution_covers_the_whole_ladder(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
) -> None:
    _docker_scan(db, docker_target, grade="B", score=72.0)

    docker = _engine(_fetch(client, member), "docker")

    by_grade = docker["score"]["by_grade"]
    assert [row["grade"] for row in by_grade] == [
        "A+++",
        "A++",
        "A+",
        "A",
        "B",
        "C",
        "D",
        "F",
    ]
    assert {row["grade"]: row["count"] for row in by_grade}["B"] == 1
    assert sum(row["count"] for row in by_grade) == docker["score"]["scored_targets"]


# ─── Findings ────────────────────────────────────────────────────────────────


def test_findings_split_by_severity_and_category_both_sum_to_open(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    scan = _docker_scan(db, docker_target)
    for _ in range(3):
        _docker_finding(db, docker_target, scan, docker_rule)

    docker = _engine(_fetch(client, member), "docker")

    assert docker["findings"]["open"] == 3
    assert sum(row["open"] for row in docker["findings"]["by_severity"]) == 3
    assert sum(row["open"] for row in docker["findings"]["by_category"]) == 3
    # Every severity and category is emitted, zeros included, so the frontend
    # can render fixed segments without gap logic.
    assert len(docker["findings"]["by_severity"]) == 5
    assert len(docker["findings"]["by_category"]) == 5


def test_resolved_and_ignored_findings_leave_the_open_count(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    scan = _docker_scan(db, docker_target)
    now = datetime.now(timezone.utc)
    _docker_finding(db, docker_target, scan, docker_rule)
    _docker_finding(db, docker_target, scan, docker_rule, resolved_at=now)
    _docker_finding(db, docker_target, scan, docker_rule, ignored_at=now)

    docker = _engine(_fetch(client, member), "docker")

    assert docker["findings"]["open"] == 1
    assert docker["findings"]["resolved"] == 1
    # The ignored one is counted in neither bucket.
    assert docker["findings"]["open"] + docker["findings"]["resolved"] == 2


def test_findings_stranded_on_a_superseded_scan_are_not_counted(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    now = datetime.now(timezone.utc)
    old_scan = _docker_scan(db, docker_target, created_at=now - timedelta(hours=1))
    _docker_scan(db, docker_target, created_at=now)
    _docker_finding(db, docker_target, old_scan, docker_rule)

    docker = _engine(_fetch(client, member), "docker")

    assert docker["findings"]["open"] == 0


def test_engines_do_not_leak_into_each_other(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    repo: Repository,
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    scan = _docker_scan(db, docker_target)
    _docker_finding(db, docker_target, scan, docker_rule)

    root = TerraformRoot(repo_id=repo.id, root_path="infra")
    db.add(root)
    db.commit()
    db.refresh(root)
    tf_rule = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.iac_terraform)
    ).first()
    assert tf_rule is not None
    tf_scan = TerraformScan(
        terraform_root_id=root.id,
        status=ScanStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        score=50.0,
        grade="C",
    )
    db.add(tf_scan)
    db.commit()
    db.refresh(tf_scan)
    db.add(
        TerraformFinding(
            scan_id=tf_scan.id,
            terraform_root_id=root.id,
            rule_id=tf_rule.id,
            fingerprint=uuid.uuid4().hex[:16],
            severity=tf_rule.severity,
            category=tf_rule.category,
            status=FindingStatus.open,
            message="tf finding",
            file_path="main.tf",
            resource_address="aws_s3_bucket.x",
        )
    )
    db.commit()

    body = _fetch(client, member)

    assert _engine(body, "docker")["findings"]["open"] == 1
    assert _engine(body, "terraform")["findings"]["open"] == 1
    assert _engine(body, "workflow")["findings"]["open"] == 0
    assert _engine(body, "cloud")["findings"]["open"] == 0
    assert body["totals"]["open_findings"] == 2


# ─── Fix pipeline ────────────────────────────────────────────────────────────


def test_cloud_has_no_fix_pipeline(client: TestClient, member: dict[str, str]) -> None:
    body = _fetch(client, member)

    # Not an all-zero object: CloudFinding carries no fix_id, so "0 ready to
    # deliver" would read as "nothing left to fix" rather than "not a thing".
    assert _engine(body, "cloud")["fixes"] is None
    for key in ("workflow", "docker", "terraform"):
        assert _engine(body, key)["fixes"] is not None


def test_fix_buckets_partition_the_open_findings(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    scan = _docker_scan(db, docker_target)
    ready = _docker_fix(db, docker_target, FixStatus.ready)
    delivered = _docker_fix(db, docker_target, FixStatus.delivered)
    rejected = _docker_fix(db, docker_target, FixStatus.rejected_by_user)
    _docker_finding(db, docker_target, scan, docker_rule, fix_id=ready.id)
    _docker_finding(db, docker_target, scan, docker_rule, fix_id=delivered.id)
    _docker_finding(db, docker_target, scan, docker_rule, fix_id=rejected.id)
    _docker_finding(db, docker_target, scan, docker_rule)

    docker = _engine(_fetch(client, member), "docker")
    fixes = docker["fixes"]

    assert fixes["ready"] == 1
    assert fixes["delivered"] == 1
    # A rejected fix is not "being addressed" — it folds into unfixed alongside
    # the finding that has no fix row at all, matching list_issues(unfixed=True).
    assert fixes["unfixed"] == 2
    assert (
        fixes["unfixed"]
        + fixes["in_progress"]
        + fixes["ready"]
        + fixes["delivered"]
        + fixes["landed"]
        + fixes["failed"]
        == docker["findings"]["open"]
    )


# ─── Top rules ───────────────────────────────────────────────────────────────


def test_top_rules_rank_by_open_count_and_respect_the_limit(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
) -> None:
    rules = db.exec(
        select(Rule).where(Rule.domain == RuleDomain.container_docker).limit(2)
    ).all()
    assert len(rules) == 2
    noisy, quiet = rules
    scan = _docker_scan(db, docker_target)
    for _ in range(3):
        _docker_finding(db, docker_target, scan, noisy)
    _docker_finding(db, docker_target, scan, quiet)

    body = _fetch(client, member, top_rules_limit=1)
    top_rules = _engine(body, "docker")["top_rules"]

    assert len(top_rules) == 1
    assert top_rules[0]["slug"] == noisy.slug
    assert top_rules[0]["open"] == 3
    assert top_rules[0]["title"] == noisy.title


def test_top_rules_can_be_switched_off(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    scan = _docker_scan(db, docker_target)
    _docker_finding(db, docker_target, scan, docker_rule)

    body = _fetch(client, member, top_rules_limit=0)

    assert _engine(body, "docker")["top_rules"] == []


# ─── CI engine specifics ─────────────────────────────────────────────────────


def _workflow_file(db: Session, repo: Repository, branch: str) -> WorkflowFile:
    workflow = WorkflowFile(
        repo_id=repo.id,
        branch=branch,
        path=f".github/workflows/{uuid.uuid4().hex[:8]}.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push",
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def test_ci_targets_are_scoped_to_the_default_branch(
    client: TestClient, db: Session, member: dict[str, str], repo: Repository
) -> None:
    """Feature-branch workflow files must not inflate CI coverage — the same
    scoping compute_avg_scores_batch applies to the repo grade."""
    _workflow_file(db, repo, "main")
    _workflow_file(db, repo, "feature/x")

    ci = _engine(_fetch(client, member), "workflow")

    assert ci["coverage"]["total"] == 1
    # A workflow file has no enable switch, so enabled tracks total.
    assert ci["coverage"]["enabled"] == 1


def test_soft_deleted_workflow_files_are_excluded(
    client: TestClient, db: Session, member: dict[str, str], repo: Repository
) -> None:
    workflow = _workflow_file(db, repo, "main")
    workflow.deleted_at = datetime.now(timezone.utc)
    db.add(workflow)
    db.commit()

    ci = _engine(_fetch(client, member), "workflow")

    assert ci["coverage"]["total"] == 0


def test_ci_open_issue_count_matches_the_issues_stats_endpoint(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    repo: Repository,
    workflow_rule: Rule,
) -> None:
    """The dashboard shows both numbers on one page — if the overview's CI
    counts ever stop matching /issues/stats, the page contradicts itself."""
    workflow = _workflow_file(db, repo, "main")
    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow.id,
        content_hash=uuid.uuid4().hex,
        status=AnalysisStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        score=80.0,
        grade="B",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    for _ in range(2):
        db.add(
            Issue(
                analysis_id=analysis.id,
                workflow_file_id=workflow.id,
                rule_id=workflow_rule.id,
                fingerprint=uuid.uuid4().hex[:16],
                severity=workflow_rule.severity,
                category=workflow_rule.category,
                message="issue",
            )
        )
    db.commit()

    overview_ci = _engine(_fetch(client, member), "workflow")
    stats = client.get(f"{settings.API_V1_STR}/issues/stats", headers=member).json()

    assert overview_ci["findings"]["open"] == 2
    assert overview_ci["findings"]["open"] == stats["total_open"]


# ─── Cloud engine specifics ──────────────────────────────────────────────────


def test_cloud_accounts_are_org_scoped_and_count_connected_as_enabled(
    client: TestClient, db: Session, member: dict[str, str], org: Organization
) -> None:
    db.add(
        CloudAccount(
            org_id=org.id,
            provider=CloudProvider.aws,
            display_name="prod",
            external_id=uuid.uuid4().hex,
            status=CloudAccountStatus.connected,
        )
    )
    db.add(
        CloudAccount(
            org_id=org.id,
            provider=CloudProvider.aws,
            display_name="staging",
            external_id=uuid.uuid4().hex,
            status=CloudAccountStatus.pending_verification,
        )
    )
    db.commit()

    cloud = _engine(_fetch(client, member), "cloud")

    assert cloud["coverage"]["total"] == 2
    # "Enabled" is a status enum here, not a bool column like Docker/Terraform.
    assert cloud["coverage"]["enabled"] == 1
    assert cloud["coverage"]["never_scanned"] == 2


def test_cloud_findings_are_counted(
    client: TestClient, db: Session, member: dict[str, str], org: Organization
) -> None:
    account = CloudAccount(
        org_id=org.id,
        provider=CloudProvider.aws,
        display_name="prod",
        external_id=uuid.uuid4().hex,
        status=CloudAccountStatus.connected,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    scan = CloudScan(
        cloud_account_id=account.id,
        status=ScanStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        score=60.0,
        grade="C",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.cloud_aws)).first()
    assert rule is not None
    db.add(
        CloudFinding(
            scan_id=scan.id,
            cloud_account_id=account.id,
            rule_id=rule.id,
            fingerprint=uuid.uuid4().hex[:16],
            severity=rule.severity,
            category=rule.category,
            status=FindingStatus.open,
            message="cloud finding",
            resource_type="AWS::S3::Bucket",
            resource_id="my-bucket",
        )
    )
    db.commit()

    cloud = _engine(_fetch(client, member), "cloud")

    assert cloud["findings"]["open"] == 1
    assert cloud["score"]["grade"] == "C"


# ─── Totals ──────────────────────────────────────────────────────────────────


def test_totals_sum_the_engines(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    docker_target: DockerTarget,
    docker_rule: Rule,
) -> None:
    scan = _docker_scan(db, docker_target)
    _docker_finding(db, docker_target, scan, docker_rule)

    body = _fetch(client, member)

    assert body["totals"]["open_findings"] == sum(
        e["findings"]["open"] for e in body["engines"]
    )
    assert body["totals"]["targets"] == sum(
        e["coverage"]["total"] for e in body["engines"]
    )
    assert body["totals"]["engines_with_data"] == 1
    assert sum(row["open"] for row in body["totals"]["by_severity"]) == 1


def test_totals_average_engines_not_targets(
    client: TestClient,
    db: Session,
    member: dict[str, str],
    repo: Repository,
    docker_target: DockerTarget,
) -> None:
    """Two Docker targets at 60 and 80 average to 70 for that engine; one
    Terraform root at 90 is the other engine. The total is 80 — the mean of
    the two engine means — not 76.7, the mean of the three targets."""
    _docker_scan(db, docker_target, score=60.0, grade="C")
    second = DockerTarget(repo_id=repo.id, root_path="second")
    db.add(second)
    db.commit()
    db.refresh(second)
    _docker_scan(db, second, score=80.0, grade="B")

    root = TerraformRoot(repo_id=repo.id, root_path="infra")
    db.add(root)
    db.commit()
    db.refresh(root)
    db.add(
        TerraformScan(
            terraform_root_id=root.id,
            status=ScanStatus.completed,
            triggered_by=AnalysisTrigger.manual,
            score=90.0,
            grade="A+",
        )
    )
    db.commit()

    body = _fetch(client, member)

    assert _engine(body, "docker")["score"]["avg_score"] == 70.0
    assert _engine(body, "terraform")["score"]["avg_score"] == 90.0
    assert body["totals"]["avg_score"] == 80.0


def test_superuser_sees_across_orgs(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    docker_target: DockerTarget,
) -> None:
    """No exact counts here on purpose — the session-scoped db means a
    superuser call sees the whole suite's rows. Only the >= relation holds."""
    _docker_scan(db, docker_target)

    body = _fetch(client, superuser_token_headers)

    assert _engine(body, "docker")["coverage"]["total"] >= 1


def test_a_user_with_no_orgs_sees_nothing(
    client: TestClient, db: Session, docker_target: DockerTarget
) -> None:
    _docker_scan(db, docker_target)
    password = random_lower_string()
    user: User = create_random_user(db)
    user.hashed_password = get_password_hash(password)
    db.add(user)
    db.commit()
    headers = user_authentication_headers(
        client=client, email=user.email, password=password
    )

    body = _fetch(client, headers)

    assert body["totals"]["targets"] == 0
