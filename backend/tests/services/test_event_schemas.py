"""Unit tests for SSE event schema factory functions."""

from app.models.enums import SSESignal
from app.services.events import schemas as ev


def test_fix_ready_has_correct_event_and_org() -> None:
    event = ev.fix_ready("org-1", "repo-1", "fix-a", ["issue-a", "issue-b"])
    assert event.event == SSESignal.fix_ready
    assert event.org_id == "org-1"
    assert event.data["repo_id"] == "repo-1"
    assert event.data["fix_id"] == "fix-a"
    assert event.data["issue_ids"] == ["issue-a", "issue-b"]


def test_fix_delivering_batch_has_correct_event() -> None:
    event = ev.fix_delivering_batch("org-1", "repo-1", ["fix-a"])
    assert event.event == SSESignal.fix_delivering
    assert event.org_id == "org-1"
    assert event.data["fix_ids"] == ["fix-a"]


def test_fix_delivered_batch_has_correct_event_and_pr_url() -> None:
    event = ev.fix_delivered_batch(
        "org-1", "repo-1", ["fix-a", "fix-b"], "https://pr.url", "fix-branch"
    )
    assert event.event == SSESignal.fix_delivered
    assert event.data["pr_url"] == "https://pr.url"
    assert event.data["pr_branch"] == "fix-branch"
    assert event.data["fix_ids"] == ["fix-a", "fix-b"]


def test_fix_delivered_batch_accepts_none_pr_url() -> None:
    event = ev.fix_delivered_batch("org-1", "repo-1", [], None, "branch")
    assert event.data["pr_url"] is None


def test_analysis_queued_has_correct_fields() -> None:
    event = ev.analysis_queued("org-1", "repo-1", "main", "manual")
    assert event.event == SSESignal.analysis_queued
    assert event.data["branch"] == "main"
    assert event.data["trigger"] == "manual"


def test_sse_event_to_wire_format() -> None:
    event = ev.fix_ready("org-1", "repo-1", "fix-a", ["issue-a"])
    wire = event.to_wire()
    assert wire.startswith("data: ")
    assert wire.endswith("\n\n")
    assert "fix.ready" in wire


def test_fix_skipped_has_correct_fields() -> None:
    event = ev.fix_skipped("org-1", "repo-1")
    assert event.event == SSESignal.fix_skipped
    assert event.org_id == "org-1"
    assert event.data["repo_id"] == "repo-1"
    assert "org_id" not in event.data


def test_installation_suspended_has_correct_fields() -> None:
    event = ev.installation_suspended("org-1", 42, 3)
    assert event.event == SSESignal.installation_suspended
    assert event.org_id == "org-1"
    assert event.data["installation_id"] == 42
    assert event.data["repos_disabled"] == 3


def test_installation_unsuspended_has_correct_fields() -> None:
    event = ev.installation_unsuspended("org-1", 42, "my-org")
    assert event.event == SSESignal.installation_unsuspended
    assert event.org_id == "org-1"
    assert event.data["installation_id"] == 42
    assert event.data["org_name"] == "my-org"


def test_installation_updated_has_correct_fields() -> None:
    event = ev.installation_updated("org-1", 42, "my-org")
    assert event.event == SSESignal.installation_updated
    assert event.org_id == "org-1"
    assert event.data["installation_id"] == 42
    assert event.data["org_name"] == "my-org"


def test_fix_generation_failed_and_delivery_failed_share_fix_failed_signal() -> None:
    gen_fail = ev.fix_generation_failed("org-1", "repo-1", "fix-1", "timeout")
    del_fail = ev.fix_delivery_failed("org-1", "repo-1", "fix-1", "conflict")
    assert gen_fail.event == SSESignal.fix_failed
    assert del_fail.event == SSESignal.fix_failed


def test_pr_closed_emits_correct_signal_based_on_merged_flag() -> None:
    closed = ev.pr_closed("org-1", "repo-1", "fix-1", "https://pr.url", merged=False)
    merged = ev.pr_closed("org-1", "repo-1", "fix-1", "https://pr.url", merged=True)
    assert closed.event == SSESignal.pr_closed
    assert merged.event == SSESignal.pr_merged


def test_all_sse_signals_are_valid_enum_members() -> None:
    events = [
        ev.analysis_queued("o", "r", "main", "manual"),
        ev.analysis_started("o", "r", "a-1", "main"),
        ev.analysis_completed("o", "r", "a-1", 80.0, "B", 3),
        ev.analysis_failed("o", "r", "a-1", "err"),
        ev.analysis_skipped("o", "r", "a-1"),
        ev.fix_skipped("o", "r"),
        ev.fix_generating("o", "r", ["f-1"], ["i-1"]),
        ev.fix_ready("o", "r", "f-1", ["i-1"]),
        ev.fix_generation_failed("o", "r", "f-1", "err"),
        ev.fix_delivering("o", "r", "f-1"),
        ev.fix_delivering_batch("o", "r", ["f-1"]),
        ev.fix_delivered("o", "r", "f-1", None, "branch"),
        ev.fix_delivered_batch("o", "r", ["f-1"], None, "branch"),
        ev.fix_delivery_failed("o", "r", "f-1", "err"),
        ev.fix_rejected("o", "r", "f-1"),
        ev.pr_opened("o", "r", ["f-1"], "https://url", "branch"),
        ev.pr_updated("o", "r", ["f-1"], "https://url", "branch"),
        ev.pr_closed("o", "r", "f-1", "https://url", merged=False),
        ev.pr_closed("o", "r", "f-1", "https://url", merged=True),
        ev.installation_syncing("o", 1),
        ev.installation_synced("o", 1, 5),
        ev.installation_created("o", 1, "my-org"),
        ev.installation_deleted("o", 1, 2),
        ev.installation_suspended("o", 1, 2),
        ev.installation_unsuspended("o", 1, "my-org"),
        ev.installation_updated("o", 1, "my-org"),
        ev.repository_added("o", 3),
        ev.repository_disabled("o", ["r-1"]),
        ev.repository_toggled("o", "r-1", True),
        ev.repository_action_pr_opened("o", "r-1", "https://url"),
    ]
    for e in events:
        assert isinstance(e.event, SSESignal), f"Not an SSESignal: {e.event!r}"
