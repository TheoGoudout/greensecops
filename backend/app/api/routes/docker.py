import uuid
from collections import defaultdict
from typing import Any

from fastapi import Query
from pydantic import BaseModel
from sqlmodel import col, select

from app.api import engine_routes as shared
from app.api.deps import CurrentUser, GitHubOidcClaims, SessionDep
from app.api.mappers import (
    to_docker_build_telemetry_public,
    to_docker_finding_public,
    to_docker_fix_public,
    to_docker_runtime_finding_public,
    to_docker_scan_public,
    to_docker_target_public,
)
from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE, LIMIT_INGEST
from app.models import (
    DockerBuildEnrichment,
    DockerBuildTelemetry,
    DockerBuildTelemetryPublic,
    DockerFilePublic,
    DockerFindingPublic,
    DockerFixPublic,
    DockerRuntimeFindingPublic,
    DockerScanPublic,
    DockerTarget,
    DockerTargetCreate,
    DockerTargetPublic,
    Engine,
    FindingUpdate,
    FixGenerateRequest,
    Rule,
    ScanTargetUpdate,
    TargetAction,
)
from app.services.docker.merge import classify_docker_file
from app.services.engines import DOCKER_ENGINE as SPEC
from app.services.github.fetch import (
    fetch_docker_files as _fetch_docker_files,
)
from app.workers.tasks.docker_analysis import run_docker_scan
from app.workers.tasks.docker_fix_delivery import deliver_docker_fixes
from app.workers.tasks.docker_fix_generation import run_docker_fix_generation

# The bodies live in api/engine_routes.py, shared with Docker and Ansible. The
# functions stay one per endpoint here because their names become the OpenAPI
# operation ids, and so the generated clients' method names.
router = RoleRouter(prefix="/docker", tags=["docker"])


