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
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.models import (
    CloudScan,
    Engine,
    FindingUpdate,
    LLMProvider,
    Repository,
    ScanTargetUpdate,
    UsageEngine,
    UsageMeter,
    WorkflowFile,
    WorkflowFix,
    WorkflowScan,
)
from app.models.enums import (
    FindingStatus,
    FixStatus,
    ScanStatus,
    TargetAction,
    TargetActivity,
)
from app.services import state_machines as sm
from app.services.billing import usage as billing_usage
from app.services.billing.quota import enforce_quota
from app.services.engines import EngineSpec
from app.services.llm.catalog import resolve_llm_provider
from app.services.sarif_report import sarif_for_repository


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


def set_finding_ignored(
    session: Session, finding: Any, ignored: bool | None, label: str
) -> Any:
    """Mute or un-mute a finding through ``FindingMachine``, then commit.

    Muting is idempotent on an already-ignored finding and a **409** on one
    that is ``resolved``: ``FindingMachine.ignore`` is legal only from ``open``
    and ``fix_in_progress``, and answering ``200`` with an unchanged row would
    let the UI toast "Finding ignored" over a finding it had not ignored.
    Un-muting stays silent where muting raises: a finding that is not ignored
    has nothing to un-ignore whatever the reason, so the call is safe to retry.
    """
    if ignored is None:
        return finding
    if ignored:
        if finding.status == FindingStatus.ignored:
            return finding
        if not sm.try_advance(finding, sm.FindingMachine, "ignore"):
            raise HTTPException(
                status_code=409,
                detail=f"A {label} finding that is {finding.status.value} "
                "cannot be ignored",
            )
    elif not sm.try_advance(finding, sm.FindingMachine, "unignore"):
        return finding
    session.add(finding)
    session.commit()
    session.refresh(finding)
    return finding


def update_finding_for_user(
    spec: EngineSpec,
    finding_id: uuid.UUID,
    body: FindingUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """``PATCH /{engine}/findings/{id}``: apply ``body`` to one finding.

    Refused while the owning target is busy: a scan in flight is about to
    rewrite the finding the user is muting.
    """
    finding = get_finding_for_user(spec, finding_id, session, current_user)
    if body.ignored is not None:
        require_target_idle(
            spec, session, getattr(finding, spec.target_id_field), TargetAction.ignore
        )
    return set_finding_ignored(session, finding, body.ignored, spec.label)


def list_fixes_for_repo(
    spec: EngineSpec,
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID,
) -> list[Any]:
    """Every fix under one repository's targets of ``spec``, newest first.

    The cross-target read the URL grammar already promises each engine
    (``/{engine}/fixes``) and that only the CI engine had. Its caller is the
    pull-requests tab: it lists a repository's PRs and offers "Update PR" on
    each, and deciding whether that may be pressed means knowing whether any of
    the owning target's fixes is in flight. Per-target reads could only answer
    that with one request per target, on a page that already has the whole list.
    """
    authorize_repo(session, current_user, repo_id, detail="Repository not found")
    target_col = getattr(spec.fix_model, spec.target_id_field)
    return list(
        session.exec(
            select(spec.fix_model)
            .where(
                col(target_col).in_(
                    select(spec.target_model.id).where(
                        spec.target_model.repo_id == repo_id
                    )
                )
            )
            .order_by(col(spec.fix_model.created_at).desc())
        ).all()
    )


def require_idle(
    activity: TargetActivity,
    action: TargetAction,
    target_label: str,
) -> None:
    """409 when ``activity`` forbids ``action``.

    The HTTP half of :mod:`app.services.state_machines.engine_target`. Split
    from the query below so the two callers that have no ``EngineSpec`` — the
    cloud engine, which has no fixes, and the CI-workflow engine, whose scope
    is a repository or a single workflow file — raise the identical error
    rather than writing their own.

    A 409 rather than the silent ``202`` these routes used to return: the
    duplicate was already being discarded, by the Redis lock in the worker
    (``scan_support.scan_lock``) or by ``prepare_pending_fix`` below, but
    nothing said so and the UI had no way to know. Same reasoning as the 402
    ``enforce_quota`` raises — fail where the user can see it, rather than
    letting them watch a job disappear.
    """
    reason = sm.blocked_reason(activity, action)
    if reason is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action.value} while {reason} for this {target_label}",
        )


