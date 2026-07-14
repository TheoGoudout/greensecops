"""Repository accessibility/lifecycle state machine (``python-statemachine``).

States mirror ``RepositoryStatus`` and model the *accessibility* axis — whether
GreenSecOps can act on the repo — as GitHub installation and repository webhooks
report it. This axis is orthogonal to ``Repository.enabled`` (user opt-in) and
``is_external``, which stay plain flags.

``is_accessible`` is a machine-synced cache of ``status == active`` so the many
existing ``if not repo.is_accessible`` write-gates need no change; call sites
advance the machine and then call :func:`sync_access_flag`. Behaviour lives in
the ``installation``/``installation_repositories``/``repository`` webhook
handlers (``api/routes/webhooks.py``) and ``crud.py``.
"""

from __future__ import annotations

from statemachine import State, StateMachine

from app.models.enums import RepositoryStatus, SSESignal


class RepositoryMachine(StateMachine):
    state_field = "status"

    active = State(initial=True, value=RepositoryStatus.active)
    suspended = State(value=RepositoryStatus.suspended)
    archived = State(value=RepositoryStatus.archived)
    inaccessible = State(value=RepositoryStatus.inaccessible)

    # Inputs (events) — GitHub webhook causes.
    suspend = active.to(suspended)  # installation suspended
    unsuspend = suspended.to(active)  # installation unsuspended
    archive = active.to(archived)  # repo archived on GitHub
    unarchive = archived.to(active)  # repo unarchived
    # installation deleted, or repo removed from the installation.
    lose_access = (
        active.to(inaccessible) | suspended.to(inaccessible) | archived.to(inaccessible)
    )
    regain_access = inaccessible.to(active)  # repo re-added / installation restored

    # Outputs (SSE signal emitted when each event fires)
    outputs: dict[str, SSESignal | None] = {
        "suspend": SSESignal.repository_suspended,
        "unsuspend": SSESignal.repository_restored,
        "archive": SSESignal.repository_archived,
        "unarchive": SSESignal.repository_restored,
        "lose_access": SSESignal.repository_inaccessible,
        "regain_access": SSESignal.repository_restored,
    }


def sync_access_flag(repo: object) -> None:
    """Mirror ``is_accessible`` from ``status`` (accessible iff ``active``).

    Called after advancing the machine so the boolean write-gate stays in lock
    step with the lifecycle state without touching every read site.
    """
    repo.is_accessible = getattr(repo, "status", None) == RepositoryStatus.active  # type: ignore[attr-defined]