@router.post(
    "/targets", role=Role.user, response_model=DockerTargetPublic, status_code=201
)
def create_target(
    target_in: DockerTargetCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> DockerTargetPublic:
    """Register an extra Docker target.

    Not normally needed: installation sync creates a repository-root target
    automatically. This exists for monorepos that want each sub-project graded
    separately.
    """
    target = shared.create_target(
        SPEC,
        session,
        current_user,
        target_in.repo_id,
        target_in.root_path,
        allow_repo_root=True,
    )
    return to_docker_target_public(target)


@router.get("/targets", role=Role.user, response_model=list[DockerTargetPublic])
def list_targets(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
) -> list[DockerTargetPublic]:
    """List Docker targets. Omit ``repo_id`` for the org-wide Infrastructure
    page (every target across every repo the user can access); pass it to
    scope to one repo."""
    return [
        to_docker_target_public(target, activity)
        for target, activity in shared.list_targets(
            SPEC, session, current_user, repo_id
        )
    ]


@router.patch(
    "/targets/{target_id}", role=Role.org_admin, response_model=DockerTargetPublic
)
def update_target(
    target_id: uuid.UUID,
    body: ScanTargetUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> DockerTargetPublic:
    return to_docker_target_public(
        *shared.update_target(SPEC, target_id, body, session, current_user)
    )


@router.delete("/targets/{target_id}", role=Role.org_admin, status_code=204)
def delete_target(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    shared.delete_target(SPEC, target_id, session, current_user)


@router.post(
    "/targets/{target_id}/scans",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def trigger_scan(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> dict[str, str]:
    return shared.trigger_target_scan(
        SPEC, run_docker_scan, target_id, session, current_user, branch
    )


@router.get(
    "/targets/{target_id}/scans",
    role=Role.org_member,
    response_model=list[DockerScanPublic],
)
def list_scans(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[DockerScanPublic]:
    return [
        to_docker_scan_public(s)
        for s in shared.list_target_scans(SPEC, target_id, session, current_user, limit)
    ]


@router.get(
    "/targets/{target_id}/findings",
    role=Role.org_member,
    response_model=list[DockerFindingPublic],
)
def list_findings(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[DockerFindingPublic]:
    return [
        to_docker_finding_public(f)
        for f in shared.list_target_findings(
            SPEC, target_id, session, current_user, include_resolved
        )
    ]


@router.get(
    "/findings/{docker_finding_id}",
    role=Role.org_member,
    response_model=DockerFindingPublic,
)
def get_finding(
    docker_finding_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> DockerFindingPublic:
    return to_docker_finding_public(
        shared.get_finding_for_user(SPEC, docker_finding_id, session, current_user)
    )


@router.patch(
    "/findings/{docker_finding_id}",
    role=Role.org_admin,
    response_model=DockerFindingPublic,
)
def update_finding(
    docker_finding_id: uuid.UUID,
    body: FindingUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> DockerFindingPublic:
    return to_docker_finding_public(
        shared.update_finding_for_user(
            SPEC, docker_finding_id, body, session, current_user
        )
    )


@router.get(
    "/targets/{target_id}/files",
    role=Role.org_member,
    response_model=list[DockerFilePublic],
)
def list_files(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None = None,
) -> list[DockerFilePublic]:
    """The target's live Docker source, fetched from GitHub on demand."""
    return [
        DockerFilePublic(
            path=f.path,
            raw_content=f.content,
            # Classified here rather than in the viewer so the frontend never
            # has to re-derive Dockerfile-vs-Compose from the filename.
            kind=classify_docker_file(f.path) or "dockerfile",
        )
        for f in shared.fetch_target_files(
            SPEC, target_id, session, current_user, ref, _fetch_docker_files
        )
    ]


# How many measured builds the Runtime tab shows per target. Build telemetry
# accrues one row per image per workflow run, so an unbounded query would grow
# without limit on an active repo.
_RUNTIME_PAGE_SIZE = 25


def _owning_root_path(dockerfile_path: str | None, roots: list[str]) -> str:
    """Which target a measured build belongs to: the longest root that prefixes it.

    Telemetry is stored per repository, but targets partition a repository. A
    build of ``backend/Dockerfile`` belongs to the ``backend`` target when one
    exists and to the repo-root target otherwise, and it must appear under
    exactly one — listing it under both would double-count it in a monorepo.

    A build with no ``dockerfile_path`` (the action input was not set) falls to
    the repo-root target, which is the only one that can claim it.
    """
    if not dockerfile_path:
        return ""
    best = ""
    for root in roots:
        if not root:
            continue
        if dockerfile_path == root or dockerfile_path.startswith(f"{root}/"):
            if len(root) > len(best):
                best = root
    return best


@router.get(
    "/targets/{target_id}/runtime-findings",
    role=Role.org_member,
    response_model=list[DockerBuildTelemetryPublic],
)
def list_runtime_findings(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[DockerBuildTelemetryPublic]:
    """Measured builds for this target, each with the findings it produced."""
    target = shared.get_target_for_user(SPEC, target_id, session, current_user)

    roots = list(
        session.exec(
            select(DockerTarget.root_path).where(DockerTarget.repo_id == target.repo_id)
        ).all()
    )
    # Telemetry is stored per repository but shown per target, and which target
    # owns a row is a longest-prefix match that SQL cannot express cleanly. So
    # the fetch is widened by the number of targets before filtering: limiting
    # to a page first would let a busy sibling target crowd this one's builds
    # out of the window entirely.
    rows = session.exec(
        select(DockerBuildTelemetry)
        .where(DockerBuildTelemetry.repo_id == target.repo_id)
        .order_by(col(DockerBuildTelemetry.collected_at).desc())
        .limit(_RUNTIME_PAGE_SIZE * max(len(roots), 1))
    ).all()
    mine = [
        row
        for row in rows
        if _owning_root_path(row.dockerfile_path, roots) == target.root_path
    ][:_RUNTIME_PAGE_SIZE]
    if not mine:
        return []

    enrichments = session.exec(
        select(DockerBuildEnrichment).where(
            col(DockerBuildEnrichment.telemetry_id).in_([row.id for row in mine])
        )
    ).all()

    # One catalog lookup for the whole page rather than one per finding.
    slugs = {e.rule_slug for e in enrichments}
    rules = (
        session.exec(select(Rule).where(col(Rule.slug).in_(slugs))).all()
        if slugs
        else []
    )
    by_slug = {rule.slug: rule for rule in rules}

    by_telemetry: dict[uuid.UUID, list[DockerRuntimeFindingPublic]] = defaultdict(list)
    for enrichment in enrichments:
        by_telemetry[enrichment.telemetry_id].append(
            to_docker_runtime_finding_public(
                enrichment, by_slug.get(enrichment.rule_slug)
            )
        )

    return [
        to_docker_build_telemetry_public(row, by_telemetry.get(row.id, []))
        for row in mine
    ]


@router.get("/fixes", role=Role.user, response_model=list[DockerFixPublic])
def list_repository_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID,
) -> list[DockerFixPublic]:
    """Every fix across a repository's Docker targets.

    The pull-requests tab reads it to decide whether "Update PR" may be
    pressed, without a request per card.
    """
    return [
        to_docker_fix_public(f)
        for f in shared.list_fixes_for_repo(SPEC, session, current_user, repo_id)
    ]


@router.get(
    "/targets/{target_id}/fixes",
    role=Role.org_member,
    response_model=list[DockerFixPublic],
)
def list_fixes(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[DockerFixPublic]:
    return [
        to_docker_fix_public(f)
        for f in shared.list_target_fixes(SPEC, target_id, session, current_user)
    ]


@router.post(
    "/targets/{target_id}/fixes",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def generate_fixes(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: FixGenerateRequest | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate LLM fixes for a target's open findings, one whole-file fix each."""
    return shared.generate_target_fixes(
        SPEC,
        run_docker_fix_generation,
        target_id,
        session,
        current_user,
        body.finding_ids if body else None,
        force,
    )


class DockerRuntimeFixRequest(BaseModel):
    # Which measured findings to act on. They must all belong to builds of the
    # same Dockerfile, since the fix rewrites one file.
    enrichment_ids: list[uuid.UUID]


@router.post(
    "/targets/{target_id}/runtime-fixes",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def generate_runtime_fixes(
    target_id: uuid.UUID,
    body: DockerRuntimeFixRequest,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate a fix from measured runtime findings.

    The join back to source is ``DockerBuildTelemetry.dockerfile_path``: without
    it a measurement describes a container but names no file, and there is
    nothing to rewrite. Builds reported without the action's ``dockerfile_path``
    input are therefore skipped rather than guessed at.

    Any open static findings for the same file are folded into the same call —
    one LLM rewrite per file, exactly as the static route does, so a runtime fix
    and a static fix can never race to patch the same lines.
    """
    target = shared.get_target_for_user(SPEC, target_id, session, current_user)
    shared.require_target_idle(SPEC, session, target_id, TargetAction.generate)

    enrichments = list(
        session.exec(
            select(DockerBuildEnrichment)
            .where(col(DockerBuildEnrichment.id).in_(body.enrichment_ids))
            .where(DockerBuildEnrichment.repo_id == target.repo_id)
        ).all()
    )
    if not enrichments:
        return {"status": "no_findings", "queued": 0}

    paths = dict(
        session.exec(
            select(DockerBuildTelemetry.id, DockerBuildTelemetry.dockerfile_path).where(
                col(DockerBuildTelemetry.id).in_({e.telemetry_id for e in enrichments})
            )
        ).all()
    )
    enrichments_by_file: dict[str, list[DockerBuildEnrichment]] = defaultdict(list)
    for enrichment in enrichments:
        path = paths.get(enrichment.telemetry_id)
        if path:
            enrichments_by_file[path].append(enrichment)
    if not enrichments_by_file:
        return {"status": "no_dockerfile_path", "queued": 0}

    # The static findings each fix will link, file by file.
    static_by_file = {
        path: shared.open_findings_by_file(
            SPEC, session, target_id, file_path=path
        ).get(path, [])
        for path in enrichments_by_file
    }

    def dispatch(file_path: str, static: list[Any]) -> None:
        run_docker_fix_generation.delay(
            finding_ids=[str(f.id) for f in static],
            enrichment_ids=[str(e.id) for e in enrichments_by_file[file_path]],
            docker_target_id=str(target_id),
            file_path=file_path,
        )

    return shared.queue_file_fixes(
        SPEC, session, current_user, target, static_by_file, force, dispatch
    )


@router.post(
    "/targets/{target_id}/deliveries",
    role=Role.org_admin,
    limit=LIMIT_EXPENSIVE,
    status_code=202,
)
def deliver_fixes(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver the target's ready fixes as a single PR (branch per target)."""
    return shared.deliver_target_fixes(
        SPEC, deliver_docker_fixes, target_id, session, current_user, force
    )


@router.get("/sarif", role=Role.service, limit=LIMIT_INGEST)
def get_sarif(
    session: SessionDep,
    claims: GitHubOidcClaims,
) -> dict[str, Any]:
    """This repository's open Docker findings as a SARIF 2.1.0 log.

    For a workflow that runs ``upload-sarif`` on its own runner, so a team can
    read GreenSecOps findings in the security tab and on the PR diff without
    installing the App. Authenticated by the run's GitHub OIDC token: the
    repository comes from the signed claim, so no id is needed and none would
    be honoured.
    """
    return shared.sarif_for_claims(Engine.docker, session, claims)


@router.post("/scans", role=Role.service, limit=LIMIT_EXPENSIVE, status_code=202)
def trigger_scans_for_code_scanning(
    session: SessionDep,
    claims: GitHubOidcClaims,
    branch: str | None = None,
) -> dict[str, str]:
    """Re-scan every enabled Docker target in the calling repository.

    Authenticated by the run's GitHub OIDC token, so the repository is the one
    the token was minted for and cannot be chosen by the caller.
    """
    return shared.trigger_code_scanning_scans(
        SPEC, run_docker_scan, session, claims, branch
    )
