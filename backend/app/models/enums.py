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


class ScanFailureKind(str, enum.Enum):
    """Why an analysis ``failed`` — orthogonal to the state itself.

    ``transient`` failures (sweep timeout, OPA/network hiccup) are safe to
    ``retry`` in place; ``permanent`` ones (invalid workflow YAML, a rule bug)
    will fail identically on re-run and need a code/content change first.
    """

    transient = "transient"
    permanent = "permanent"


class ScanTrigger(str, enum.Enum):
    webhook_push = "webhook_push"
    webhook_workflow_run = "webhook_workflow_run"
    # A push detected by polling an external repo's default-branch head (external
    # repos receive no webhooks); the polling analogue of ``webhook_push``.
    polled_push = "polled_push"
    manual = "manual"
    scheduled = "scheduled"
    release = "release"
    # Asked for by a GitHub Actions run over OIDC, to publish the result to
    # Code Scanning. Distinct from ``manual`` because nobody clicked anything,
    # and from ``scheduled`` because it is the repository's own schedule rather
    # than ours — which is what a reader of the scan history needs to know.
    code_scanning = "code_scanning"


class Severity(str, enum.Enum):
    """How bad a rule violation is. Shared by every engine's findings."""

    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Category(str, enum.Enum):
    """Which axis a rule grades on. Also the directory a .rego file lives in."""

    energy = "energy"
    reliability = "reliability"
    security = "security"
    performance = "performance"
    maintainability = "maintainability"
    # NOTE: a "cost" category for IaC/cloud rules is deliberately not added
    # yet. services/scoring.py:compute_category_scores iterates every
    # Category member against a penalties dict that workflow analysis
    # builds with exactly the 5 categories above — adding a 6th here without
    # also updating that function (and deciding whether the *workflow*
    # per-category radar should even show a "Cost" spoke) breaks every
    # repo's grade computation. Add it in the phase that ships a rule
    # actually using it, alongside that fix.


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
    # The rewrite resolved none of the findings it was given: the generator
    # reported every one of them as needing manual work, and what came back is
    # an edit nobody asked for. Delivering it pushed a real regression once
    # (PR #275 flipped `persist-credentials` on a workflow whose own comment
    # said the credential was required), so it is now withheld. Terminal by
    # intent rather than by failure — ``failed`` is regenerable, and retrying a
    # fix the model correctly declined just churns the PR.
    no_op = "no_op"


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
    # WorkflowScan
    analysis_queued = "analysis.queued"
    analysis_started = "analysis.started"
    analysis_completed = "analysis.completed"
    analysis_failed = "analysis.failed"
    analysis_skipped = "analysis.skipped"
    analysis_no_workflows = "analysis.no_workflows"
    # WorkflowFix generation & delivery
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
    # WorkflowScan refused before any work was dispatched because the org's
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
    """Which Rego package a rule lives in, and therefore which document it sees.

    Lets the single ``rule`` table and its admin UI serve every engine without
    one Rule table each.

    **Every member is exactly a directory name under ``app/rules/``**, which is
    what lets ``core/rule_registry`` derive the domain with ``RuleDomain(dir)``.
    That invariant is the whole point: ``workflow`` used to be the odd one out
    against a ``ci_workflow/`` directory, and bridging the two took a
    hand-maintained lookup table that only a comment kept honest.

    Distinct from :class:`Engine`, and deliberately not one-to-one with it:
    ``container_docker`` and ``container_runtime`` rules both produce findings
    on the Docker engine, and ``ci_workflow``/``ci_telemetry`` likewise split
    across the workflow and telemetry engines. See :data:`ENGINE_OF_DOMAIN`.
    """

    ci_workflow = "ci_workflow"
    iac_terraform = "iac_terraform"
    iac_ansible = "iac_ansible"
    cloud_aws = "cloud_aws"
    ci_telemetry = "ci_telemetry"
    container_docker = "container_docker"
    container_runtime = "container_runtime"


class Engine(str, enum.Enum):
    """Which analysis engine produced something.

    The one name for an engine across the whole system: usage records tag
    themselves with it, the dashboard overview keys its stat blocks by it, and
    ``services/engines.EngineSpec`` is looked up by it. There used to be three
    of these enums disagreeing about whether the first one is called ``ci`` or
    ``workflow``; it is ``workflow``, after the ``WorkflowFile`` rows it scans.

    Not the same axis as :class:`RuleDomain`, which names a Rego package — the
    mapping is many-to-one and lives in :data:`ENGINE_OF_DOMAIN`.
    """

    workflow = "workflow"
    terraform = "terraform"
    ansible = "ansible"
    docker = "docker"
    cloud = "cloud"
    telemetry = "telemetry"


