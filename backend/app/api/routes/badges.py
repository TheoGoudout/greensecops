from fastapi import APIRouter
from fastapi.responses import Response
from sqlmodel import select

from app.api.deps import SessionDep
from app.models import Analysis, AnalysisStatus, Repository
from app.services.badge_renderer import render_badge, render_unknown_badge

router = APIRouter(prefix="/badges", tags=["badges"])

_CACHE_HEADERS = {
    "Cache-Control": "max-age=300, s-maxage=300",
    "Content-Type": "image/svg+xml",
}


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

    latest = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == db_repo.id)
        .where(Analysis.branch == branch)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()

    grade = latest.grade if latest and latest.grade else None
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
            "label": "GreenSecOps",
            "message": "not configured",
            "color": "lightgrey",
        }

    latest = session.exec(
        select(Analysis)
        .where(Analysis.repo_id == db_repo.id)
        .where(Analysis.branch == branch)
        .where(Analysis.status == AnalysisStatus.completed)
        .order_by(Analysis.created_at.desc())  # type: ignore[arg-type]
    ).first()

    if not latest or not latest.grade:
        return {
            "schemaVersion": 1,
            "label": "GreenSecOps",
            "message": "pending",
            "color": "lightgrey",
        }

    from app.services.badge_renderer import _GRADE_COLORS

    color = _GRADE_COLORS.get(latest.grade, "#9CA3AF").lstrip("#")
    return {
        "schemaVersion": 1,
        "label": "GreenSecOps",
        "message": latest.grade,
        "color": color,
        "cacheSeconds": 300,
    }
