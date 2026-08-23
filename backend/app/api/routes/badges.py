import uuid

from fastapi.responses import Response
from sqlmodel import Session, col, select

from app.api.deps import SessionDep
from app.api.mappers import latest_completed_scan
from app.api.router import Role, RoleRouter
from app.core.config import settings
from app.core.rate_limit import LIMIT_PUBLIC
from app.models import (
    Analysis,
    AnalysisStatus,
    DockerTarget,
    Repository,
    TerraformRoot,
)
from app.services.badge_renderer import (
    _GRADE_COLORS,
    render_badge,
    render_unknown_badge,
)
from app.services.badge_signing import (
    repo_badge_message,
    verify_badge,
)
from app.services.scoring import average_latest_scores, score_to_grade

router = RoleRouter(prefix="/badges", tags=["badges"])

_CACHE_HEADERS = {
    "Cache-Control": "max-age=300, s-maxage=300",
    "Content-Type": "image/svg+xml",
}


def _avg_grade_for_branch(
    session: Session, repo_id: uuid.UUID, branch: str
) -> str | None:
    """Average grade across latest completed analysis per workflow file on a branch.

    Returns a grade string (e.g. "A", "B", "N/A") or None when no analyses exist yet.
    "N/A" means the repo has no workflow files on this branch.
    None means analyses are pending or have not run yet.
    """
    analyses = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.branch == branch)
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(col(Analysis.workflow_file_id), col(Analysis.created_at).desc())
    ).all()

    avg, _ = average_latest_scores(list(analyses))
    if avg is not None:
        return score_to_grade(avg)

    has_no_workflows = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.branch == branch)
        .where(Analysis.status == AnalysisStatus.no_workflows)
        .limit(1)
    ).first()

    return "N/A" if has_no_workflows else None


@router.get(
    "/{owner}/{repo}/{branch}.svg",
    role=Role.guest,
    limit=LIMIT_PUBLIC,
    response_class=Response,
)
def get_badge(
    owner: str,
    repo: str,
    branch: str,
    session: SessionDep,
    sig: str | None = None,
) -> Response:
    full_name = f"{owner}/{repo}"

    db_repo = session.exec(
        select(Repository).where(Repository.full_name == full_name)
    ).first()

    # Private repos require a valid signature so a guessed full_name can't leak
    # their grade; public repos are served on plain URLs.
    if not db_repo or (
        db_repo.is_private
        and not verify_badge(repo_badge_message(owner, repo, branch), sig)
    ):
        return Response(
            content=render_unknown_badge(),
            headers=_CACHE_HEADERS,
        )

    grade = _avg_grade_for_branch(session, db_repo.id, branch)
    svg = render_unknown_badge() if grade is None else render_badge(grade)

    return Response(content=svg, headers=_CACHE_HEADERS)


@router.get("/{owner}/{repo}/{branch}.json", role=Role.guest, limit=LIMIT_PUBLIC)
def get_badge_json(
    owner: str,
    repo: str,
    branch: str,
    session: SessionDep,
    sig: str | None = None,
) -> dict[str, object]:
    """Shields.io-compatible JSON endpoint."""
    full_name = f"{owner}/{repo}"

    db_repo = session.exec(
        select(Repository).where(Repository.full_name == full_name)
    ).first()

    if not db_repo or (
        db_repo.is_private
        and not verify_badge(repo_badge_message(owner, repo, branch), sig)
    ):
        return {
            "schemaVersion": 1,
            "label": settings.PROJECT_NAME,
            "message": "not configured",
            "color": "lightgrey",
        }

    grade = _avg_grade_for_branch(session, db_repo.id, branch)

    if grade is None:
        return {
            "schemaVersion": 1,
            "label": settings.PROJECT_NAME,
            "message": "pending",
            "color": "lightgrey",
        }

    color = _GRADE_COLORS.get(grade, "#9CA3AF").lstrip("#")
    return {
        "schemaVersion": 1,
        "label": "GreenSecOps",
        "message": grade,
        "color": color,
        "cacheSeconds": 300,
    }


