import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SSEEvent:
    event: str
    org_id: str  # routing key — published to events:org:{org_id}
    data: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> str:
        """Serialize to SSE wire format."""
        payload = {"event": self.event, **self.data}
        return f"data: {json.dumps(payload)}\n\n"


# ─── Analysis ────────────────────────────────────────────────────────────────


def analysis_queued(org_id: str, repo_id: str, branch: str, trigger: str) -> SSEEvent:
    return SSEEvent(
        event="analysis.queued",
        org_id=org_id,
        data={"repo_id": repo_id, "branch": branch, "trigger": trigger},
    )


def analysis_started(
    org_id: str, repo_id: str, analysis_id: str, branch: str
) -> SSEEvent:
    return SSEEvent(
        event="analysis.started",
        org_id=org_id,
        data={"repo_id": repo_id, "analysis_id": analysis_id, "branch": branch},
    )


def analysis_completed(
    org_id: str,
    repo_id: str,
    analysis_id: str,
    score: float,
    grade: str,
    issues_count: int,
) -> SSEEvent:
    return SSEEvent(
        event="analysis.completed",
        org_id=org_id,
        data={
            "repo_id": repo_id,
            "analysis_id": analysis_id,
            "score": score,
            "grade": grade,
            "issues_count": issues_count,
        },
    )


def analysis_failed(
    org_id: str, repo_id: str, analysis_id: str, error: str
) -> SSEEvent:
    return SSEEvent(
        event="analysis.failed",
        org_id=org_id,
        data={"repo_id": repo_id, "analysis_id": analysis_id, "error": error},
    )


def analysis_skipped(org_id: str, repo_id: str, analysis_id: str) -> SSEEvent:
    return SSEEvent(
        event="analysis.skipped",
        org_id=org_id,
        data={"repo_id": repo_id, "analysis_id": analysis_id},
    )


# ─── Fix generation ──────────────────────────────────────────────────────────


def fix_generating(
    org_id: str, repo_id: str, fix_ids: list[str], issue_ids: list[str]
) -> SSEEvent:
    return SSEEvent(
        event="fix.generating",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_ids": fix_ids, "issue_ids": issue_ids},
    )


def fix_ready(org_id: str, repo_id: str, fix_id: str, issue_id: str) -> SSEEvent:
    return SSEEvent(
        event="fix.ready",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_id": fix_id, "issue_id": issue_id},
    )


def fix_ready_batch(org_id: str, repo_id: str, fix_ids: list[str]) -> SSEEvent:
    return SSEEvent(
        event="fix.ready",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_ids": fix_ids},
    )


def fix_generation_failed(
    org_id: str, repo_id: str, fix_id: str, error: str
) -> SSEEvent:
    return SSEEvent(
        event="fix.failed",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_id": fix_id, "error": error},
    )


# ─── Fix delivery ────────────────────────────────────────────────────────────


def fix_delivering(org_id: str, repo_id: str, fix_id: str) -> SSEEvent:
    return SSEEvent(
        event="fix.delivering",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_id": fix_id},
    )


def fix_delivering_batch(org_id: str, repo_id: str, fix_ids: list[str]) -> SSEEvent:
    return SSEEvent(
        event="fix.delivering",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_ids": fix_ids},
    )


def fix_delivered(
    org_id: str, repo_id: str, fix_id: str, pr_url: str | None, pr_branch: str
) -> SSEEvent:
    return SSEEvent(
        event="fix.delivered",
        org_id=org_id,
        data={
            "repo_id": repo_id,
            "fix_id": fix_id,
            "pr_url": pr_url,
            "pr_branch": pr_branch,
        },
    )


def fix_delivered_batch(
    org_id: str, repo_id: str, fix_ids: list[str], pr_url: str | None, pr_branch: str
) -> SSEEvent:
    return SSEEvent(
        event="fix.delivered",
        org_id=org_id,
        data={
            "repo_id": repo_id,
            "fix_ids": fix_ids,
            "pr_url": pr_url,
            "pr_branch": pr_branch,
        },
    )


