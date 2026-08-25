"""Unit tests for fix_generation helpers."""

import uuid
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session

from app.models import (
    Category,
    FixStatus,
    LLMProvider,
    Organization,
    PullRequest,
    Repository,
    Rule,
    ScanStatus,
    ScanTrigger,
    Severity,
    UserTier,
    WorkflowFile,
    WorkflowFinding,
    WorkflowFix,
    WorkflowScan,
)
from app.services.llm.response import (
    parse_full_content,
    parse_unfixed_issues,
    restore_trailing_whitespace,
)
from app.workers.tasks.fix_generation import (
    _is_valid_workflow_yaml,
    _maybe_auto_deliver,
    _record_batch_result,
    init_fix_batch,
    resolve_llm_provider,
)

_FULL_CONTENT = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"

_WORKFLOW = (
    "name: CI\n"
    "on: push\n"
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
)


# ─── parse_full_content ─────────────────────────────────────────────────────


def test_parse_llm_response_extracts_full_content() -> None:
    response = f"<full_content>\n{_WORKFLOW}</full_content>"
    assert parse_full_content(response) == _WORKFLOW


def test_parse_llm_response_missing_block_returns_empty() -> None:
    assert parse_full_content("no delimiters here") == ""


def test_parse_llm_response_ignores_surrounding_prose() -> None:
    response = (
        "Here is the fixed workflow:\n"
        "<full_content>\nname: CI\non: push\n</full_content>\n"
        "All issues addressed."
    )
    assert parse_full_content(response) == "name: CI\non: push\n"


# ─── parse_unfixed_issues ───────────────────────────────────────────────────


def test_parse_unfixed_issues_extracts_index_and_reason() -> None:
    response = (
        f"<full_content>\n{_WORKFLOW}</full_content>\n"
        "<unfixed>\n2: requires manual OIDC trust setup in AWS IAM\n</unfixed>"
    )
    assert parse_unfixed_issues(response) == {
        2: "requires manual OIDC trust setup in AWS IAM"
    }


def test_parse_unfixed_issues_multiple_entries() -> None:
    response = (
        "<unfixed>\n1: needs a repo secret\n3: cross-file refactor needed\n</unfixed>"
    )
    assert parse_unfixed_issues(response) == {
        1: "needs a repo secret",
        3: "cross-file refactor needed",
    }


def test_parse_unfixed_issues_missing_block_returns_empty() -> None:
    response = f"<full_content>\n{_WORKFLOW}</full_content>"
    assert parse_unfixed_issues(response) == {}


def test_parse_unfixed_issues_empty_block_returns_empty() -> None:
    response = f"<full_content>\n{_WORKFLOW}</full_content>\n<unfixed>\n</unfixed>"
    assert parse_unfixed_issues(response) == {}


# ─── _is_valid_workflow_yaml ─────────────────────────────────────────────────


def test_valid_workflow_yaml_accepted() -> None:
    assert _is_valid_workflow_yaml(_WORKFLOW) is True


def test_invalid_yaml_rejected() -> None:
    assert _is_valid_workflow_yaml("{ invalid: yaml: [}") is False


def test_non_mapping_yaml_rejected() -> None:
    assert _is_valid_workflow_yaml("- just\n- a\n- list\n") is False


# ─── restore_trailing_whitespace ─────────────────────────────────────────────


def test_restore_trailing_whitespace_restores_stripped_space() -> None:
    original = "hello   \nworld"
    patched = "hello\nworld"
    result = restore_trailing_whitespace(original, patched)
    assert result == "hello   \nworld"


def test_restore_trailing_whitespace_keeps_new_content() -> None:
    # When stripped content differs, keep the new line
    original = "hello\nworld"
    patched = "hello\nuniverse"
    result = restore_trailing_whitespace(original, patched)
    assert result == "hello\nuniverse"


def test_restore_trailing_whitespace_no_change_needed() -> None:
    original = "a\nb\nc"
    patched = "a\nb\nc"
    result = restore_trailing_whitespace(original, patched)
    assert result == "a\nb\nc"


def test_restore_trailing_whitespace_new_lines_beyond_original() -> None:
    # Extra lines in patched that have no corresponding original line are kept as-is
    original = "a"
    patched = "a\nb\nc"
    result = restore_trailing_whitespace(original, patched)
    assert result == "a\nb\nc"


