"""Tests for the fix generation pipeline using realistic workflow content.

The encode/httpx test-suite workflow is used as WorkflowFile.raw_content throughout,
replacing the trivial 'on: push\njobs: {}' stub used elsewhere.
Tests cover _parse_llm_response (pure), generate/deliver/sync endpoints (mocked Celery
and GitHub), and the full LLM→patch→apply roundtrip via a directly-mocked _generate_fixes.
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
from app.workers.patch_utils import apply_patch
from app.workers.tasks.fix_generation import _parse_llm_response, run_fix_generation

_FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "workflows"
_HTTPX_WORKFLOW = (_FIXTURES / "httpx_test_suite.yml").read_text()

# Realistic 40-char SHA replacing actions/checkout@v4
_CHECKOUT_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
# Realistic 40-char SHA replacing actions/setup-python@v6
_SETUP_PYTHON_SHA = "ece7cb06caefa5fff74198d8649806c4678c61a1"

# Fingerprint pre-seeded on the test issue so the LLM mock can target it
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


@pytest.fixture()
def ready_fix(db: Session, issue: Issue) -> Fix:
    diff = (
        "--- a/.github/workflows/test-suite.yml\n"
        "+++ b/.github/workflows/test-suite.yml\n"
        "@@ -19,1 +19,1 @@\n"
        '-      - uses: "actions/checkout@v4"\n'
        f'+      - uses: "actions/checkout@{_CHECKOUT_SHA}"  # v4\n'
    )
    f = Fix(
        issue_id=issue.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=FixStatus.ready,
        diff=diff,
        patch=diff,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


# ═══════════════════════════════════════════════════════════════════════════════
# _parse_llm_response — pure function tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_parse_llm_response_extracts_full_content() -> None:
    """full_content block is returned as a plain string."""
    llm_output = (
        "<full_content>\n"
        "name: Test Suite\non: push\njobs:\n  tests:\n    runs-on: ubuntu-latest\n"
        "</full_content>\n"
        f'<fix fingerprint="{_ISSUE_FINGERPRINT}">\n'
        "--- a/test.yml\n+++ b/test.yml\n@@ -1,1 +1,1 @@\n-on: push\n+on: workflow_dispatch\n"
        "</fix>\n"
    )
    full_content, patches = _parse_llm_response(llm_output)
    assert "name: Test Suite" in full_content
    assert _ISSUE_FINGERPRINT in patches
    assert "@@ -1,1 +1,1 @@" in patches[_ISSUE_FINGERPRINT]


def test_parse_llm_response_realistic_httpx_patch() -> None:
    """Parses a multi-line YAML diff pinning both unpinned actions in the httpx workflow."""
    patch_body = (
        "--- a/.github/workflows/test-suite.yml\n"
        "+++ b/.github/workflows/test-suite.yml\n"
        "@@ -19,2 +19,2 @@\n"
        '-      - uses: "actions/checkout@v4"\n'
        '-      - uses: "actions/setup-python@v6"\n'
        f'+      - uses: "actions/checkout@{_CHECKOUT_SHA}"  # v4\n'
        f'+      - uses: "actions/setup-python@{_SETUP_PYTHON_SHA}"  # v6\n'
    )
    llm_output = (
        f"<full_content>\n{_HTTPX_WORKFLOW}</full_content>\n"
        f'<fix fingerprint="{_ISSUE_FINGERPRINT}">\n{patch_body}</fix>\n'
    )
    full_content, patches = _parse_llm_response(llm_output)
    # _parse_llm_response strips the optional trailing \n before </full_content>
    assert full_content.strip() == _HTTPX_WORKFLOW.strip()
    assert _ISSUE_FINGERPRINT in patches
    assert _CHECKOUT_SHA in patches[_ISSUE_FINGERPRINT]
    assert _SETUP_PYTHON_SHA in patches[_ISSUE_FINGERPRINT]


def test_parse_llm_response_missing_full_content_returns_empty_string() -> None:
    llm_output = (
        '<fix fingerprint="fp1">\n--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+b\n</fix>'
    )
    full_content, patches = _parse_llm_response(llm_output)
    assert full_content == ""
    assert "fp1" in patches


def test_parse_llm_response_multiple_fix_blocks() -> None:
    """Multiple <fix> blocks for separate issues are all extracted."""
    llm_output = (
        "<full_content>\ncontent\n</full_content>\n"
        '<fix fingerprint="fp-checkout">\ndiff-checkout\n</fix>\n'
        '<fix fingerprint="fp-timeout">\ndiff-timeout\n</fix>\n'
    )
    _, patches = _parse_llm_response(llm_output)
    assert set(patches.keys()) == {"fp-checkout", "fp-timeout"}
    assert patches["fp-checkout"] == "diff-checkout"
    assert patches["fp-timeout"] == "diff-timeout"


# ═══════════════════════════════════════════════════════════════════════════════
# Full LLM→patch→apply roundtrip (mocked _generate_fixes, no Celery broker)
# ═══════════════════════════════════════════════════════════════════════════════


def test_full_fix_generation_produces_applicable_patch(
    db: Session, issue: Issue
) -> None:
    """run_fix_generation with a mocked LLM stores a patch that apply_patch can apply."""
    single_line_patch = (
        "--- a/.github/workflows/test-suite.yml\n"
        "+++ b/.github/workflows/test-suite.yml\n"
        "@@ -19,1 +19,1 @@\n"
        '-      - uses: "actions/checkout@v4"\n'
        f'+      - uses: "actions/checkout@{_CHECKOUT_SHA}"  # v4\n'
    )
    llm_response_content = (
        f"<full_content>\n{_HTTPX_WORKFLOW}</full_content>\n"
        f'<fix fingerprint="{_ISSUE_FINGERPRINT}">\n{single_line_patch}</fix>\n'
    )

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
    fix = db.exec(select(Fix).where(Fix.issue_id == issue.id)).first()
    assert fix is not None
    assert fix.status == FixStatus.ready
    assert fix.patch is not None

    patched_content = apply_patch(_HTTPX_WORKFLOW, fix.patch)
    assert patched_content is not None, (
        "apply_patch failed — patch does not apply cleanly"
    )
    assert _CHECKOUT_SHA in patched_content
    assert "actions/checkout@v4" not in patched_content


# ═══════════════════════════════════════════════════════════════════════════════
# Generate endpoint — mocked Celery delay
# ═══════════════════════════════════════════════════════════════════════════════


def test_generate_fix_queued_for_realistic_workflow_issue(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    issue: Issue,
) -> None:
    """POST /fixes/generate/{issue_id} queues task for an issue tied to the httpx workflow."""
    with patch(
        "app.workers.tasks.fix_generation.run_fix_generation.delay"
    ) as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/generate/{issue.id}",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["issue_id"] == str(issue.id)
    mock_delay.assert_called_once_with(issue_ids=[str(issue.id)])


# ═══════════════════════════════════════════════════════════════════════════════
# Deliver endpoint — mocked Celery delay
# ═══════════════════════════════════════════════════════════════════════════════


def test_deliver_realistic_fix_queues_task(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    ready_fix: Fix,
) -> None:
    """POST /fixes/{id}/deliver queues deliver task for a fix tied to the httpx workflow."""
    with patch("app.workers.tasks.fix_delivery.deliver_fix.delay") as mock_delay:
        response = client.post(
            f"{settings.API_V1_STR}/fixes/{ready_fix.id}/deliver",
            headers=superuser_token_headers,
        )

    assert response.status_code == 202
    body = response.json()
    assert body["fix_id"] == str(ready_fix.id)
    mock_delay.assert_called_once_with(fix_id=str(ready_fix.id), force=False)


# ═══════════════════════════════════════════════════════════════════════════════
# PR sync — mocked GitHub client
# ═══════════════════════════════════════════════════════════════════════════════


def test_pr_sync_marks_merged_for_realistic_workflow_fix(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    repo: Repository,
    issue: Issue,
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
        issue_id=issue.id,
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