def fix_delivery_failed(org_id: str, repo_id: str, fix_id: str, error: str) -> SSEEvent:
    return SSEEvent(
        event="fix.failed",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_id": fix_id, "error": error},
    )


def fix_rejected(org_id: str, repo_id: str, fix_id: str) -> SSEEvent:
    return SSEEvent(
        event="fix.rejected",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_id": fix_id},
    )


# ─── PR ──────────────────────────────────────────────────────────────────────


def pr_opened(
    org_id: str, repo_id: str, fix_ids: list[str], pr_url: str, pr_branch: str
) -> SSEEvent:
    return SSEEvent(
        event="pr.opened",
        org_id=org_id,
        data={
            "repo_id": repo_id,
            "fix_ids": fix_ids,
            "pr_url": pr_url,
            "pr_branch": pr_branch,
        },
    )


def pr_updated(
    org_id: str, repo_id: str, fix_ids: list[str], pr_url: str, pr_branch: str
) -> SSEEvent:
    return SSEEvent(
        event="pr.updated",
        org_id=org_id,
        data={
            "repo_id": repo_id,
            "fix_ids": fix_ids,
            "pr_url": pr_url,
            "pr_branch": pr_branch,
        },
    )


def pr_closed(
    org_id: str, repo_id: str, fix_id: str, pr_url: str, merged: bool
) -> SSEEvent:
    return SSEEvent(
        event="pr.merged" if merged else "pr.closed",
        org_id=org_id,
        data={"repo_id": repo_id, "fix_id": fix_id, "pr_url": pr_url},
    )


# ─── Installation ────────────────────────────────────────────────────────────


def installation_syncing(org_id: str, installation_id: int) -> SSEEvent:
    return SSEEvent(
        event="installation.syncing",
        org_id=org_id,
        data={"org_id": org_id, "installation_id": installation_id},
    )


def installation_synced(org_id: str, installation_id: int, repo_count: int) -> SSEEvent:
    return SSEEvent(
        event="installation.synced",
        org_id=org_id,
        data={
            "org_id": org_id,
            "installation_id": installation_id,
            "repo_count": repo_count,
        },
    )


def installation_created(org_id: str, installation_id: int, org_name: str) -> SSEEvent:
    return SSEEvent(
        event="installation.created",
        org_id=org_id,
        data={
            "org_id": org_id,
            "installation_id": installation_id,
            "org_name": org_name,
        },
    )


def installation_deleted(
    org_id: str, installation_id: int, repos_disabled: int
) -> SSEEvent:
    return SSEEvent(
        event="installation.deleted",
        org_id=org_id,
        data={
            "org_id": org_id,
            "installation_id": installation_id,
            "repos_disabled": repos_disabled,
        },
    )


def repository_added(org_id: str, repo_count: int) -> SSEEvent:
    return SSEEvent(
        event="repository.added",
        org_id=org_id,
        data={"org_id": org_id, "repo_count": repo_count},
    )


def repository_disabled(org_id: str, repo_ids: list[str]) -> SSEEvent:
    return SSEEvent(
        event="repository.disabled",
        org_id=org_id,
        data={"org_id": org_id, "repo_ids": repo_ids},
    )


def repository_toggled(org_id: str, repo_id: str, enabled: bool) -> SSEEvent:
    return SSEEvent(
        event="repository.toggled",
        org_id=org_id,
        data={"org_id": org_id, "repo_id": repo_id, "enabled": enabled},
    )


def repository_action_pr_opened(org_id: str, repo_id: str, pr_url: str) -> SSEEvent:
    return SSEEvent(
        event="repository.action_pr_opened",
        org_id=org_id,
        data={"org_id": org_id, "repo_id": repo_id, "pr_url": pr_url},
    )