def test_restore_trailing_whitespace_tab_trailing() -> None:
    original = "line\t\nend"
    patched = "line\nend"
    result = restore_trailing_whitespace(original, patched)
    assert result == "line\t\nend"


# ─── resolve_llm_provider ────────────────────────────────────────────────────


def test_resolve_llm_provider_uses_provider_default_model() -> None:
    # A repo pinned to anthropic without a model must NOT fall back to an
    # OpenAI model name.
    repo = SimpleNamespace(
        llm_provider=LLMProvider.anthropic,
        llm_model=None,
        organization=None,
    )
    provider, model = resolve_llm_provider(repo)
    assert provider == "anthropic"
    assert "gpt" not in model


# ─── batch coordination ──────────────────────────────────────────────────────


class _FakeRedis:
    """Minimal in-memory stand-in for the sync redis client."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def set(self, key: str, value: object, ex: int | None = None) -> None:
        self.store[key] = str(value)

    def get(self, key: str) -> str | None:
        return self.store.get(key)  # type: ignore[return-value]

    def sadd(self, key: str, *values: str) -> None:
        self.store.setdefault(key, set()).update(values)  # type: ignore[union-attr]

    def smembers(self, key: str) -> "set[str]":
        return self.store.get(key) or set()  # type: ignore[return-value]

    def expire(self, key: str, ttl: int) -> None:
        pass

    def decr(self, key: str) -> int:
        value = int(self.store.get(key, 0)) - 1  # type: ignore[arg-type]
        self.store[key] = str(value)
        return value

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)

    def close(self) -> None:
        pass


def test_batch_publishes_single_event_pair_when_last_task_ends() -> None:
    fake = _FakeRedis()
    with (
        patch("redis.from_url", return_value=fake),
        patch(
            "app.workers.tasks.fix_generation.events_pub.publish_event"
        ) as mock_publish,
    ):
        init_fix_batch("b1", 2)
        _record_batch_result("b1", "org", "repo", ["f1"], [], None)
        assert mock_publish.call_count == 0

        _record_batch_result("b1", "org", "repo", ["f2"], ["f3"], "boom")

    events = [call.args[0] for call in mock_publish.call_args_list]
    ready = [e for e in events if "error" not in e.data]
    failed = [e for e in events if "error" in e.data]
    assert len(ready) == 1
    assert set(ready[0].data["fix_ids"]) == {"f1", "f2"}
    assert len(failed) == 1
    assert failed[0].data["fix_ids"] == ["f3"]
    assert failed[0].data["error"] == "boom"


def test_batch_publishes_no_failed_event_when_all_ready() -> None:
    fake = _FakeRedis()
    with (
        patch("redis.from_url", return_value=fake),
        patch(
            "app.workers.tasks.fix_generation.events_pub.publish_event"
        ) as mock_publish,
    ):
        init_fix_batch("b2", 1)
        _record_batch_result("b2", "org", "repo", ["f1", "f2"], [], None)

    events = [call.args[0] for call in mock_publish.call_args_list]
    assert len(events) == 1
    assert set(events[0].data["fix_ids"]) == {"f1", "f2"}


def test_batch_fails_open_when_redis_unavailable() -> None:
    with (
        patch("redis.from_url", side_effect=RuntimeError("redis down")),
        patch(
            "app.workers.tasks.fix_generation.events_pub.publish_event"
        ) as mock_publish,
    ):
        _record_batch_result("b3", "org", "repo", ["f1"], ["f2"], "err")

    events = [call.args[0] for call in mock_publish.call_args_list]
    assert len(events) == 2
    ready = next(e for e in events if "error" not in e.data)
    failed = next(e for e in events if "error" in e.data)
    assert ready.data["fix_ids"] == ["f1"]
    assert failed.data["fix_ids"] == ["f2"]


# ─── _maybe_auto_deliver ─────────────────────────────────────────────────────


def _make_wf_fix_issue(
    db: Session, repo: Repository, rule: Rule, status: FixStatus, n: int
) -> tuple[WorkflowFile, WorkflowFix, WorkflowFinding]:
    wf = WorkflowFile(
        repo_id=repo.id,
        path=f".github/workflows/auto-deliver-{n}-{uuid.uuid4().hex[:6]}.yml",
        content_hash=uuid.uuid4().hex,
        raw_content="on: push\njobs: {}",
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    fix = WorkflowFix(
        workflow_file_id=wf.id,
        llm_provider=LLMProvider.openai,
        llm_model="gpt-4o-mini",
        status=status,
        full_content=_FULL_CONTENT if status == FixStatus.ready else None,
    )
    db.add(fix)
    db.commit()
    db.refresh(fix)
    analysis = WorkflowScan(
        repo_id=repo.id,
        workflow_file_id=wf.id,
        content_hash=wf.content_hash,
        status=ScanStatus.completed,
        triggered_by=ScanTrigger.manual,
        branch="main",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    issue = WorkflowFinding(
        analysis_id=analysis.id,
        workflow_file_id=wf.id,
        rule_id=rule.id,
        fingerprint=uuid.uuid4().hex[:16],
        severity=Severity.medium,
        category=Category.reliability,
        message=f"auto-deliver issue {n}",
        fix_id=fix.id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return wf, fix, issue


def test_maybe_auto_deliver_body_keeps_previously_delivered_fixes(
    db: Session,
) -> None:
    # Regression: same bug as the manual delivery routes, in the auto-fix
    # path — a sibling workflow's fix already `delivered` onto a shared PR
    # must not be dropped from the body when only a new fix is `ready`.
    org = Organization(
        name=f"auto-deliver-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"autodeliver/repo-{uuid.uuid4().hex[:8]}",
        installation_id=99992,
        auto_fix_enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    rule = Rule(
        slug=f"auto-deliver-rule-{uuid.uuid4().hex[:8]}",
        category=Category.reliability,
        severity=Severity.medium,
        title="Auto Deliver Rule",
        description="A test rule",
        enabled=True,
        severity_weight=1.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/fixes-{str(repo.id)[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/135",
        pr_state="open",
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    _delivered_wf, delivered_fix, delivered_issue = _make_wf_fix_issue(
        db, repo, rule, FixStatus.delivered, 1
    )
    delivered_fix.pr_id = pr.id
    db.add(delivered_fix)
    db.commit()

    _ready_wf, ready_fix, ready_issue = _make_wf_fix_issue(
        db, repo, rule, FixStatus.ready, 2
    )

    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        _maybe_auto_deliver(str(repo.id), [str(ready_fix.id)])

    mock_delay.assert_called_once()
    call_kwargs = mock_delay.call_args.kwargs
    # Only the ready fix is actually delivered...
    assert call_kwargs["fix_ids"] == [str(ready_fix.id)]
    # ...but the body still reflects the sibling's already-delivered issue.
    assert delivered_issue.message in call_kwargs["pr_body"]
    assert ready_issue.message in call_kwargs["pr_body"]


def test_maybe_auto_deliver_skips_externally_modified_pr(db: Session) -> None:
    org = Organization(
        name=f"auto-deliver-org-{uuid.uuid4().hex[:8]}", tier=UserTier.free
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    repo = Repository(
        org_id=org.id,
        github_repo_id=int(uuid.uuid4().int % 10**9),
        full_name=f"autodeliver/repo-{uuid.uuid4().hex[:8]}",
        installation_id=99993,
        auto_fix_enabled=True,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    rule = Rule(
        slug=f"auto-deliver-rule-{uuid.uuid4().hex[:8]}",
        category=Category.reliability,
        severity=Severity.medium,
        title="Auto Deliver Rule",
        description="A test rule",
        enabled=True,
        severity_weight=1.0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    pr = PullRequest(
        repo_id=repo.id,
        pr_branch=f"greensecops/fixes-{str(repo.id)[:8]}",
        pr_url=f"https://github.com/{repo.full_name}/pull/136",
        pr_state="open",
        externally_modified=True,
    )
    db.add(pr)
    db.commit()

    _wf, ready_fix, _issue = _make_wf_fix_issue(db, repo, rule, FixStatus.ready, 1)

    with patch(
        "app.workers.tasks.fix_delivery.deliver_fixes_batch.delay"
    ) as mock_delay:
        _maybe_auto_deliver(str(repo.id), [str(ready_fix.id)])

    # The user's commits on the fix branch block auto-redelivery.
    mock_delay.assert_not_called()
