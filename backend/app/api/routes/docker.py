import uuid

from fastapi import APIRouter, HTTPException
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
    to_docker_scan_public,
    to_docker_target_public,
)
from app.models import (
    DockerFilePublic,
    DockerFinding,
    DockerFindingPublic,
    DockerScan,
    DockerScanPublic,
    DockerTarget,
    DockerTargetCreate,
    DockerTargetPublic,
    Repository,
)
from app.services.docker.merge import classify_docker_file
from app.workers.tasks.docker_analysis import _fetch_docker_files, run_docker_scan

router = APIRouter(prefix="/docker-targets", tags=["docker"])


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
