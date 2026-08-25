"""Builders for the rows tests need, so each test file stops writing its own.

Thirty-eight test modules built an `Organization` by hand, most of them a
`Repository` and a `WorkflowFile` too, and twenty-nine carried a private
`_make_*` or `_seed_*` helper doing the same three lines with a different name.
That is a lot of places to visit when a column gains a `NOT NULL`, and it is why
`tests/fixtures/` existed as an empty package — the intent was there, the
factories never were.

Every builder commits and refreshes, takes sensible defaults, and accepts
overrides for whatever the test is actually about. Identifiers are randomised so
builders can be called repeatedly in one session without colliding on a unique
constraint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session

from app.models import (
    Category,
    LLMProvider,
    Organization,
    OrgMember,
    OrgRole,
    Repository,
    Rule,
    RuleDomain,
    ScanStatus,
    ScanTrigger,
    Severity,
    User,
    UserTier,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)
from app.services.deduplication import compute_content_hash


def _rand(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _save(session: Session, obj: Any) -> Any:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


def make_org(
    session: Session,
    *,
    name: str | None = None,
    tier: UserTier = UserTier.free,
    **kw: Any,
) -> Organization:
    return _save(session, Organization(name=name or _rand("org-"), tier=tier, **kw))


def make_member(
    session: Session, org: Organization, user: User, role: OrgRole = OrgRole.member
) -> OrgMember:
    return _save(session, OrgMember(org_id=org.id, user_id=user.id, role=role))


def make_repo(
    session: Session,
    org: Organization,
    *,
    full_name: str | None = None,
    installation_id: int = 99991,
    **kw: Any,
) -> Repository:
    return _save(
        session,
        Repository(
            org_id=org.id,
            # Modulo keeps it inside a 32-bit column while staying collision-free
            # in practice for a test session.
            github_repo_id=int(uuid.uuid4().int % 10**9),
            full_name=full_name or f"owner/{_rand('repo-')}",
            installation_id=installation_id,
            **kw,
        ),
    )


def make_workflow_file(
    session: Session,
    repo: Repository,
    *,
    path: str = ".github/workflows/ci.yml",
    branch: str | None = None,
    raw_content: str = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
    **kw: Any,
) -> WorkflowFile:
    return _save(
        session,
        WorkflowFile(
            repo_id=repo.id,
            path=path,
            branch=branch or repo.default_branch,
            raw_content=raw_content,
            # Derived rather than defaulted, so a test that changes the content
            # gets a hash that matches it — which is what the duplicate-skip
            # path in static_analysis actually keys on.
            content_hash=kw.pop("content_hash", compute_content_hash(raw_content)),
            **kw,
        ),
    )


def make_rule(
    session: Session,
    *,
    slug: str | None = None,
    domain: RuleDomain = RuleDomain.ci_workflow,
    severity: Severity = Severity.high,
    category: Category = Category.security,
    **kw: Any,
) -> Rule:
    return _save(
        session,
        Rule(
            slug=slug or _rand("rule-"),
            domain=domain,
            severity=severity,
            category=category,
            title=kw.pop("title", "Test rule"),
            description=kw.pop("description", "A rule, for testing."),
            **kw,
        ),
    )


def make_scan(
    session: Session,
    repo: Repository,
    workflow_file: WorkflowFile | None = None,
    *,
    status: ScanStatus = ScanStatus.completed,
    score: float | None = 90.0,
    **kw: Any,
) -> WorkflowScan:
    return _save(
        session,
        WorkflowScan(
            repo_id=repo.id,
            workflow_file_id=workflow_file.id if workflow_file else None,
            content_hash=kw.pop("content_hash", _rand()),
            status=status,
            score=score,
            triggered_by=kw.pop("triggered_by", ScanTrigger.manual),
            completed_at=kw.pop("completed_at", datetime.now(timezone.utc)),
            **kw,
        ),
    )


def make_finding(
    session: Session,
    scan: WorkflowScan,
    rule: Rule,
    *,
    workflow_file: WorkflowFile | None = None,
    severity: Severity = Severity.high,
    category: Category = Category.security,
    **kw: Any,
) -> WorkflowFinding:
    return _save(
        session,
        WorkflowFinding(
            analysis_id=scan.id,
            workflow_file_id=(
                workflow_file.id if workflow_file else scan.workflow_file_id
            ),
            rule_id=rule.id,
            severity=severity,
            category=category,
            message=kw.pop("message", "Test violation"),
            fingerprint=kw.pop("fingerprint", _rand()[:16]),
            **kw,
        ),
    )


def make_fix(
    session: Session,
    workflow_file: WorkflowFile,
    *,
    provider: LLMProvider = LLMProvider.openai,
    model: str = "gpt-4o-mini",
    **kw: Any,
) -> WorkflowFix:
    return _save(
        session,
        WorkflowFix(
            workflow_file_id=workflow_file.id,
            llm_provider=provider,
            llm_model=model,
            **kw,
        ),
    )
