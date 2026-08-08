import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    GitHubOidcClaims,
    SessionDep,
    authorize_repo,
)
from app.api.mappers import (
    compute_telemetry_average,
    to_dynamic_enrichment_public,
    to_telemetry_run_public,
)
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE, LIMIT_INGEST
from app.models import (
    DockerBuildTelemetry,
    DynamicAnalysisStatus,
    DynamicEnrichment,
    DynamicEnrichmentPublic,
    Repository,
    TelemetryMetricSample,
    TelemetryPhase,
    TelemetryRun,
    TelemetrySummaryPublic,
    UsageEngine,
)
from app.services.billing.quota import enforce_quota

logger = logging.getLogger(__name__)

router = RoleRouter(prefix="/telemetry", tags=["telemetry"])


class TelemetryPayload(BaseModel):
    workflow_run_id: int
    branch: str = ""
    commit_sha: str = ""
    workflow_name: str = ""
    runner_specs: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    phase: TelemetryPhase = TelemetryPhase.completed


class DockerBuildPayload(BaseModel):
    """One image build (and optionally its containers) observed in CI.

    A workflow can build several images, so this is posted once per image
    rather than once per run — which is exactly why it is not folded into
    TelemetryPayload.
    """

    workflow_run_id: int
    image_ref: str | None = None
    # The join back to the static engine: lets a measured cache-hit ratio be
    # shown against the DockerFinding that predicted the problem from
    # instruction order alone.
    dockerfile_path: str | None = None
    image_size_bytes: int | None = None
    context_size_bytes: int | None = None
    build_duration_ms: int | None = None
    # Only the opt-in BuildKit metadata path can supply this; the zero-config
    # `docker history` collector cannot tell whether a layer was cached.
    cache_hit_ratio: float | None = None
    layers: list[dict[str, Any]] | None = None
    containers: list[dict[str, Any]] | None = None


class SamplePayload(BaseModel):
    workflow_run_id: int
    cpu_percent: float | None = None
    ram_used_mb: float | None = None
    disk_used_gb: float | None = None
    net_bytes_sent: int | None = None
    net_bytes_recv: int | None = None
    # Top 5-10% resource-consuming processes from the proc-sampler binary
    # (Linux runners only); absent elsewhere or if sampling failed.
    top_processes: list[dict[str, Any]] | None = None


def _count_observed_builds(
    session: SessionDep,
    repo_id: uuid.UUID,
    telemetry: DockerBuildTelemetry,
) -> int:
    """How many builds of this Dockerfile we have now seen, including this one.

    Server-side because it is a property of the *series*, and the runner has no
    way to know it — it sees one job. ``image_layer_cache_ineffective`` gates on
    this to avoid firing on a first build that legitimately missed every layer,
    so a client-supplied count would let a caller suppress or force the rule.

    Counted per ``dockerfile_path`` rather than per image: image ids change on
    every build by definition, so counting those would always answer 1.
    """
    query = (
        select(func.count())
        .select_from(DockerBuildTelemetry)
        .where(DockerBuildTelemetry.repo_id == repo_id)
    )
    if telemetry.dockerfile_path is None:
        query = query.where(col(DockerBuildTelemetry.dockerfile_path).is_(None))
    else:
        query = query.where(
            DockerBuildTelemetry.dockerfile_path == telemetry.dockerfile_path
        )
    return session.exec(query).one()


def _lookup_repo(session: SessionDep, repository: str) -> Repository | None:
    return session.exec(
        select(Repository).where(Repository.full_name == repository)
    ).first()