ENGINE_OF_DOMAIN: dict[RuleDomain, Engine] = {
    RuleDomain.ci_workflow: Engine.workflow,
    RuleDomain.ci_telemetry: Engine.telemetry,
    RuleDomain.iac_terraform: Engine.terraform,
    RuleDomain.cloud_aws: Engine.cloud,
    RuleDomain.container_docker: Engine.docker,
    # Runtime container rules grade the Docker engine too: a measured OOM kill
    # and a missing memory limit in the Compose file are the same engine's
    # findings, arrived at from different evidence.
    RuleDomain.container_runtime: Engine.docker,
    RuleDomain.iac_ansible: Engine.ansible,
}


class ScanStatus(str, enum.Enum):
    """Lifecycle of one engine's run over one target.

    Shared by every scan table. There used to be a second, identical enum called
    ``ScanStatus`` for the CI engine alone, differing in exactly one member:
    it spelled the empty case ``no_workflows`` where this one says
    ``no_targets``. That is workflow-specific vocabulary for a case every engine
    has — no ``.tf`` files under this root, no resources of the scanned types in
    this account, no workflow files in this repository — so the general name
    won and migration 0053 rewrote the rows.
    """

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    no_targets = "no_targets"


class FindingStatus(str, enum.Enum):
    """Derived lifecycle of a rule violation, on any engine.

    For CI-workflow findings this column is computed by a database trigger from
    ``ignored_at``, ``resolved_at`` and ``fix_id`` (migrations ``0022``/``0026``,
    renamed in ``0053``); ``ignored`` takes precedence, so a user-dismissed
    violation stays muted regardless of fix or resolve activity. The other
    engines set it directly through ``FindingMachine``.

    ``fix_in_progress`` arrived with the merge of the old ``FindingStatus``: only
    the CI engine reaches it today, because only its findings carry a ``fix_id``
    — the other engines key a fix on ``(target, file_path)`` instead. It is
    declared here rather than in a CI-only enum because the state is about the
    finding, not about which engine found it.
    """

    open = "open"
    fix_in_progress = "fix_in_progress"
    resolved = "resolved"
    ignored = "ignored"


class FindingResolutionReason(str, enum.Enum):
    """Why a finding stopped being open.

    An attribute of the ``resolved`` state, not a state of its own. The union of
    what the engines can observe: the first two are available to all of them,
    the rest need a file or a pull request and so only arise on engines that
    have one.
    """

    # The violation is simply no longer reported — the user fixed it, or its
    # rule was disabled or withdrawn. Indistinguishable from here, and both
    # mean the same thing to a reader of the finding.
    no_longer_detected = "no_longer_detected"
    # The whole target went away (root deleted, account disconnected).
    target_removed = "target_removed"
    # The file the violation was in no longer exists.
    file_removed = "file_removed"
    # A fix PR carrying this finding was merged.
    merged = "merged"
    # The branch the finding was observed on was deleted.
    branch_deleted = "branch_deleted"


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
    """Which engine produced a usage record, plus one non-engine sentinel.

    Every one of these debits the same shared pool; the tag exists so a user
    can see *where* their allowance went, and so tests can assert that each
    engine is actually metered.

    Its engine members are :class:`Engine`'s, spelled out rather than generated
    so the persisted values stay greppable — ``_ENGINE_MEMBERS_MATCH`` below
    fails at import if the two ever drift.
    """

    workflow = "workflow"
    terraform = "terraform"
    ansible = "ansible"
    docker = "docker"
    cloud = "cloud"
    telemetry = "telemetry"
    # Not produced by an engine: the one-off record the ledger migration writes
    # to carry a subscription's pre-ledger fix usage into its current period.
    carryover = "carryover"

    @classmethod
    def of(cls, engine: Engine) -> "UsageEngine":
        """The usage tag for an engine. Total, given the check below."""
        return cls(engine.value)


# A usage record tagged with an engine the rest of the system does not know
# about is unattributable, and the reverse is a meter that silently bills
# nothing. Catch either at import rather than in a billing report.
_ENGINE_MEMBERS_MATCH = {e.value for e in Engine} == {u.value for u in UsageEngine} - {
    UsageEngine.carryover.value
}
assert _ENGINE_MEMBERS_MATCH, "UsageEngine and Engine have drifted apart"


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


class OverviewSection(str, enum.Enum):
    """Which collapsible dashboard section an engine renders under.

    Four engines, three sections: the Infrastructure page already shows
    Terraform and cloud posture as sibling tabs, so the dashboard groups them
    the same way rather than inventing a fourth top-level heading.
    """

    ci = "ci"
    docker = "docker"
    infra = "infra"