def _statuses(session: SessionDep, statement: Any) -> list[Any]:
    """Run a single-column ``status`` select and return the values.

    ``list[Any]`` on purpose. The two type checkers this project runs describe a
    scalar-column select differently — mypy calls it ``Sequence[str]``, ty calls
    it ``Sequence[Sequence[Unknown]]`` — and neither is what SQLAlchemy actually
    hands back, which is the status enum. ``activity_of`` reads either spelling,
    so this is where the argument stops rather than spreading through three
    call sites.
    """
    return list(session.exec(statement).all())


def target_activity(
    spec: EngineSpec,
    session: SessionDep,
    target_id: uuid.UUID,
) -> TargetActivity:
    """What one registered target is busy with right now.

    Reads the same two things the target's card does: the status of its most
    recent scan whatever the outcome (matching ``mappers.base.latest_scan_status``,
    so the API and the badge on screen never disagree) and the statuses of any
    fixes a worker still holds.
    """
    scan_target = getattr(spec.scan_model, spec.target_id_field)
    fix_target = getattr(spec.fix_model, spec.target_id_field)
    return sm.activity_of(
        _statuses(
            session,
            select(spec.scan_model.status)
            .where(scan_target == target_id)
            .order_by(col(spec.scan_model.created_at).desc())
            .limit(1),
        ),
        _statuses(
            session,
            select(spec.fix_model.status)
            .where(fix_target == target_id)
            .where(col(spec.fix_model.status).in_(sm.IN_FLIGHT_STATUSES)),
        ),
    )


def target_activities(
    spec: EngineSpec,
    session: Session,
    target_ids: list[uuid.UUID],
) -> dict[uuid.UUID, TargetActivity]:
    """:func:`target_activity` for a whole page of targets, in two queries.

    The list endpoints publish this on ``ScanTargetPublicBase.activity`` so the
    browser reads what the 409 guard would decide rather than reconstructing it
    from three separate collections. Per-row reads would be the N+1 the
    repository list already avoids with ``_latest_scan_statuses_batch``, and
    these lists are unpaginated.

    Deliberately the same two questions :func:`target_activity` asks — the
    latest scan whatever its outcome, and any fix a worker still holds — so a
    row's field and the refusal it predicts can never disagree.
    """
    if not target_ids:
        return {}

    scan_target = getattr(spec.scan_model, spec.target_id_field)
    fix_target = getattr(spec.fix_model, spec.target_id_field)

    # The latest scan per target: rank by recency within each target and keep
    # the first. One query rather than one per row.
    ranked = (
        select(
            scan_target.label("target_id"),
            col(spec.scan_model.status).label("status"),
            func.row_number()
            .over(
                partition_by=scan_target,
                order_by=col(spec.scan_model.created_at).desc(),
            )
            .label("rank"),
        )
        .where(col(scan_target).in_(target_ids))
        .subquery()
    )
    scans: dict[uuid.UUID, Any] = dict(
        session.exec(
            select(ranked.c.target_id, ranked.c.status).where(ranked.c.rank == 1)
        ).all()
    )

    fixes: dict[uuid.UUID, list[Any]] = {}
    for target_id, status in session.exec(
        select(fix_target, spec.fix_model.status)
        .where(col(fix_target).in_(target_ids))
        .where(col(spec.fix_model.status).in_(sm.IN_FLIGHT_STATUSES))
    ).all():
        fixes.setdefault(target_id, []).append(status)

    return {
        target_id: sm.activity_of([scans.get(target_id)], fixes.get(target_id, []))
        for target_id in target_ids
    }


