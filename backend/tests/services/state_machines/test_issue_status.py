"""Tests for the derived Issue.status property."""

import uuid
from datetime import datetime, timezone

from app.models import Issue
from app.models.enums import IssueCategory, IssueSeverity, IssueStatus


def _issue(**overrides: object) -> Issue:
    kwargs: dict[str, object] = {
        "analysis_id": uuid.uuid4(),
        "rule_id": uuid.uuid4(),
        "severity": IssueSeverity.high,
        "category": IssueCategory.security,
        "message": "boom",
    }
    kwargs.update(overrides)
    return Issue(**kwargs)


def test_open_when_unresolved_and_unlinked() -> None:
    assert _issue().status is IssueStatus.open


def test_fix_in_progress_when_linked() -> None:
    assert _issue(fix_id=uuid.uuid4()).status is IssueStatus.fix_in_progress


def test_resolved_when_resolved_at_set() -> None:
    assert _issue(resolved_at=datetime.now(timezone.utc)).status is IssueStatus.resolved


def test_resolved_wins_over_fix_link() -> None:
    issue = _issue(fix_id=uuid.uuid4(), resolved_at=datetime.now(timezone.utc))
    assert issue.status is IssueStatus.resolved
