import uuid

from fastapi import APIRouter
from fastapi.responses import Response
from sqlmodel import Session, select

from app.api.deps import SessionDep
from app.core.config import settings
from app.models import Analysis, AnalysisStatus, Repository
from app.services.badge_renderer import render_badge, render_unknown_badge
from app.services.scoring import score_to_grade

router = APIRouter(prefix="/badges", tags=["badges"])

_CACHE_HEADERS = {
    "Cache-Control": "max-age=300, s-maxage=300",
    "Content-Type": "image/svg+xml",
}


def _avg_grade_for_branch(
    session: Session, repo_id: uuid.UUID, branch: str
) -> str | None:
    """Average grade across latest completed analysis per workflow file on a branch."""
    analyses = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == repo_id)
        .where(Analysis.branch == branch)
        .where(Analysis.status == AnalysisStatus.completed)
        .where(Analysis.score.isnot(None))  # type: ignore[union-attr]
        .order_by(Analysis.workflow_file_id, Analysis.created_at.desc())  # type: ignore[arg-type]
    ).all()

    seen: set[uuid.UUID] = set()
    latest_per_file: list[Analysis] = []
    for a in analyses:
        if a.workflow_file_id not in seen:
            seen.add(a.workflow_file_id)
            latest_per_file.append(a)

    if not latest_per_file:
        return None

    avg = sum(a.score for a in latest_per_file if a.score is not None) / len(  # type: ignore[arg-type]
        latest_per_file
    )
    return score_to_grade(avg)


@router.get("/{owner}/{repo}/{branch}.svg", response_class=Response)
def get_badge(
    owner: str,
    repo: str,
    branch: str,
    session: SessionDep,
) -> Response:
    full_name = f"{owner}/{repo}"

    db_repo = session.exec(
        select(Repository).where(Repository.full_name == full_name)
    ).first()

    if not db_repo:
        return Response(
            content=render_unknown_badge(),
            headers=_CACHE_HEADERS,
        )

    grade = _avg_grade_for_branch(session, db_repo.id, branch)
    svg = render_badge(grade) if grade else render_unknown_badge()

    return Response(content=svg, headers=_CACHE_HEADERS)


@router.get("/{owner}/{repo}/{branch}.json")
def get_badge_json(
    owner: str,
    repo: str,
    branch: str,
    session: SessionDep,
) -> dict[str, object]:
    """Shields.io-compatible JSON endpoint."""
    full_name = f"{owner}/{repo}"

    db_repo = session.exec(
        select(Repository).where(Repository.full_name == full_name)
    ).first()

    if not db_repo:
        return {
            "schemaVersion": 1,
            "label": settings.PROJECT_NAME,
            "message": "not configured",
            "color": "lightgrey",
        }

    grade = _avg_grade_for_branch(session, db_repo.id, branch)

    if not grade:
        return {
            "schemaVersion": 1,
            "label": settings.PROJECT_NAME,
            "message": "pending",
            "color": "lightgrey",
        }

    from app.services.badge_renderer import _GRADE_COLORS

    color = _GRADE_COLORS.get(grade, "#9CA3AF").lstrip("#")
    return {
        "schemaVersion": 1,
        "label": "GreenSecOps",
        "message": grade,
        "color": color,
        "cacheSeconds": 300,
    }
