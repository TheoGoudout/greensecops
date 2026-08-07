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


class AnalysisFailureKind(str, enum.Enum):
    """Why an analysis ``failed`` — orthogonal to the state itself.

    ``transient`` failures (sweep timeout, OPA/network hiccup) are safe to
    ``retry`` in place; ``permanent`` ones (invalid workflow YAML, a rule bug)
    will fail identically on re-run and need a code/content change first.
    """

    transient = "transient"
    permanent = "permanent"


class AnalysisTrigger(str, enum.Enum):
    webhook_push = "webhook_push"
    webhook_workflow_run = "webhook_workflow_run"
    # A push detected by polling an external repo's default-branch head (external
    # repos receive no webhooks); the polling analogue of ``webhook_push``.
    polled_push = "polled_push"
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
    # NOTE: a "cost" category for IaC/cloud rules is deliberately not added
    # yet. services/scoring.py:compute_category_scores iterates every
    # IssueCategory member against a penalties dict that workflow analysis
    # builds with exactly the 5 categories above — adding a 6th here without
    # also updating that function (and deciding whether the *workflow*
    # per-category radar should even show a "Cost" spoke) breaks every
    # repo's grade computation. Add it in the phase that ships a rule
    # actually using it, alongside that fix.


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


class IssueResolutionReason(str, enum.Enum):
    """Why an issue was resolved — an attribute of the ``resolved`` state.

    Kept as a column rather than splitting ``resolved`` into several states so
    the issue graph stays small. Set alongside ``resolved_at`` and cleared when
    a resolved violation recurs.

    - ``no_longer_detected``: absent from the latest analysis (a manual fix or a
      disabled/removed rule — the two cannot be told apart after the fact).
    - ``file_removed``: the workflow file was deleted or renamed.
    - ``merged``: the fix PR was merged, applying the change to the branch.
    - ``branch_deleted``: the branch carrying the issue's workflow file was
      deleted; the violation no longer exists anywhere to fix.
    """

    no_longer_detected = "no_longer_detected"
    file_removed = "file_removed"
    merged = "merged"
    branch_deleted = "branch_deleted"


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
    # The workflow file this fix targets was deleted from the repo; it becomes
    # deliverable again (``restore``) if a later push re-adds the same path.
    superseded_by_deleted_file = "superseded_by_deleted_file"
    # Terminal: the fix's PR was merged, so its change is on the branch. Distinct
    # from ``delivered`` (awaiting review) — set from the pull_request merge
    # webhook, and it resolves the fix's issues with reason ``merged``.
    landed = "landed"


class PullRequestState(str, enum.Enum):
    open = "open"
    # A GitHub draft PR (opened as draft or via ``converted_to_draft``); returns
    # to ``open`` on ``ready_for_review``. CI / review / mergeable detail is kept
    # as attributes on the row, not as extra states.
    draft = "draft"
    merged = "merged"
    closed = "closed"


class CIStatus(str, enum.Enum):
    """Aggregate CI outcome for a PR, from ``check_suite`` webhooks."""

    pending = "pending"
    success = "success"
    failure = "failure"
    none = "none"


class ReviewDecision(str, enum.Enum):
    """Latest human review decision for a PR, from ``pull_request_review``."""

    approved = "approved"
    changes_requested = "changes_requested"
    review_required = "review_required"


class TelemetryPhase(str, enum.Enum):
    started = "started"
    completed = "completed"


class DynamicAnalysisStatus(str, enum.Enum):
    """Lifecycle of the dynamic-analysis enrichment for a ``completed``-phase
    telemetry run.

    Distinct from ``TelemetryPhase`` (an ingest category — ``started`` and
    ``completed`` are separate rows): this tracks the worker that turns a
    completed run's metrics into persisted ``DynamicEnrichment`` findings.
    """

    queued = "queued"
    running = "running"
    enriched = "enriched"
    failed = "failed"


class RepositoryStatus(str, enum.Enum):
    """Accessibility / lifecycle of a repository as GreenSecOps sees it.

    Drives the ``is_accessible`` gate (``active`` ⇒ accessible). Orthogonal to
    ``Repository.enabled`` (user opt-in) and ``is_external``, which stay plain
    flags. Toggled by installation/repository webhooks.
    """

    active = "active"
    suspended = "suspended"  # installation suspended
    archived = "archived"  # repo archived on GitHub
    inaccessible = "inaccessible"  # installation deleted or repo removed from it


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
    fix_landed = "fix.landed"
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
    repository_suspended = "repository.suspended"
    repository_archived = "repository.archived"
    repository_inaccessible = "repository.inaccessible"
    repository_restored = "repository.restored"
    # Dynamic analysis (telemetry enrichment)
    dynamic_queued = "dynamic.queued"
    dynamic_running = "dynamic.running"
    dynamic_enriched = "dynamic.enriched"
    dynamic_failed = "dynamic.failed"
    # Analysis refused before any work was dispatched because the org's
    # billing owner has no metered allowance left. Distinct from
    # ``analysis_failed``: nothing broke, and a retry will not help.
    analysis_quota_exceeded = "analysis.quota_exceeded"
    # Billing lifecycle. The UI listens for these to refresh the billing page
    # and raise/lower the past-due banner without polling.
    subscription_activated = "subscription.activated"
    subscription_past_due = "subscription.past_due"
    subscription_unpaid = "subscription.unpaid"
    subscription_canceled = "subscription.canceled"
    subscription_updated = "subscription.updated"


