"""The wire shape of a server-sent event."""

from sqlmodel import SQLModel

from ..enums import (
    SSESignal,
)


class SSEEventPublic(SQLModel):
    """The wire shape of one server-sent event.

    Every event is a flat JSON object: an ``event`` discriminant plus whatever
    the emitting factory in ``services/events/schemas.py`` put beside it. That
    payload was a bare ``dict[str, Any]`` and never reached OpenAPI, so the
    frontend read it by hand — ``data.grade as string | undefined``, forty times
    over in ``hooks/useRepoEvents.ts``. A renamed field broke silently at
    runtime, in a browser, with nothing to catch it.

    Declaring it here puts the field names in the generated client, which turns
    that class of break into a TypeScript error.

    Every field but ``event`` is optional, and deliberately so: this is a union
    of what ~30 distinct signals carry, not a claim that any one of them carries
    all of it. Which fields a given signal actually populates is documented on
    its factory function. The alternative — a discriminated union with one model
    per signal — buys per-signal precision at the cost of thirty-odd models to
    keep in step with their factories, and the consumer switches on ``event``
    anyway.
    """

    event: SSESignal

    # Routing and subjects
    org_id: str | None = None
    repo_id: str | None = None
    repo_ids: list[str] | None = None
    analysis_id: str | None = None
    fix_id: str | None = None
    fix_ids: list[str] | None = None
    issue_ids: list[str] | None = None
    telemetry_run_id: str | None = None
    installation_id: int | None = None

    # WorkflowScan outcome
    branch: str | None = None
    trigger: str | None = None
    score: float | None = None
    grade: str | None = None
    issues_count: int | None = None
    error: str | None = None

    # Pull requests
    pr_url: str | None = None
    pr_branch: str | None = None

    # Installations and repositories
    org_name: str | None = None
    repo_count: int | None = None
    repos_disabled: int | None = None
    enabled: bool | None = None

    # Billing
    tier: str | None = None
    status: str | None = None
    meter: str | None = None
    message: str | None = None