def require_target_idle(
    spec: EngineSpec,
    session: SessionDep,
    target_id: uuid.UUID,
    action: TargetAction,
) -> None:
    """Refuse ``action`` on a target that is already scanning, generating or
    delivering. See :func:`require_idle` for why this is a 409."""
    require_idle(target_activity(spec, session, target_id), action, spec.target_label)


def repository_activity(session: SessionDep, repo_id: uuid.UUID) -> TargetActivity:
    """What a repository is busy with on the CI-workflow engine.

    The CI engine has no ``EngineSpec`` — its fixes key on a persisted
    ``WorkflowFile`` rather than a ``(target, path)`` pair — so its scope is
    spelled out here instead of derived from a spec.

    Scans are counted as *any* unfinished scan for the repository rather than
    only the most recent one, because that is the granularity the work actually
    serializes at: ``static_analysis`` takes ``scan_lock("static_analysis:<repo>")``,
    one lock for the whole repository, and a repo-wide analysis writes one scan
    row per workflow file, so "the latest row" would happily be a finished one
    while a sibling is still running.

    Fixes reach the repository through ``WorkflowFile``: ``WorkflowFix`` carries
    no ``repo_id`` column (the public schema derives one in the mapper), so the
    membership test is a join, not a filter.
    """
    return sm.activity_of(
        _statuses(
            session,
            select(WorkflowScan.status)
            .where(WorkflowScan.repo_id == repo_id)
            .where(col(WorkflowScan.status).in_(sm.ACTIVE_SCAN_STATUSES))
            .limit(1),
        ),
        _statuses(
            session,
            select(WorkflowFix.status)
            .join(
                WorkflowFile, col(WorkflowFile.id) == col(WorkflowFix.workflow_file_id)
            )
            .where(WorkflowFile.repo_id == repo_id)
            .where(col(WorkflowFix.status).in_(sm.IN_FLIGHT_STATUSES)),
        ),
    )


def workflow_file_activity(
    session: SessionDep,
    workflow_file: Any,
) -> TargetActivity:
    """What one workflow file is busy with.

    The scan half is the whole repository's — a CI analysis holds a repo-wide
    lock whether it was aimed at one file or all of them — while the fix half is
    this file's own, so a user can still ship or regenerate file A's fix while
    file B is being written.
    """
    return sm.activity_of(
        _statuses(
            session,
            select(WorkflowScan.status)
            .where(WorkflowScan.repo_id == workflow_file.repo_id)
            .where(col(WorkflowScan.status).in_(sm.ACTIVE_SCAN_STATUSES))
            .limit(1),
        ),
        _statuses(
            session,
            select(WorkflowFix.status)
            .where(WorkflowFix.workflow_file_id == workflow_file.id)
            .where(col(WorkflowFix.status).in_(sm.IN_FLIGHT_STATUSES)),
        ),
    )


def cloud_account_activity(
    session: SessionDep, account_id: uuid.UUID
) -> TargetActivity:
    """What a cloud account is busy with.

    Cloud has no fixes — no files to rewrite — so the only thing that can be in
    flight is another scan. It lives here beside the CI helpers, rather than in
    the cloud route module, for the same reason: this is where "what is this
    target doing?" is answered for every engine, spec or no spec.
    """
    return sm.activity_of(
        _statuses(
            session,
            select(CloudScan.status)
            .where(CloudScan.cloud_account_id == account_id)
            .order_by(col(CloudScan.created_at).desc())
            .limit(1),
        )
    )


