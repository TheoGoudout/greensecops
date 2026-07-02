"""Unit tests for SSE event schema factory functions."""

from app.services.events import schemas as ev


def test_fix_ready_batch_has_correct_event_and_org() -> None:
    event = ev.fix_ready_batch("org-1", "repo-1", ["fix-a", "fix-b"])
    assert event.event == "fix.ready"
    assert event.org_id == "org-1"
    assert event.data["repo_id"] == "repo-1"
    assert event.data["fix_ids"] == ["fix-a", "fix-b"]


def test_fix_delivering_batch_has_correct_event() -> None:
    event = ev.fix_delivering_batch("org-1", "repo-1", ["fix-a"])
    assert event.event == "fix.delivering"
    assert event.org_id == "org-1"
    assert event.data["fix_ids"] == ["fix-a"]


def test_fix_delivered_batch_has_correct_event_and_pr_url() -> None:
    event = ev.fix_delivered_batch(
        "org-1", "repo-1", ["fix-a", "fix-b"], "https://pr.url", "fix-branch"
    )
    assert event.event == "fix.delivered"
    assert event.data["pr_url"] == "https://pr.url"
    assert event.data["pr_branch"] == "fix-branch"
    assert event.data["fix_ids"] == ["fix-a", "fix-b"]


def test_fix_delivered_batch_accepts_none_pr_url() -> None:
    event = ev.fix_delivered_batch("org-1", "repo-1", [], None, "branch")
    assert event.data["pr_url"] is None


def test_analysis_queued_has_correct_fields() -> None:
    event = ev.analysis_queued("org-1", "repo-1", "main", "manual")
    assert event.event == "analysis.queued"
    assert event.data["branch"] == "main"
    assert event.data["trigger"] == "manual"


def test_sse_event_to_wire_format() -> None:
    event = ev.fix_ready_batch("org-1", "repo-1", ["fix-a"])
    wire = event.to_wire()
    assert wire.startswith("data: ")
    assert wire.endswith("\n\n")
    assert "fix.ready" in wire
