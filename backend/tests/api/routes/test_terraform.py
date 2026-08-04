"""Tests for the /api/v1/terraform-roots/ endpoints."""

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AnalysisTrigger,
    FixStatus,
    IssueCategory,
    IssueSeverity,
    LLMProvider,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    TerraformFinding,
    TerraformFix,
    TerraformRoot,
    TerraformScan,
    User,
    UserTier,
)

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "terraform"

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    organization = Organization(
        name=f"tfapi-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    repository = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"tfapiowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=66666,
    )
    db.add(repository)
    db.commit()
    db.refresh(repository)
    return repository


@pytest.fixture()
def terraform_root(db: Session, repo: Repository) -> TerraformRoot:
    root = TerraformRoot(repo_id=repo.id, root_path=f"infra/{uuid.uuid4().hex[:8]}")
    db.add(root)
    db.commit()
    db.refresh(root)
    return root


@pytest.fixture()
def seeded_terraform_rule(db: Session) -> Rule:
    rule = db.exec(select(Rule).where(Rule.domain == RuleDomain.iac_terraform)).first()
    assert rule is not None
    return rule


@pytest.fixture()
def completed_scan(db: Session, terraform_root: TerraformRoot) -> TerraformScan:
    scan = TerraformScan(
        terraform_root_id=terraform_root.id,
        status=ScanStatus.completed,
        triggered_by=AnalysisTrigger.manual,
        score=72.0,
        grade="B",
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan


# ─── POST /terraform-roots/ ────────────────────────────────────────────────────


def test_create_terraform_root(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "infra/prod"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["root_path"] == "infra/prod"
    assert body["repo_id"] == str(repo.id)
    assert body["enabled"] is True


def test_create_terraform_root_normalizes_slashes(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "/infra/prod/"},
    )
    assert response.status_code == 201
    assert response.json()["root_path"] == "infra/prod"


def test_create_terraform_root_rejects_empty_path(
    client: TestClient, superuser_token_headers: dict[str, str], repo: Repository
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": "///"},
    )
    assert response.status_code == 422


def test_create_terraform_root_duplicate_conflicts(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        json={"repo_id": str(repo.id), "root_path": terraform_root.root_path},
    )
    assert response.status_code == 409


# ─── GET /terraform-roots/ ──────────────────────────────────────────────────────


def test_list_terraform_roots(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(terraform_root.id)


def test_list_terraform_roots_includes_latest_grade(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,  # noqa: ARG001
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    body = response.json()
    assert body[0]["latest_score"] == 72.0
    assert body[0]["latest_grade"] == "B"


def test_list_terraform_roots_includes_repo_full_name(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
        params={"repo_id": str(repo.id)},
    )
    body = response.json()
    assert body[0]["repo_full_name"] == repo.full_name
    assert body[0]["id"] == str(terraform_root.id)


def test_list_terraform_roots_without_repo_id_is_org_wide(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    # No repo_id filter — the org-wide Infrastructure page's default query.
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert str(terraform_root.id) in ids


def test_list_terraform_roots_without_repo_id_scoped_to_user_orgs(
    client: TestClient,
    db: Session,
    normal_user_token_headers: dict[str, str],
) -> None:
    user = db.exec(select(User).where(User.email == settings.EMAIL_TEST_USER)).first()
    assert user is not None

    my_org = Organization(name=f"tfapi-mine-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    other_org = Organization(
        name=f"tfapi-theirs-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(my_org)
    db.add(other_org)
    db.commit()
    db.refresh(my_org)
    db.refresh(other_org)
    db.add(OrgMember(org_id=my_org.id, user_id=user.id, role=OrgRole.owner))
    db.commit()

    my_repo = Repository(
        org_id=my_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"mine/repo-{uuid.uuid4().hex[:8]}",
    )
    other_repo = Repository(
        org_id=other_org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"theirs/repo-{uuid.uuid4().hex[:8]}",
    )
    db.add(my_repo)
    db.add(other_repo)
    db.commit()
    db.refresh(my_repo)
    db.refresh(other_repo)

    my_root = TerraformRoot(repo_id=my_repo.id, root_path="infra")
    other_root = TerraformRoot(repo_id=other_repo.id, root_path="infra")
    db.add(my_root)
    db.add(other_root)
    db.commit()
    db.refresh(my_root)
    db.refresh(other_root)

    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/", headers=normal_user_token_headers
    )

    assert response.status_code == 200
    ids = {r["id"] for r in response.json()}
    assert str(my_root.id) in ids
    assert str(other_root.id) not in ids


# ─── PATCH /terraform-roots/{id}/toggle ────────────────────────────────────────


def test_toggle_terraform_root(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    response = client.patch(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/toggle",
        headers=superuser_token_headers,
        params={"enabled": "false"},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False


# ─── DELETE /terraform-roots/{id} ───────────────────────────────────────────────


def test_delete_terraform_root_cascades_scans(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
) -> None:
    root_id = terraform_root.id
    scan_id = completed_scan.id
    response = client.delete(
        f"{settings.API_V1_STR}/terraform-roots/{root_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 204
    # A plain select (not db.get()) avoids ObjectDeletedError when refreshing
    # an already-loaded, strongly-referenced identity-map entry for a row
    # another session just deleted.
    assert (
        db.exec(select(TerraformRoot).where(TerraformRoot.id == root_id)).first()
        is None
    )
    assert (
        db.exec(select(TerraformScan).where(TerraformScan.id == scan_id)).first()
        is None
    )


# ─── POST /terraform-roots/{id}/scan ────────────────────────────────────────────


def test_trigger_terraform_scan(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    with patch(
        "app.workers.tasks.terraform_analysis.run_terraform_scan.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/scan",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["terraform_root_id"] == str(terraform_root.id)


def test_trigger_terraform_scan_disabled_root_rejected(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    terraform_root.enabled = False
    db.add(terraform_root)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/scan",
        headers=superuser_token_headers,
    )
    assert response.status_code == 403


# ─── GET /terraform-roots/{id}/scans ────────────────────────────────────────────


def test_list_terraform_scans(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/scans",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(completed_scan.id)
    assert body[0]["grade"] == "B"


# ─── GET /terraform-roots/{id}/findings ─────────────────────────────────────────


def test_list_terraform_findings_excludes_resolved_by_default(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
    seeded_terraform_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    open_finding = TerraformFinding(
        scan_id=completed_scan.id,
        terraform_root_id=terraform_root.id,
        rule_id=seeded_terraform_rule.id,
        resource_address="aws_s3_bucket.data",
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="open finding",
    )
    resolved_finding = TerraformFinding(
        scan_id=completed_scan.id,
        terraform_root_id=terraform_root.id,
        rule_id=seeded_terraform_rule.id,
        resource_address="aws_s3_bucket.other",
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="resolved finding",
        resolved_at=datetime.now(timezone.utc),
    )
    db.add(open_finding)
    db.add(resolved_finding)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/findings",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["message"] == "open finding"
    assert body[0]["rule_slug"] == seeded_terraform_rule.slug


def test_list_terraform_findings_include_resolved(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
    seeded_terraform_rule: Rule,
) -> None:
    from datetime import datetime, timezone

    resolved_finding = TerraformFinding(
        scan_id=completed_scan.id,
        terraform_root_id=terraform_root.id,
        rule_id=seeded_terraform_rule.id,
        resource_address="aws_s3_bucket.other",
        file_path="main.tf",
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="resolved finding",
        resolved_at=datetime.now(timezone.utc),
    )
    db.add(resolved_finding)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/findings",
        headers=superuser_token_headers,
        params={"include_resolved": "true"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


# ─── GET /terraform-roots/{id}/files ────────────────────────────────────────────


def test_list_terraform_files(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    from types import SimpleNamespace

    # A real registry module (terraform-aws-modules/terraform-aws-security-group,
    # vendored under tests/fixtures/terraform/) rather than two stub lines — the
    # endpoint hands whole files back, so it should be exercised over one.
    module = _FIXTURES / "terraform_aws_security_group"
    fetched = [
        SimpleNamespace(path=name, content=(module / name).read_text())
        for name in ("main.tf", "variables.tf")
    ]
    with patch("app.api.routes.terraform._fetch_terraform_files", return_value=fetched):
        response = client.get(
            f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/files",
            headers=superuser_token_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert [f["path"] for f in body] == ["main.tf", "variables.tf"]
    assert body[0]["raw_content"] == fetched[0].content
    assert 'resource "aws_security_group" "this"' in body[0]["raw_content"]


def test_list_terraform_files_github_failure_is_502(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    with patch(
        "app.api.routes.terraform._fetch_terraform_files",
        side_effect=RuntimeError("boom"),
    ):
        response = client.get(
            f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/files",
            headers=superuser_token_headers,
        )
    assert response.status_code == 502


# ─── POST/GET /terraform-roots/{id}/fixes ───────────────────────────────────────


def _make_open_finding(
    db: Session,
    root: TerraformRoot,
    scan: TerraformScan,
    rule: Rule,
    file_path: str = "main.tf",
) -> TerraformFinding:
    finding = TerraformFinding(
        scan_id=scan.id,
        terraform_root_id=root.id,
        rule_id=rule.id,
        resource_address="aws_s3_bucket.data",
        file_path=file_path,
        fingerprint=uuid.uuid4().hex[:16],
        severity=IssueSeverity.high,
        category=IssueCategory.security,
        message="unencrypted bucket",
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


def test_trigger_terraform_fix_generation_creates_pending_fix(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    repo: Repository,
    terraform_root: TerraformRoot,
    completed_scan: TerraformScan,
    seeded_terraform_rule: Rule,
) -> None:
    # Give the repo an explicit provider so resolve_llm_provider doesn't need a
    # configured API key in the test environment.
    repo.llm_provider = LLMProvider.openai
    repo.llm_model = "gpt-4o-mini"
    db.add(repo)
    db.commit()

    finding = _make_open_finding(
        db, terraform_root, completed_scan, seeded_terraform_rule
    )

    with patch(
        "app.api.routes.terraform.run_terraform_fix_generation.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/fixes",
            headers=superuser_token_headers,
            json={},
        )
    assert response.status_code == 202
    assert response.json()["queued"] == 1
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["finding_ids"] == [str(finding.id)]

    fix = db.exec(
        select(TerraformFix).where(TerraformFix.terraform_root_id == terraform_root.id)
    ).first()
    assert fix is not None
    assert fix.status == FixStatus.pending
    assert fix.file_path == "main.tf"
    db.refresh(finding)
    assert finding.fix_id == fix.id


def test_list_terraform_fixes(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    fix = TerraformFix(
        terraform_root_id=terraform_root.id,
        file_path="main.tf",
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        full_content='resource "aws_s3_bucket" "b" {}\n',
    )
    db.add(fix)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/fixes",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["file_path"] == "main.tf"
    assert body[0]["status"] == "ready"


def test_trigger_terraform_delivery_queues_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    terraform_root: TerraformRoot,
) -> None:
    with patch("app.api.routes.terraform.deliver_terraform_fixes.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/terraform-roots/{terraform_root.id}/deliver",
            headers=superuser_token_headers,
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["pr_branch"].startswith("greensecops/terraform-")
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["terraform_root_id"] == str(terraform_root.id)