def cloud_account_activities(
    session: Session, account_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TargetActivity]:
    """:func:`cloud_account_activity` for a whole page of accounts.

    Cloud has no ``EngineSpec`` and no fixes, so it cannot use
    :func:`target_activities`; the shape is the same, minus the fix half.
    """
    if not account_ids:
        return {}

    ranked = (
        select(
            col(CloudScan.cloud_account_id).label("account_id"),
            col(CloudScan.status).label("status"),
            func.row_number()
            .over(
                partition_by=col(CloudScan.cloud_account_id),
                order_by=col(CloudScan.created_at).desc(),
            )
            .label("rank"),
        )
        .where(col(CloudScan.cloud_account_id).in_(account_ids))
        .subquery()
    )
    latest: dict[uuid.UUID, Any] = dict(
        session.exec(
            select(ranked.c.account_id, ranked.c.status).where(ranked.c.rank == 1)
        ).all()
    )
    return {
        account_id: sm.activity_of([latest.get(account_id)])
        for account_id in account_ids
    }


def repository_activities(
    session: Session, repo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, TargetActivity]:
    """:func:`repository_activity` for a whole page of repositories.

    The scan half matches ``routes/repositories._latest_scan_statuses_batch``'s
    rule — *any* unfinished scan counts, because a CI analysis writes one row
    per workflow file under one repo-wide lock — so the ``activity`` a row
    publishes and the ``latest_scan_status`` beside it tell the same story.
    """
    if not repo_ids:
        return {}

    scanning = set(
        session.exec(
            select(WorkflowScan.repo_id)
            .where(col(WorkflowScan.repo_id).in_(repo_ids))
            .where(col(WorkflowScan.status).in_(sm.ACTIVE_SCAN_STATUSES))
            .distinct()
        ).all()
    )

    fixes: dict[uuid.UUID, list[Any]] = {}
    for repo_id, status in session.exec(
        select(WorkflowFile.repo_id, WorkflowFix.status)
        .join(WorkflowFile, col(WorkflowFile.id) == col(WorkflowFix.workflow_file_id))
        .where(col(WorkflowFile.repo_id).in_(repo_ids))
        .where(col(WorkflowFix.status).in_(sm.IN_FLIGHT_STATUSES))
    ).all():
        fixes.setdefault(repo_id, []).append(status)

    return {
        repo_id: sm.activity_of(
            [ScanStatus.running] if repo_id in scanning else [],
            fixes.get(repo_id, []),
        )
        for repo_id in repo_ids
    }


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


# ─── Route bodies every file engine shares ──────────────────────────────────


def normalize_root_path(raw: str) -> str:
    """Collapse the spellings of one folder to one.

    ``"infra"``, ``"/infra/"`` and ``" infra "`` all address the same folder,
    and ``""``, ``"/"`` and ``"."`` all mean the repository root. The
    ``(repo_id, root_path)`` unique constraints compare strings, so without
    this a repository could accumulate targets that scan the same files.
    """
    stripped = raw.strip().strip("/")
    return "" if stripped in ("", ".") else stripped