def _terraform_root_badge_grade(
    session: Session, root_id: uuid.UUID
) -> tuple[TerraformRoot | None, str | None]:
    root = session.get(TerraformRoot, root_id)
    if root is None:
        return None, None
    latest = latest_completed_scan(root)
    return root, (latest.grade if latest else None)


@router.get(
    "/terraform/{root_id}.svg",
    role=Role.guest,
    limit=LIMIT_PUBLIC,
    response_class=Response,
)
def get_terraform_root_badge(
    root_id: uuid.UUID,
    session: SessionDep,
    sig: str | None = None,
) -> Response:
    root, grade = _terraform_root_badge_grade(session, root_id)

    if root is None or (
        root.repository
        and root.repository.is_private
        and not verify_badge(str(root_id), sig)
    ):
        return Response(content=render_unknown_badge(), headers=_CACHE_HEADERS)

    svg = (
        render_unknown_badge()
        if grade is None
        else render_badge(grade, label="Terraform")
    )

    return Response(content=svg, headers=_CACHE_HEADERS)


@router.get("/terraform/{root_id}.json", role=Role.guest, limit=LIMIT_PUBLIC)
def get_terraform_root_badge_json(
    root_id: uuid.UUID,
    session: SessionDep,
    sig: str | None = None,
) -> dict[str, object]:
    """Shields.io-compatible JSON endpoint for a Terraform root's badge."""
    root, grade = _terraform_root_badge_grade(session, root_id)

    if root is None or (
        root.repository
        and root.repository.is_private
        and not verify_badge(str(root_id), sig)
    ):
        return {
            "schemaVersion": 1,
            "label": "Terraform",
            "message": "not configured",
            "color": "lightgrey",
        }

    if grade is None:
        return {
            "schemaVersion": 1,
            "label": "Terraform",
            "message": "pending",
            "color": "lightgrey",
        }

    color = _GRADE_COLORS.get(grade, "#9CA3AF").lstrip("#")
    return {
        "schemaVersion": 1,
        "label": "Terraform",
        "message": grade,
        "color": color,
        "cacheSeconds": 300,
    }


def _docker_target_badge_grade(
    session: Session, target_id: uuid.UUID
) -> tuple[DockerTarget | None, str | None]:
    target = session.get(DockerTarget, target_id)
    if target is None:
        return None, None
    latest = latest_completed_scan(target)
    return target, (latest.grade if latest else None)


@router.get(
    "/docker/{target_id}.svg",
    role=Role.guest,
    limit=LIMIT_PUBLIC,
    response_class=Response,
)
def get_docker_target_badge(
    target_id: uuid.UUID,
    session: SessionDep,
    sig: str | None = None,
) -> Response:
    target, grade = _docker_target_badge_grade(session, target_id)

    # An unknown badge for both the missing and the unauthorized case: a badge
    # is unauthenticated, so distinguishing them would leak which private
    # targets exist.
    if target is None or (
        target.repository
        and target.repository.is_private
        and not verify_badge(str(target_id), sig)
    ):
        return Response(content=render_unknown_badge(), headers=_CACHE_HEADERS)

    svg = (
        render_unknown_badge() if grade is None else render_badge(grade, label="Docker")
    )

    return Response(content=svg, headers=_CACHE_HEADERS)


@router.get("/docker/{target_id}.json", role=Role.guest, limit=LIMIT_PUBLIC)
def get_docker_target_badge_json(
    target_id: uuid.UUID,
    session: SessionDep,
    sig: str | None = None,
) -> dict[str, object]:
    """Shields.io-compatible JSON endpoint for a Docker target's badge."""
    target, grade = _docker_target_badge_grade(session, target_id)

    if target is None or (
        target.repository
        and target.repository.is_private
        and not verify_badge(str(target_id), sig)
    ):
        return {
            "schemaVersion": 1,
            "label": "Docker",
            "message": "not configured",
            "color": "lightgrey",
        }

    if grade is None:
        return {
            "schemaVersion": 1,
            "label": "Docker",
            "message": "pending",
            "color": "lightgrey",
        }

    color = _GRADE_COLORS.get(grade, "#9CA3AF").lstrip("#")
    return {
        "schemaVersion": 1,
        "label": "Docker",
        "message": grade,
        "color": color,
        "cacheSeconds": 300,
    }