@router.post("/ingest", role=Role.service, limit=LIMIT_INGEST, status_code=201)
async def ingest_telemetry(
    payload: TelemetryPayload,
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, str]:
    repository: str = claims.get("repository", "")

    repo = _lookup_repo(session, repository)
    if not repo:
        logger.info(
            "Telemetry received for unregistered repo %s — ignoring",
            repository,
        )
        return {"status": "accepted", "note": "repository_not_registered"}

    existing = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.workflow_run_id == payload.workflow_run_id)
        .where(TelemetryRun.phase == payload.phase)
    ).first()

    if existing:
        return {"status": "accepted", "note": "duplicate_run_phase"}

    run = TelemetryRun(
        repo_id=repo.id,
        workflow_run_id=payload.workflow_run_id,
        runner_specs=json.dumps(payload.runner_specs),
        metrics=json.dumps(payload.metrics),
        phase=payload.phase,
        # Only completed-phase rows enrich; mark them queued so the worker can
        # advance them through the TelemetryMachine.
        dynamic_status=(
            DynamicAnalysisStatus.queued
            if payload.phase == TelemetryPhase.completed
            else None
        ),
    )
    session.add(run)
    session.commit()

    # A completed run carries the full metrics needed for enrichment; queue the
    # dynamic analysis that turns them into persisted findings.
    if payload.phase == TelemetryPhase.completed:
        from app.workers.tasks.dynamic_analysis import run_dynamic_analysis

        run_dynamic_analysis.delay(str(run.id))

    logger.info(
        "Telemetry ingested: repo=%s run_id=%d phase=%s",
        repository,
        payload.workflow_run_id,
        payload.phase,
    )
    return {"status": "accepted", "telemetry_run_id": str(run.id)}


@router.post("/docker-build", role=Role.service, limit=LIMIT_INGEST, status_code=201)
async def ingest_docker_build(
    payload: DockerBuildPayload,
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, str]:
    """Ingest one image build's measured facts and queue its analysis.

    Authenticated by the same GitHub OIDC flow as ``/ingest`` — the repository
    comes from the token claims, never from the body.
    """
    repository: str = claims.get("repository", "")

    repo = _lookup_repo(session, repository)
    if not repo:
        logger.info(
            "Docker build telemetry received for unregistered repo %s — ignoring",
            repository,
        )
        return {"status": "accepted", "note": "repository_not_registered"}

    telemetry = DockerBuildTelemetry(
        repo_id=repo.id,
        workflow_run_id=payload.workflow_run_id,
        image_ref=payload.image_ref,
        dockerfile_path=payload.dockerfile_path,
        image_size_bytes=payload.image_size_bytes,
        context_size_bytes=payload.context_size_bytes,
        build_duration_ms=payload.build_duration_ms,
        cache_hit_ratio=payload.cache_hit_ratio,
        layers=json.dumps(payload.layers) if payload.layers is not None else None,
        containers=(
            json.dumps(payload.containers) if payload.containers is not None else None
        ),
    )
    session.add(telemetry)
    session.commit()
    session.refresh(telemetry)

    from app.workers.tasks.docker_telemetry_analysis import (
        run_docker_telemetry_analysis,
    )

    run_docker_telemetry_analysis.delay(
        str(telemetry.id),
        observed_builds=_count_observed_builds(session, repo.id, telemetry),
    )

    logger.info(
        "Docker build telemetry ingested: repo=%s run_id=%d image=%s",
        repository,
        payload.workflow_run_id,
        payload.image_ref,
    )
    return {"status": "accepted", "telemetry_id": str(telemetry.id)}


@router.post("/sample", role=Role.service, limit=LIMIT_INGEST, status_code=200)
async def ingest_sample(
    payload: SamplePayload,
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, str]:
    repository: str = claims.get("repository", "")

    repo = _lookup_repo(session, repository)
    if not repo:
        return {"status": "ok"}

    sample = TelemetryMetricSample(
        repo_id=repo.id,
        workflow_run_id=payload.workflow_run_id,
        cpu_percent=payload.cpu_percent,
        ram_used_mb=payload.ram_used_mb,
        disk_used_gb=payload.disk_used_gb,
        net_bytes_sent=payload.net_bytes_sent,
        net_bytes_recv=payload.net_bytes_recv,
        top_processes=(
            json.dumps(payload.top_processes) if payload.top_processes else None
        ),
    )

    try:
        session.add(sample)
        session.commit()
    except Exception:
        logger.exception("Failed to persist telemetry sample for repo %s", repository)
        session.rollback()

    return {"status": "ok"}


# ─── Read / analyze (user-session authenticated) ──────────────────────────────