class RuleDomain(str, enum.Enum):
    """Which analysis engine a Rule belongs to.

    Lets the single ``rule`` table and its admin UI serve the CI-workflow
    engine and the new IaC/cloud engines without three parallel Rule tables.
    Existing rows default to ``workflow`` (see migration 0042).
    """

    workflow = "workflow"
    iac_terraform = "iac_terraform"
    cloud_aws = "cloud_aws"
    ci_telemetry = "ci_telemetry"
    container_docker = "container_docker"
    container_runtime = "container_runtime"


class ScanStatus(str, enum.Enum):
    """Lifecycle of a TerraformScan or CloudScan.

    Deliberately separate from ``AnalysisStatus``: that enum's ``no_workflows``
    value is workflow-specific vocabulary. ``no_targets`` covers both "no .tf
    files under this root" and "no resources of the scanned types in this
    account/region".
    """

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    no_targets = "no_targets"


class FindingStatus(str, enum.Enum):
    """Lifecycle of a TerraformFinding or CloudFinding.

    Unlike ``Issue.status`` (owned by a DB trigger reacting to ``fix_id``),
    findings in this delivery have no fix/PR concept yet (see plan Phase 7),
    so the application sets this column directly alongside resolved_at/
    ignored_at rather than needing trigger-derived state.
    """

    open = "open"
    resolved = "resolved"
    ignored = "ignored"


class FindingResolutionReason(str, enum.Enum):
    no_longer_detected = "no_longer_detected"
    # The Terraform file/resource block was removed, or the cloud resource no
    # longer exists on the provider side.
    target_removed = "target_removed"


class CloudProvider(str, enum.Enum):
    aws = "aws"


class CloudAccountStatus(str, enum.Enum):
    pending_verification = "pending_verification"
    connected = "connected"
    error = "error"
    disabled = "disabled"


class SubscriptionStatus(str, enum.Enum):
    """Lifecycle of a ``BillingSubscription`` — see ``BillingSubscriptionMachine``.

    Orthogonal to ``UserTier``: the tier says *what was bought*, this says
    *whether it is currently being paid for*. The combination is resolved by
    ``services/billing/lifecycle.effective_tier``, which is the only thing
    quota enforcement reads.

    ``past_due`` deliberately keeps full paid service — it is the grace window,
    not a punishment. Only ``unpaid`` (grace expired) and ``canceled`` fall
    back to Free limits, and neither ever removes data.
    """

    # Checkout started but never paid. A subscription is born here only when it
    # came from Checkout; accounts that never bought anything sit in ``active``
    # on the free tier, because there is nothing to collect.
    incomplete = "incomplete"
    trialing = "trialing"
    active = "active"
    # Payment failed; inside the grace window. Full service continues.
    past_due = "past_due"
    # Grace window expired. Free limits until payment succeeds.
    unpaid = "unpaid"
    # Cancelled, but paid through the end of the current period.
    pending_cancellation = "pending_cancellation"
    canceled = "canceled"


class UsageMeter(str, enum.Enum):
    """Which allowance a usage record draws down.

    ``repos`` is absent on purpose: it is a live capacity count (how many
    repositories are enabled right now), not something consumed over time, so
    it is measured by querying rather than by ledger entries.
    """

    analyses = "analyses"
    fixes = "fixes"


class UsageEngine(str, enum.Enum):
    """Which engine produced a usage record.

    Every one of these debits the same shared pool; the tag exists so a user
    can see *where* their allowance went, and so tests can assert that each
    engine is actually metered.
    """

    workflow = "workflow"
    terraform = "terraform"
    docker = "docker"
    cloud = "cloud"
    telemetry = "telemetry"
    # Not produced by an engine: the one-off record the ledger migration writes
    # to carry a subscription's pre-ledger fix usage into its current period.
    carryover = "carryover"


class InvoiceStatus(str, enum.Enum):
    """Mirrors Stripe's invoice statuses, minus ``deleted`` (drafts only)."""

    draft = "draft"
    open = "open"
    paid = "paid"
    void = "void"
    uncollectible = "uncollectible"


class OssApplicationStatus(str, enum.Enum):
    """Review state of a request for the granted open-source plan."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"


class OverviewEngineKey(str, enum.Enum):
    """Which analysis engine a block of dashboard overview stats describes.

    A presentation-layer key, not a persisted column — ``Rule.domain`` stays
    the DB-level discriminator. The two exist because they don't line up:
    ``container_docker`` and ``container_runtime`` rules both produce findings
    on the Docker engine, so one key covers two domains.
    """

    ci = "ci"
    docker = "docker"
    terraform = "terraform"
    cloud = "cloud"


class OverviewSection(str, enum.Enum):
    """Which collapsible dashboard section an engine renders under.

    Four engines, three sections: the Infrastructure page already shows
    Terraform and cloud posture as sibling tabs, so the dashboard groups them
    the same way rather than inventing a fourth top-level heading.
    """

    ci = "ci"
    docker = "docker"
    infra = "infra"
