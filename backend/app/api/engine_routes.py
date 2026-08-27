"""Route bodies the Terraform and Docker endpoints share.

The route *functions* stay one-per-endpoint in their own modules, because their
names become OpenAPI operation ids and therefore the generated clients' method
names. Only the bodies that were genuinely identical move here.

The list endpoints deliberately stay put: their limits and orderings differ per
engine (a Docker findings list sorts by file and line, a Terraform one by
recency), so parameterising them would need more knobs than it saves.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, authorize_repo, get_or_404
from app.models import LLMProvider, Repository, UsageEngine, UsageMeter
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.billing import usage as billing_usage
from app.services.engines import EngineSpec


def get_target_for_user(
    spec: EngineSpec,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Load a scan target the user may see, or 404.

    Both the missing and the unauthorized case return the same detail, so the
    API never discloses that another tenant's target exists.
    """
    detail = f"{spec.target_label} not found"
    target = get_or_404(session, spec.target_model, target_id, detail=detail)
    authorize_repo(session, current_user, target.repo_id, detail=detail)
    return target


def get_finding_for_user(
    spec: EngineSpec,
    finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Load a finding the user may see, or 404.

    Authorizes through the finding's own target (Terraform root / Docker
    target / Ansible project) rather than a direct org lookup, mirroring
    ``get_target_for_user`` — the finding carries its target id denormalized
    (see ``EngineSpec.target_id_field``), so no join back through the scan is
    needed the way Workflow's ``_authorize_issue`` requires.
    """
    detail = f"{spec.label} finding not found"
    finding = get_or_404(session, spec.finding_model, finding_id, detail=detail)
    get_target_for_user(
        spec, getattr(finding, spec.target_id_field), session, current_user
    )
    return finding


def ignore_finding_for_user(
    spec: EngineSpec,
    finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Mute a violation (false positive / accepted risk). Idempotent."""
    finding = get_finding_for_user(spec, finding_id, session, current_user)
    if sm.try_advance(finding, sm.FindingMachine, "ignore"):
        session.add(finding)
        session.commit()
        session.refresh(finding)
    return finding


def unignore_finding_for_user(
    spec: EngineSpec,
    finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Un-mute a previously ignored violation. Idempotent."""
    finding = get_finding_for_user(spec, finding_id, session, current_user)
    if sm.try_advance(finding, sm.FindingMachine, "unignore"):
        session.add(finding)
        session.commit()
        session.refresh(finding)
    return finding


def prepare_pending_fix(
    spec: EngineSpec,
    session: SessionDep,
    target_id: uuid.UUID,
    file_path: str,
    provider_str: str,
    model_str: str,
    force: bool,
    repo: Repository | None = None,
) -> Any | None:
    """Create or reuse the single (target, file) fix row, leaving it ``pending``.

    Returns ``None`` when a fix is already in flight, or already resolved and
    not being forced — nothing to (re)queue.

    Passing ``repo`` charges the org's ``fixes`` allowance for the generation
    this call is about to queue. Every early return above leaves it uncharged,
    which is exactly right: those paths queue no LLM call. Terraform and Docker
    fix generation was unmetered entirely before this — the same LLM spend as a
    workflow fix, billed to nobody.
    """
    target_col = getattr(spec.fix_model, spec.target_id_field)
    existing = session.exec(
        select(spec.fix_model)
        .where(target_col == target_id)
        .where(spec.fix_model.file_path == file_path)
    ).first()
    if existing is not None:
        # A fix a worker is mid-way through must not be reset out from under it.
        if existing.status in sm.IN_FLIGHT_STATUSES:
            return None
        if not force and existing.status != FixStatus.failed:
            return None
        # Reuse the row (the unique constraint allows only one per file): hard
        # reset to pending for a fresh generation.
        sm.force_to(existing, sm.FixMachine, FixStatus.pending)
        existing.full_content = None
        existing.error_message = None
        existing.pr_id = None
        existing.llm_provider = LLMProvider(provider_str)
        existing.llm_model = model_str
        session.add(existing)
        _charge_fix(session, spec, repo, existing.id)
        return existing

    fix = spec.fix_model(
        **{spec.target_id_field: target_id},
        file_path=file_path,
        llm_provider=LLMProvider(provider_str),
        llm_model=model_str,
        status=FixStatus.pending,
    )
    session.add(fix)
    session.flush()
    _charge_fix(session, spec, repo, fix.id)
    return fix


def _charge_fix(
    session: SessionDep,
    spec: EngineSpec,
    repo: Repository | None,
    fix_id: uuid.UUID,
) -> None:
    """Debit one ``fixes`` unit for a generation this engine is about to run.

    A regenerate reuses the fix row but is still a fresh LLM call, so it is
    charged again — usage counts generation events, not surviving rows.
    """
    if repo is None:
        return
    billing_usage.record_for_org(
        session,
        org_id=repo.org_id,
        repo_id=repo.id,
        meter=UsageMeter.fixes,
        engine=UsageEngine.of(spec.engine),
        source_type=f"{spec.name}_fix",
        source_id=fix_id,
        commit=False,
    )