def _enrichments_by_run(
    session: SessionDep, repo_id: uuid.UUID
) -> dict[uuid.UUID, list[DynamicEnrichment]]:
    """Group a repo's dynamic-enrichment findings by their telemetry run."""
    grouped: dict[uuid.UUID, list[DynamicEnrichment]] = {}
    rows = session.exec(
        select(DynamicEnrichment)
        .where(DynamicEnrichment.repo_id == repo_id)
        .order_by(col(DynamicEnrichment.created_at).desc())
    ).all()
    for row in rows:
        grouped.setdefault(row.telemetry_run_id, []).append(row)
    return grouped


@router.get(
    "/summary/{repo_id}", role=Role.org_member, response_model=TelemetrySummaryPublic
)
def get_telemetry_summary(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = 50,
    skip: int = 0,
) -> TelemetrySummaryPublic:
    """Average telemetry plus a per-run breakdown for a repository.

    Averages are computed over every telemetry run/sample the repo has; the
    ``runs`` list is paginated (most recent first) for the by-run table.
    """
    repo = authorize_repo(session, current_user, repo_id)

    all_runs = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .order_by(col(TelemetryRun.collected_at).desc())
    ).all()
    samples = session.exec(
        select(TelemetryMetricSample).where(TelemetryMetricSample.repo_id == repo.id)
    ).all()

    average = compute_telemetry_average(list(all_runs), list(samples))

    enrichments = _enrichments_by_run(session, repo.id)
    paged = all_runs[skip : skip + limit]
    runs = [to_telemetry_run_public(run, enrichments.get(run.id, [])) for run in paged]
    return TelemetrySummaryPublic(average=average, runs=runs)


@router.get(
    "/findings/{repo_id}",
    role=Role.org_member,
    response_model=list[DynamicEnrichmentPublic],
)
def get_telemetry_findings(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[DynamicEnrichmentPublic]:
    """A repo's runtime findings, for the Issues-page "Runtime" section."""
    repo = authorize_repo(session, current_user, repo_id)

    run_ids = {
        run.id: run.workflow_run_id
        for run in session.exec(
            select(TelemetryRun).where(TelemetryRun.repo_id == repo.id)
        ).all()
    }
    findings = session.exec(
        select(DynamicEnrichment)
        .where(DynamicEnrichment.repo_id == repo.id)
        .order_by(col(DynamicEnrichment.created_at).desc())
    ).all()
    return [
        to_dynamic_enrichment_public(f, run_ids.get(f.telemetry_run_id))
        for f in findings
    ]


@router.post(
    "/analyze/{repo_id}", role=Role.org_admin, limit=LIMIT_EXPENSIVE, status_code=202
)
def analyze_telemetry(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str | int]:
    """Re-run dynamic analysis over the repo's completed telemetry runs.

    The CI action collects telemetry during workflow runs; this re-derives
    findings from what is already stored. ``_enrich`` replaces a run's prior
    enrichments, so re-running is idempotent.
    """
    repo = authorize_repo(session, current_user, repo_id)
    if not repo.is_accessible:
        raise HTTPException(status_code=403, detail="Repository is not accessible")

    from app.workers.tasks.dynamic_analysis import run_dynamic_analysis

    runs = session.exec(
        select(TelemetryRun)
        .where(TelemetryRun.repo_id == repo.id)
        .where(TelemetryRun.phase == TelemetryPhase.completed)
    ).all()
    # Each run is a separate analysis, so re-deriving a repo's whole telemetry
    # history can cost hundreds at once. Checked up front so the user sees one
    # clear 402 instead of a fan-out that half-completes.
    #
    # Note that telemetry *ingest* is deliberately not gated: storing what CI
    # reported is cheap, and rejecting it would lose data the user cannot
    # re-send. Only the analysis it triggers is metered, and the worker refuses
    # that on its own if the allowance is spent.
    enforce_quota(
        session,
        current_user,
        repo.org_id,
        "analyses",
        requested=len(runs),
        engine=UsageEngine.telemetry,
    )
    for run in runs:
        run.dynamic_status = DynamicAnalysisStatus.queued
        session.add(run)
        run_dynamic_analysis.delay(str(run.id))
    session.commit()

    return {"status": "queued", "runs": len(runs)}
