import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    authorize_repo,
    get_or_404,
    user_org_ids,
)
from app.api.mappers import (
    to_docker_finding_public,
    to_docker_fix_public,
    to_docker_scan_public,
    to_docker_target_public,
)
from app.models import (
    DockerFilePublic,
    DockerFinding,
    DockerFindingPublic,
    DockerFix,
    DockerFixPublic,
    DockerScan,
    DockerScanPublic,
    DockerTarget,
    DockerTargetCreate,
    DockerTargetPublic,
    LLMProvider,
    Repository,
)
from app.models.enums import FixStatus
from app.services import state_machines as sm
from app.services.delivery_pr import docker_fix_branch
from app.services.docker.merge import classify_docker_file
from app.workers.tasks.docker_analysis import _fetch_docker_files, run_docker_scan
from app.workers.tasks.docker_fix_delivery import deliver_docker_fixes
from app.workers.tasks.docker_fix_generation import run_docker_fix_generation
from app.workers.tasks.fix_generation import resolve_llm_provider

router = APIRouter(prefix="/docker-targets", tags=["docker"])

# Fix statuses a worker is actively processing — a fix here must not be reset
# out from under the worker (mirrors fixes.IN_FLIGHT_STATUSES).
_IN_FLIGHT_FIX_STATUSES = (
    FixStatus.pending,
    FixStatus.generating,
    FixStatus.delivering,
)


class DockerFixGenerateRequest(BaseModel):
    # Optional subset of finding ids to fix; omit to fix every open finding in
    # the target. Findings are grouped by file into one whole-file fix each.
    finding_ids: list[uuid.UUID] | None = None


def _normalize_root_path(raw: str) -> str:
    """Collapse the several spellings of "the repository root" to ``""``.

    ``uq_docker_target_repo_path`` treats ``""``, ``"/"`` and ``"./"`` as three
    distinct paths, so without this a repo could accumulate duplicate
    repo-root targets that each scan the same files.
    """
    stripped = raw.strip().strip("/")
    return "" if stripped in ("", ".") else stripped


