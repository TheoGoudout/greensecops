"""Cross-tenant authorization tests for issues / analyses / fixes.

Regression coverage for the BOLA fix: an authenticated user who is not a member
of a repository's organization must not be able to read or act on that
repository's issues, analyses, or fixes.
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    Category,
    Fix,
    FixStatus,
    Issue,
    LLMProvider,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    Rule,
    ScanTrigger,
    Severity,
    UserTier,
    UserUpdate,
    WorkflowFile,
)
from tests.utils.user import create_random_user, user_authentication_headers
from tests.utils.utils import random_lower_string


class _Tenant:
    def __init__(self, org, repo, analysis, issue, fix):
        self.org = org
        self.repo = repo
        self.analysis = analysis
        self.issue = issue
        self.fix = fix


@pytest.fixture()
def rule(db: Session) -> Rule:
    r = Rule(
        slug=f"authz-rule-{uuid.uuid4().hex[:8]}",
        category=Category.security,
        severity=Severity.high,
        title="Authz Rule",
        description="rule for authz tests",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _make_tenant(db: Session, rule: Rule) -> _Tenant:
    org = Organization(name=f"authz-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(org)
    db.commit()
    db.refresh(org)

    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"authzowner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=int(uuid.uuid4().int % 10**8),
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/authz.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)

    analysis = Analysis(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=AnalysisStatus.completed,
        score=80.0,
        grade="B",
        triggered_by=ScanTrigger.manual,
        branch="main",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    issue = Issue(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        severity=Severity.high,
        category=Category.security,
        message="secret tenant issue",
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)

    fix = Fix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    issue.fix_id = fix.id
    db.add(issue)
    db.commit()

    return _Tenant(org, repo, analysis, issue, fix)


@pytest.fixture()
def victim(db: Session, rule: Rule) -> _Tenant:
    return _make_tenant(db, rule)


@pytest.fixture()
def outsider_headers(client: TestClient, db: Session) -> dict[str, str]:
    """An authenticated user who belongs to no organization."""
    password = random_lower_string()
    user = create_random_user(db)
    crud.update_user(session=db, db_user=user, user_in=UserUpdate(password=password))
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


@pytest.fixture()
def member_headers(client: TestClient, db: Session, victim: _Tenant) -> dict[str, str]:
    """A user who IS a member of the victim organization."""
    password = random_lower_string()
    user = create_random_user(db)
    crud.update_user(session=db, db_user=user, user_in=UserUpdate(password=password))
    db.add(OrgMember(org_id=victim.org.id, user_id=user.id, role=OrgRole.member))
    db.commit()
    return user_authentication_headers(
        client=client, email=user.email, password=password
    )


# ─── Reads are scoped ─────────────────────────────────────────────────────────


def test_outsider_cannot_list_issues(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/issues/",
        params={"repo_id": str(victim.repo.id)},
        headers=outsider_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_outsider_cannot_get_issue(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/issues/{victim.issue.id}", headers=outsider_headers
    )
    assert resp.status_code == 404


def test_outsider_cannot_list_analyses(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/analyses/",
        params={"repo_id": str(victim.repo.id)},
        headers=outsider_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_outsider_cannot_get_analysis(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/analyses/{victim.analysis.id}",
        headers=outsider_headers,
    )
    assert resp.status_code == 404


def test_outsider_cannot_list_fixes(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"repo_id": str(victim.repo.id)},
        headers=outsider_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_outsider_cannot_get_fix(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/fixes/{victim.fix.id}", headers=outsider_headers
    )
    assert resp.status_code == 404


# ─── State-changing actions are scoped ───────────────────────────────────────


def test_outsider_cannot_trigger_analysis(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/analyses/trigger/{victim.repo.id}",
        headers=outsider_headers,
    )
    assert resp.status_code == 404


def test_outsider_cannot_deliver_fixes_for_repo(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/fixes/deliver-for-repo/{victim.repo.id}",
        headers=outsider_headers,
    )
    assert resp.status_code == 404


def test_outsider_cannot_generate_fixes_for_repo(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/fixes/generate-for-repo/{victim.repo.id}",
        headers=outsider_headers,
        json={"issue_ids": [str(victim.issue.id)]},
    )
    assert resp.status_code == 404


def test_outsider_cannot_deliver_fix_for_workflow(
    client: TestClient, outsider_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.post(
        f"{settings.API_V1_STR}/fixes/deliver-for-workflow",
        headers=outsider_headers,
        json={"fix_id": str(victim.fix.id)},
    )
    assert resp.status_code == 404


# ─── Members retain access ───────────────────────────────────────────────────


def test_member_can_get_issue(
    client: TestClient, member_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/issues/{victim.issue.id}", headers=member_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(victim.issue.id)


def test_member_can_list_fixes(
    client: TestClient, member_headers: dict[str, str], victim: _Tenant
) -> None:
    resp = client.get(
        f"{settings.API_V1_STR}/fixes/",
        params={"repo_id": str(victim.repo.id)},
        headers=member_headers,
    )
    assert resp.status_code == 200
    assert any(f["id"] == str(victim.fix.id) for f in resp.json())
