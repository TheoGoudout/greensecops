"""Tests for the fix generation pipeline using realistic workflow content.

The encode/httpx test-suite workflow is used as WorkflowFile.raw_content throughout,
replacing the trivial 'on: push\njobs: {}' stub used elsewhere.
Tests cover the generate endpoint (mocked Celery), the full LLM→full-content
roundtrip via a directly-mocked _generate_fixes, and PR sync (mocked GitHub).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Analysis,
    AnalysisStatus,
    AnalysisTrigger,
    Fix,
    FixStatus,
    Issue,
    IssueCategory,
    IssueSeverity,
    LLMProvider,
    Organization,
    PullRequest,
    Repository,
    Rule,
    UserTier,
    WorkflowFile,
)
from app.workers.tasks.fix_generation import run_fix_generation

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
_HTTPX_WORKFLOW = (_FIXTURES / "httpx_test_suite.yml").read_text()

# Realistic 40-char SHA replacing actions/checkout@v4
_CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"

# Fingerprint pre-seeded on the test issue
_ISSUE_FINGERPRINT = "cafebabe12345678"


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def org(db: Session) -> Organization:
    o = Organization(name=f"fgw-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


@pytest.fixture()
def repo(db: Session, org: Organization) -> Repository:
    r = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"fgw-owner/repo-{uuid.uuid4().hex[:8]}",
        installation_id=40001,
        default_branch="main",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def workflow_file(db: Session, repo: Repository) -> WorkflowFile:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=".github/workflows/test-suite.yml",
        content_hash=uuid.uuid4().hex,
        raw_content=_HTTPX_WORKFLOW,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@pytest.fixture()
def rule(db: Session) -> Rule:
    r = Rule(
        slug=f"fgw-rule-{uuid.uuid4().hex[:8]}",
        category=IssueCategory.reliability,
        severity=IssueSeverity.high,
        title="Unpinned Action (test)",
        description="Rule for fix generation workflow tests",
        enabled=True,
        severity_weight=1.0,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def analysis(db: Session, repo: Repository, workflow_file: WorkflowFile) -> Analysis:
    a = Analysis(
        repo_id=repo.id,
        workflow_file_id=workflow_file.id,
        content_hash=workflow_file.content_hash,
        status=AnalysisStatus.completed,
        score=60.0,
        grade="C",
        triggered_by=AnalysisTrigger.manual,
        branch="main",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@pytest.fixture()
def issue(
    db: Session, analysis: Analysis, rule: Rule, workflow_file: WorkflowFile
) -> Issue:
    i = Issue(
        analysis_id=analysis.id,
        workflow_file_id=workflow_file.id,
        rule_id=rule.id,
        severity=IssueSeverity.high,
        category=IssueCategory.reliability,
        line_start=19,
        line_end=19,
        message="actions/checkout@v4 uses a mutable ref",
        context="actions/checkout@v4",
        fingerprint=_ISSUE_FINGERPRINT,
    )
    db.add(i)
    db.commit()
    db.refresh(i)
    return i


# ═══════════════════════════════════════════════════════════════════════════════
# Full LLM→full-content roundtrip (mocked _generate_fixes, no Celery broker)
# ═══════════════════════════════════════════════════════════════════════════════


def test_full_fix_generation_stores_full_content(
    db: Session, issue: Issue, workflow_file: WorkflowFile
) -> None:
    """run_fix_generation with a mocked LLM stores one whole-file fix per workflow."""
    fixed_workflow = _HTTPX_WORKFLOW.replace(
        '"actions/checkout@v4"',
        f'"actions/checkout@{_CHECKOUT_SHA}"  # v4',
    )
    llm_response_content = f"<full_content>\n{fixed_workflow}</full_content>\n"

    class _FakeLLMResult:
        content = llm_response_content
        prompt_tokens = 500
        completion_tokens = 100
        run_id = None

    with (
        patch(
            "app.workers.tasks.fix_generation._resolve_llm_provider",
            return_value=("openai", "gpt-4o-mini"),
        ),
        patch(
            "app.workers.tasks.fix_generation._generate_fixes",
            new=AsyncMock(return_value=_FakeLLMResult()),
        ),
    ):
        run_fix_generation.apply(kwargs={"issue_ids": [str(issue.id)]})

    db.expire_all()
    fix = db.exec(select(Fix).where(Fix.workflow_file_id == workflow_file.id)).first()
    assert fix is not None
    assert fix.status == FixStatus.ready
    assert fix.full_content is not None
    assert _CHECKOUT_SHA in fix.full_content
    assert 'actions/checkout@v4"' not in fix.full_content
    assert fix.prompt_tokens == 500

    # The addressed issue is linked to the workflow fix
    db.refresh(issue)
    assert issue.fix_id == fix.id


def test_full_fix_generation_invalid_yaml_marks_failed(
    db: Session, issue: Issue, workflow_file: WorkflowFile
) -> None:
    """A full_content response that is not valid YAML must not be stored as ready."""
    llm_response_content = "<full_content>\n{ invalid: yaml: [}\n</full_content>\n"

    class _FakeLLMResult:
        content = llm_response_content
        prompt_tokens = 10
        completion_tokens = 10
        run_id = None

    with (
        patch(
            "app.workers.tasks.fix_generation._resolve_llm_provider",
            return_value=("openai", "gpt-4o-mini"),
        ),
        patch(
            "app.workers.tasks.fix_generation._generate_fixes",
            new=AsyncMock(return_value=_FakeLLMResult()),
        ),
    ):
        run_fix_generation.apply(kwargs={"issue_ids": [str(issue.id)]})

    db.expire_all()
    fix = db.exec(select(Fix).where(Fix.workflow_file_id == workflow_file.id)).first()
    assert fix is not None
    assert fix.status == FixStatus.failed
    assert fix.full_content is None


# ═══════════════════════════════════════════════════════════════════════════════
# Generate endpoint — mocked Celery delay
# ═══════════════════════════════════════════════════════════════════════════════


def test_generate_fix_queued_for_realistic_workflow_issue(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
    repo: Repository,
) -> None:
    """generate-for-repo with a single issue id queues one whole-file fix task."""
    with patch("app.api.routes.fixes.run_fix_generation.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate-for-repo/{repo.id}",
            headers=superuser_token_headers,
            json={"issue_ids": [str(issue.id)]},
        )

    assert response.status_code == 202
    assert response.json()["queued"] == 1
    mock_delay.assert_called_once_with(issue_ids=[str(issue.id)], batch_mode=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PR sync — mocked GitHub client
# ═══════════════════════════════════════════════════════════════════════════════


def test_pr_sync_marks_merged_for_realistic_workflow_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    workflow_file: WorkflowFile,
) -> None:
    """PR sync updates state to merged for a PR associated with an httpx-workflow fix."""
    pr_url = f"https://github.com/{repo.full_name}/pull/42"
    pr = PullRequest(
        repo_id=repo.id,
        pr_branch="greensecops/fix-httpx-checkout",
        pr_url=pr_url,
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    delivered_fix = Fix(
        workflow_file_id=workflow_file.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.delivered,
        pr_id=pr.id,
    )
    db.add(delivered_fix)
    db.commit()

    from app.api.deps import get_github_app_client
    from app.main import app as fastapi_app

    mock_gh = AsyncMock()
    mock_gh.get_pr_state = AsyncMock(return_value="merged")
    fastapi_app.dependency_overrides[get_github_app_client] = lambda: mock_gh
    try:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/sync-pr-status/{repo.id}",
            headers=superuser_token_headers,
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_github_app_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["updated"] >= 1

    db.refresh(pr)
    assert pr.pr_state == "merged"