def _get_target_for_user(
    target_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> DockerTarget:
    # Both the missing and the unauthorized case return the same 404 detail so
    # the API never discloses that another tenant's target exists.
    target = get_or_404(
        session, DockerTarget, target_id, detail="Docker target not found"
    )
    authorize_repo(
        session, current_user, target.repo_id, detail="Docker target not found"
    )
    return target


@router.post("/", response_model=DockerTargetPublic, status_code=201)
def create_docker_target(
    target_in: DockerTargetCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> DockerTargetPublic:
    """Register an extra Docker target.

    Not normally needed: installation sync creates a repository-root target
    automatically. This exists for monorepos that want each sub-project graded
    separately.
    """
    authorize_repo(session, current_user, target_in.repo_id)
    repo = get_or_404(
        session, Repository, target_in.repo_id, detail="Repository not found"
    )
    normalized_path = _normalize_root_path(target_in.root_path)
    existing = session.exec(
        select(DockerTarget)
        .where(DockerTarget.repo_id == repo.id)
        .where(DockerTarget.root_path == normalized_path)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This path is already configured")
    target = DockerTarget(repo_id=repo.id, root_path=normalized_path)
    session.add(target)
    session.commit()
    session.refresh(target)
    return to_docker_target_public(target)


@router.get("/", response_model=list[DockerTargetPublic])
def list_docker_targets(
    session: SessionDep,
    current_user: CurrentUser,
    repo_id: uuid.UUID | None = None,
) -> list[DockerTargetPublic]:
    """List targets for one repo, or every target the user can see.

    Dual-mode so the same endpoint powers both the org-wide Infrastructure
    page and the per-repo Docker tab.
    """
    if repo_id:
        authorize_repo(session, current_user, repo_id)
        query = select(DockerTarget).where(DockerTarget.repo_id == repo_id)
    else:
        query = select(DockerTarget)
        if not current_user.is_superuser:
            query = query.join(
                Repository,
                # Same SQLModel/mypy limitation the Terraform route documents:
                # a model-attribute comparison isn't seen as a ColumnElement.
                DockerTarget.repo_id == Repository.id,  # type: ignore[arg-type]
            ).where(col(Repository.org_id).in_(user_org_ids(session, current_user)))
    targets = session.exec(query.order_by(col(DockerTarget.root_path))).all()
    return [to_docker_target_public(t) for t in targets]


@router.patch("/{target_id}/toggle")
def toggle_docker_target(
    target_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> dict[str, str | bool]:
    target = _get_target_for_user(target_id, session, current_user)
    target.enabled = not target.enabled
    session.add(target)
    session.commit()
    return {"id": str(target.id), "enabled": target.enabled}


@router.delete("/{target_id}", status_code=204)
def delete_docker_target(
    target_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> None:
    target = _get_target_for_user(target_id, session, current_user)
    session.delete(target)
    session.commit()


@router.post("/{target_id}/scan", status_code=202)
def trigger_docker_scan(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    branch: str | None = None,
) -> dict[str, str]:
    target = _get_target_for_user(target_id, session, current_user)
    if not target.enabled:
        raise HTTPException(status_code=403, detail="Docker target is disabled")
    run_docker_scan.delay(
        docker_target_id=str(target.id), branch=branch or "", trigger="manual"
    )
    return {"status": "queued", "docker_target_id": str(target_id)}


@router.get("/{target_id}/scans", response_model=list[DockerScanPublic])
def list_docker_scans(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = 20,
) -> list[DockerScanPublic]:
    target = _get_target_for_user(target_id, session, current_user)
    scans = session.exec(
        select(DockerScan)
        .where(DockerScan.docker_target_id == target.id)
        .order_by(col(DockerScan.created_at).desc())
        .limit(limit)
    ).all()
    return [to_docker_scan_public(s) for s in scans]


@router.get("/{target_id}/findings", response_model=list[DockerFindingPublic])
def list_docker_findings(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    include_resolved: bool = False,
) -> list[DockerFindingPublic]:
    target = _get_target_for_user(target_id, session, current_user)
    query = select(DockerFinding).where(DockerFinding.docker_target_id == target.id)
    if not include_resolved:
        query = query.where(col(DockerFinding.resolved_at).is_(None))
    findings = session.exec(
        query.order_by(col(DockerFinding.file_path), col(DockerFinding.line_start))
    ).all()
    return [to_docker_finding_public(f) for f in findings]


@router.get("/{target_id}/files", response_model=list[DockerFilePublic])
def list_docker_files(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    ref: str | None = None,
) -> list[DockerFilePublic]:
    """Live source of the target's Docker files, fetched from GitHub.

    Docker files aren't persisted, so this reaches through to GitHub on each
    call — any failure there is upstream's, hence 502 rather than 500.
    """
    target = _get_target_for_user(target_id, session, current_user)
    repo = get_or_404(
        session, Repository, target.repo_id, detail="Repository not found"
    )
    try:
        fetched = _fetch_docker_files(repo, target.root_path, ref=ref)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail="Failed to fetch Docker files from GitHub"
        ) from exc
    return [
        DockerFilePublic(
            path=f.path,
            raw_content=f.content,
            # Classified here rather than in the viewer so the frontend never
            # has to re-derive Dockerfile-vs-Compose from the filename.
            kind=classify_docker_file(f.path) or "dockerfile",
        )
        for f in sorted(fetched, key=lambda f: f.path)
    ]


@router.get("/{target_id}/fixes", response_model=list[DockerFixPublic])
def list_docker_fixes(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[DockerFixPublic]:
    _get_target_for_user(target_id, session, current_user)
    fixes = session.exec(
        select(DockerFix)
        .where(DockerFix.docker_target_id == target_id)
        .order_by(col(DockerFix.created_at).desc())
    ).all()
    return [to_docker_fix_public(f) for f in fixes]


@router.post("/{target_id}/fixes", status_code=202)
def trigger_docker_fix_generation(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: DockerFixGenerateRequest | None = None,
    force: bool = False,
) -> dict[str, str | int]:
    """Generate LLM fixes for a target's open findings, one whole-file fix each."""
    target = _get_target_for_user(target_id, session, current_user)
    repo = get_or_404(
        session, Repository, target.repo_id, detail="Repository not found"
    )

    query = (
        select(DockerFinding)
        .where(DockerFinding.docker_target_id == target_id)
        .where(col(DockerFinding.resolved_at).is_(None))
        .where(col(DockerFinding.ignored_at).is_(None))
    )
    if body and body.finding_ids:
        query = query.where(col(DockerFinding.id).in_(body.finding_ids))
    findings = list(session.exec(query).all())
    if not findings:
        return {"status": "no_findings", "queued": 0}

    # One LLM call per file, not per finding: the model rewrites the whole file
    # once with every finding in front of it, which is both cheaper and avoids
    # two fixes racing to patch the same lines.
    by_file: dict[str, list[DockerFinding]] = defaultdict(list)
    for finding in findings:
        by_file[finding.file_path].append(finding)

    provider_str, model_str = resolve_llm_provider(repo)
    queued = 0
    for file_path, group in by_file.items():
        fix = _prepare_pending_fix(
            session, target_id, file_path, provider_str, model_str, force
        )
        if fix is None:
            continue
        session.flush()
        for finding in group:
            finding.fix_id = fix.id
            session.add(finding)
        session.commit()
        run_docker_fix_generation.delay(finding_ids=[str(f.id) for f in group])
        queued += 1

    return {"status": "queued", "queued": queued}


def _prepare_pending_fix(
    session: SessionDep,
    target_id: uuid.UUID,
    file_path: str,
    provider_str: str,
    model_str: str,
    force: bool,
) -> DockerFix | None:
    """Create or reuse the single (target, file) fix row, leaving it ``pending``.

    Returns ``None`` when a fix is already in flight, or already resolved and
    not being forced — nothing to (re)queue.
    """
    existing = session.exec(
        select(DockerFix)
        .where(DockerFix.docker_target_id == target_id)
        .where(DockerFix.file_path == file_path)
    ).first()
    if existing is not None:
        if existing.status in _IN_FLIGHT_FIX_STATUSES:
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
        return existing

    fix = DockerFix(
        docker_target_id=target_id,
        file_path=file_path,
        llm_provider=LLMProvider(provider_str),
        llm_model=model_str,
        status=FixStatus.pending,
    )
    session.add(fix)
    return fix


@router.post("/{target_id}/deliver", status_code=202)
def trigger_docker_delivery(
    target_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    force: bool = False,
) -> dict[str, str]:
    """Deliver the target's ready fixes as a single PR (branch per target)."""
    target = _get_target_for_user(target_id, session, current_user)
    deliver_docker_fixes.delay(docker_target_id=str(target.id), force=force)
    return {
        "status": "queued",
        "docker_target_id": str(target_id),
        # Returned so the UI can match this target against an already-open PR.
        "pr_branch": docker_fix_branch(target.id),
    }