def create_target(
    spec: EngineSpec,
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID,
    root_path: str,
    *,
    allow_repo_root: bool,
) -> Any:
    """Register a folder of a repository as one of ``spec``'s targets.

    ``allow_repo_root`` is the per-engine part: a Terraform root must name a
    folder, while a Docker target or an Ansible project frequently *is* the
    whole repository.
    """
    repo = authorize_repo(session, current_user, repo_id)
    path = normalize_root_path(root_path)
    if not path and not allow_repo_root:
        raise HTTPException(status_code=422, detail="root_path must not be empty")
    existing = session.exec(
        select(spec.target_model)
        .where(spec.target_model.repo_id == repo.id)
        .where(spec.target_model.root_path == path)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This path is already configured")
    target = spec.target_model(repo_id=repo.id, root_path=path)
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def list_targets(
    spec: EngineSpec,
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None,
) -> list[tuple[Any, TargetActivity]]:
    """One repository's targets, or every target the user can see, by path.

    Dual-mode so the same endpoint powers both the org-wide Infrastructure page
    and the per-repository tab. Each target comes with what it is busy with, in
    one batched read for the whole page, so a list can grey its own actions
    without fetching each target's fixes to work it out.
    """
    model = spec.target_model
    query = select(model)
    if repo_id:
        authorize_repo(session, current_user, repo_id)
        query = query.where(model.repo_id == repo_id)
    elif not current_user.is_superuser:
        query = query.join(Repository, col(model.repo_id) == col(Repository.id)).where(
            col(Repository.org_id).in_(user_org_ids(session, current_user))
        )
    targets = session.exec(query.order_by(col(model.root_path))).all()
    activities = target_activities(spec, session, [t.id for t in targets])
    return [(t, activities.get(t.id, TargetActivity.idle)) for t in targets]


def update_target(
    spec: EngineSpec,
    target_id: uuid.UUID,
    body: ScanTargetUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> tuple[Any, TargetActivity]:
    """Apply ``body`` to a target and return it with its current activity."""
    target = get_target_for_user(spec, target_id, session, current_user)
    if body.enabled is not None:
        target.enabled = body.enabled
    session.add(target)
    session.commit()
    session.refresh(target)
    return target, target_activity(spec, session, target.id)


def delete_target(
    spec: EngineSpec,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    """Remove a target and, by cascade, its scans, findings and fixes.

    Which is why it needs the guard the disable switch does not: a worker
    still holding one of those rows would be writing into a deleted tree.
    """
    target = get_target_for_user(spec, target_id, session, current_user)
    require_target_idle(spec, session, target_id, TargetAction.remove)
    session.delete(target)
    session.commit()


def trigger_target_scan(
    spec: EngineSpec,
    scan_task: Any,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None,
) -> dict[str, str]:
    """Queue a manual scan of one target."""
    target = get_target_for_user(spec, target_id, session, current_user)
    if not target.enabled:
        raise HTTPException(status_code=403, detail=f"{spec.target_label} is disabled")
    require_target_idle(spec, session, target_id, TargetAction.scan)
    repo = session.get_one(Repository, target.repo_id)
    # Fail fast with a precise 402 rather than letting the user watch a job
    # disappear. The worker re-checks — that gate is the one that holds.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "analyses",
        engine=UsageEngine.of(spec.engine),
    )
    scan_task.delay(
        **{spec.target_id_field: str(target.id)},
        branch=branch or "",
        trigger="manual",
    )
    return {"status": "queued", spec.target_id_field: str(target_id)}


def list_target_scans(
    spec: EngineSpec,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int,
) -> list[Any]:
    """A target's most recent scans, newest first."""
    get_target_for_user(spec, target_id, session, current_user)
    scan_model = spec.scan_model
    return list(
        session.exec(
            select(scan_model)
            .where(getattr(scan_model, spec.target_id_field) == target_id)
            .order_by(col(scan_model.created_at).desc())
            .limit(limit)
        ).all()
    )


def list_target_findings(
    spec: EngineSpec,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool,
) -> list[Any]:
    """A target's findings, by file then line.

    The order a reader works in: one file at a time, top to bottom.
    """
    get_target_for_user(spec, target_id, session, current_user)
    model = spec.finding_model
    query = select(model).where(getattr(model, spec.target_id_field) == target_id)
    if not include_resolved:
        query = query.where(col(model.resolved_at).is_(None))
    return list(
        session.exec(query.order_by(col(model.file_path), col(model.line_start))).all()
    )


def fetch_target_files(
    spec: EngineSpec,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None,
    fetch_files: Callable[..., list[Any]],
) -> list[Any]:
    """A target's live source, fetched from GitHub on demand, by path.

    These files are not persisted (unlike ``WorkflowFile``), so this fetches
    them the same way the scan worker does — which lets the UI show source with
    the findings annotated inline. Any failure there is upstream's, hence 502.

    ``fetch_files`` is passed in by the route module because its module-level
    name is the seam the tests patch.
    """
    target = get_target_for_user(spec, target_id, session, current_user)
    repo = session.get_one(Repository, target.repo_id)
    try:
        fetched = fetch_files(repo, target.root_path, ref=ref)
    except Exception as exc:  # network / GitHub failures are transient
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch {spec.files_description} from GitHub",
        ) from exc
    return sorted(fetched, key=lambda f: f.path)


def list_target_fixes(
    spec: EngineSpec,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[Any]:
    """A target's fixes, newest first."""
    get_target_for_user(spec, target_id, session, current_user)
    model = spec.fix_model
    return list(
        session.exec(
            select(model)
            .where(getattr(model, spec.target_id_field) == target_id)
            .order_by(col(model.created_at).desc())
        ).all()
    )


def open_findings_by_file(
    spec: EngineSpec,
    session: SessionDep,
    target_id: uuid.UUID,
    finding_ids: list[uuid.UUID] | None = None,
    file_path: str | None = None,
) -> dict[str, list[Any]]:
    """A target's open findings — or the chosen subset — grouped by file.

    One whole-file LLM rewrite per file: the model sees every finding in the
    file at once, which is cheaper and keeps two fixes from racing to patch
    the same lines.
    """
    model = spec.finding_model
    query = (
        select(model)
        .where(getattr(model, spec.target_id_field) == target_id)
        .where(col(model.resolved_at).is_(None))
        .where(col(model.ignored_at).is_(None))
    )
    if finding_ids:
        query = query.where(col(model.id).in_(finding_ids))
    if file_path is not None:
        query = query.where(model.file_path == file_path)
    by_file: dict[str, list[Any]] = defaultdict(list)
    for finding in session.exec(query).all():
        by_file[finding.file_path].append(finding)
    return dict(by_file)


def queue_file_fixes(
    spec: EngineSpec,
    session: SessionDep,
    current_user: CurrentUser,
    target: Any,
    by_file: dict[str, list[Any]],
    force: bool,
    dispatch: Callable[[str, list[Any]], None],
) -> dict[str, str | int]:
    """Create one pending fix per file, charge for them, then queue each.

    One transaction for the whole request: every fix row, the findings linked
    to it and its usage charge commit together, and ``dispatch`` runs only
    after that commit — so a worker never picks up a row a later failure would
    roll back, and a half-processed request cannot bill for fixes it never
    queued. ``dispatch(file_path, findings)`` queues the engine's generation
    task for one file.
    """
    repo = session.get_one(Repository, target.repo_id)
    # Each file is one LLM call, so the request costs as many generations as
    # there are files.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "fixes",
        requested=len(by_file),
        engine=UsageEngine.of(spec.engine),
    )
    provider_str, model_str = resolve_llm_provider(repo)
    queued: list[str] = []
    for file_path, findings in by_file.items():
        fix = prepare_pending_fix(
            spec,
            session,
            target.id,
            file_path,
            provider_str,
            model_str,
            force,
            repo=repo,
        )
        if fix is None:
            continue
        for finding in findings:
            finding.fix_id = fix.id
            session.add(finding)
        queued.append(file_path)
    session.commit()
    for file_path in queued:
        dispatch(file_path, by_file[file_path])
    return {"status": "queued", "queued": len(queued)}


def generate_target_fixes(
    spec: EngineSpec,
    fix_task: Any,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    finding_ids: list[uuid.UUID] | None,
    force: bool,
) -> dict[str, str | int]:
    """Generate LLM fixes for a target's open findings, one whole-file fix each."""
    target = get_target_for_user(spec, target_id, session, current_user)
    require_target_idle(spec, session, target_id, TargetAction.generate)
    by_file = open_findings_by_file(spec, session, target_id, finding_ids)
    if not by_file:
        return {"status": "no_findings", "queued": 0}
    return queue_file_fixes(
        spec,
        session,
        current_user,
        target,
        by_file,
        force,
        lambda _path, findings: fix_task.delay(
            finding_ids=[str(f.id) for f in findings]
        ),
    )


def deliver_target_fixes(
    spec: EngineSpec,
    delivery_task: Any,
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool,
) -> dict[str, str]:
    """Deliver a target's ready fixes as a single PR (one branch per target).

    The branch is returned so the UI can match the target against a PR that is
    already open.
    """
    target = get_target_for_user(spec, target_id, session, current_user)
    require_target_idle(spec, session, target_id, TargetAction.deliver)
    delivery_task.delay(**{spec.target_id_field: str(target.id)}, force=force)
    return {
        "status": "queued",
        spec.target_id_field: str(target_id),
        "pr_branch": spec.fix_branch(target.id),
    }


# ─── SARIF, for GitHub Code Scanning ─────────────────────────────────────────


def repo_from_oidc_claims(session: Session, claims: dict[str, Any]) -> Repository:
    """The repository a GitHub Actions OIDC token was minted for.

    The caller is a workflow run, not a person, so the repository is taken from
    the signed token rather than from a path parameter — a run cannot ask for
    another repository's findings, because it cannot mint a claim naming one.
    That is the whole authorization story for these endpoints, and it is why
    they carry no id in the path.
    """
    full_name = str(claims.get("repository", ""))
    repo = session.exec(
        select(Repository).where(Repository.full_name == full_name)
    ).first()
    if repo is None:
        # 404 rather than 403: from the runner's side the difference between
        # "not registered" and "not yours" is not a distinction we can make —
        # the token proves the repository, so an unknown one is simply absent.
        raise HTTPException(
            status_code=404,
            detail=(
                f"{full_name or 'This repository'} is not registered with "
                "GreenSecOps. Add it from the dashboard first."
            ),
        )
    return repo


def sarif_for_claims(
    engine: Engine, session: SessionDep, claims: dict[str, Any]
) -> dict[str, Any]:
    """One engine's open findings for the calling repository, as SARIF.

    Shared by the four file engines' ``GET /{engine}/sarif`` routes. Those stay
    one function each so their operation ids — and therefore the generated
    clients' method names — say which engine they fetch.
    """
    return sarif_for_repository(session, repo_from_oidc_claims(session, claims), engine)


def enabled_targets_for_claims(
    spec: EngineSpec, session: SessionDep, claims: dict[str, Any]
) -> tuple[Repository, list[Any]]:
    """The calling repository and the targets of ``spec`` it has switched on.

    The scan half of the Code Scanning flow. A workflow run asks for its own
    repository to be re-analysed and then fetches the SARIF; without this a
    team using the workflows instead of the App would publish only whatever the
    last scan happened to find, and on a repository that has never been scanned
    that is nothing at all.

    A disabled target stays disabled: the switch means "do not spend analyses
    on this", and a run coming in over OIDC is not a reason to override the
    decision someone made in the dashboard.
    """
    repo = repo_from_oidc_claims(session, claims)
    targets = list(
        session.exec(
            select(spec.target_model)
            .where(spec.target_model.repo_id == repo.id)
            .where(spec.target_model.enabled.is_(True))
        ).all()
    )
    return repo, targets


def trigger_code_scanning_scans(
    spec: EngineSpec,
    scan_task: Any,
    session: SessionDep,
    claims: dict[str, Any],
    branch: str | None,
) -> dict[str, str]:
    """Re-scan every enabled target of ``spec`` in the calling repository.

    The first half of the Code Scanning flow: a workflow asks for fresh
    analysis and then fetches ``GET /{engine}/sarif``. Quota is charged to the
    org's billing owner, exactly as a dashboard-triggered scan is; there is no
    user to attribute it to.
    """
    repo, targets = enabled_targets_for_claims(spec, session, claims)
    if not targets:
        return {"status": "no_targets", "queued": "0"}
    enforce_quota(
        session,
        None,
        repo.org_id,
        "analyses",
        requested=len(targets),
        engine=UsageEngine.of(spec.engine),
    )
    for target in targets:
        scan_task.delay(
            **{spec.target_id_field: str(target.id)},
            branch=branch or "",
            trigger="code_scanning",
        )
    return {"status": "queued", "queued": str(len(targets))}
