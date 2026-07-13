import enum


class UserTier(str, enum.Enum):
    free = "free"
    starter = "starter"
    pro = "pro"
    ultimate = "ultimate"
    open_source = "open_source"


class OrgRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class FixDeliveryMode(str, enum.Enum):
    pr = "pr"
    comment = "comment"
    disabled = "disabled"


class LLMProvider(str, enum.Enum):
    openai = "openai"
    anthropic = "anthropic"
    gemini = "gemini"
    ollama = "ollama"


class AnalysisStatus(str, enum.Enum):
    # An analysis row is created as ``queued`` (or directly ``no_workflows``)
    # and advances to ``running`` when the worker begins OPA evaluation. The
    # broker-queue phase before the worker picks the task up is still signalled
    # over SSE without a row. Content-hash duplicates reference the prior
    # analysis and emit ``analysis.skipped`` without writing a row. A
    # ``skipped`` row is never persisted, so that value is not a machine state.
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    no_workflows = "no_workflows"


class AnalysisTrigger(str, enum.Enum):
    webhook_push = "webhook_push"
    webhook_workflow_run = "webhook_workflow_run"
    manual = "manual"
    scheduled = "scheduled"
    release = "release"


class IssueSeverity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class IssueCategory(str, enum.Enum):
    energy = "energy"
    reliability = "reliability"
    security = "security"
    performance = "performance"
    maintainability = "maintainability"


class IssueStatus(str, enum.Enum):
    """Derived lifecycle of an issue.

    This value is a persisted column computed by a database trigger from
    ``ignored_at``, ``resolved_at`` and ``fix_id`` (see ``Issue.status`` and
    migrations ``0022``/``0026``). ``ignored`` takes precedence over the other
    states so a user-dismissed violation stays muted regardless of fix/resolve
    activity.
    """

    open = "open"
    fix_in_progress = "fix_in_progress"
    resolved = "resolved"
    ignored = "ignored"


class FixStatus(str, enum.Enum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    delivering = "delivering"
    delivered = "delivered"
    failed = "failed"
    # Two distinct rejections (previously a single overloaded ``rejected``):
    #  - ``rejected_by_user``:  a human dismissed the fix via the API.
    #  - ``superseded_by_closed_pr``: the closed-PR delivery guard auto-rejected
    #    it; it becomes deliverable again if that PR is reopened.
    rejected_by_user = "rejected_by_user"
    superseded_by_closed_pr = "superseded_by_closed_pr"


class PullRequestState(str, enum.Enum):
    open = "open"
    merged = "merged"
    closed = "closed"


class TelemetryPhase(str, enum.Enum):
    started = "started"
    completed = "completed"


class SSESignal(str, enum.Enum):
    # Analysis
    analysis_queued = "analysis.queued"
    analysis_started = "analysis.started"
    analysis_completed = "analysis.completed"
    analysis_failed = "analysis.failed"
    analysis_skipped = "analysis.skipped"
    analysis_no_workflows = "analysis.no_workflows"
    # Fix generation & delivery
    fix_skipped = "fix.skipped"
    fix_pending = "fix.pending"
    fix_generating = "fix.generating"
    fix_ready = "fix.ready"
    fix_delivering = "fix.delivering"
    fix_delivered = "fix.delivered"
    fix_failed = "fix.failed"
    fix_rejected = "fix.rejected"
    # Pull requests
    pr_opened = "pr.opened"
    pr_updated = "pr.updated"
    pr_closed = "pr.closed"
    pr_merged = "pr.merged"
    # Installation lifecycle
    installation_syncing = "installation.syncing"
    installation_synced = "installation.synced"
    installation_created = "installation.created"
    installation_deleted = "installation.deleted"
    installation_suspended = "installation.suspended"
    installation_unsuspended = "installation.unsuspended"
    installation_updated = "installation.updated"
    # Repository
    repository_added = "repository.added"
    repository_disabled = "repository.disabled"
    repository_toggled = "repository.toggled"
    repository_action_pr_opened = "repository.action_pr_opened"
