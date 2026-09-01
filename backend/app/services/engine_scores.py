"""Per-engine scores for a repository, from each engine's latest scans.

A repository is graded five times over — once per engine — and only the CI
number was ever computed. ``RepositoryPublic.grade`` is the workflow average
(``scoring.compute_avg_scores_batch``), so the Docker page fell back to the
*worst* of its targets' grades and the Infrastructure page showed none at all.
Worst-of is not an average: one bad Dockerfile among ten dragged the header to
its grade, which is not what the same page's own summary said.

The "latest scan per target" helpers live here rather than in
``api/routes/overview.py`` because two callers now need them and a service is
where both may reach — the dashboard aggregates them across an org, this
aggregates them within one repository.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import CloudAccount, Engine, Repository
from app.services.engines import OVERVIEW_SPECS, OverviewSpec
from app.services.scoring import compute_avg_scores_batch, score_to_grade


def latest_scan_order(spec: OverviewSpec) -> list[Any]:
    """How to pick a target's most recent scan.

    Two orderings already exist in this codebase and they disagree:
    ``mappers/base.latest_completed_scan`` takes ``max(created_at)``, while
    ``get_issue_stats``' correlated subquery orders by ``completed_at`` first.
    Rather than silently picking one, each engine keeps the ordering its own
    endpoints already use — so a Docker grade computed here always matches what
    ``GET /docker/targets`` reports, and CI counts always match
    ``GET /workflow/findings/stats``.
    """
    order = [col(spec.scan_model.created_at).desc()]
    if spec.scan_orders_by_completed_at:
        order.insert(0, col(spec.scan_model.completed_at).desc().nulls_last())
    return order


def latest_scan_subquery(spec: OverviewSpec, *, completed_only: bool) -> Any:
    """One row per target: its most recent scan.

    A window function rather than a correlated subquery because the callers
    touch every target in an org or a repo — this is one sorted pass over the
    scan table instead of an index probe per target. (``DISTINCT ON`` would be
    tighter still, but it is Postgres-only and appears nowhere else here.)
    """
    query = select(  # type: ignore[call-overload]
        spec.scan_target_fk.label("target_id"),
        col(spec.scan_model.status).label("status"),
        col(spec.scan_model.score).label("score"),
        col(spec.scan_model.grade).label("grade"),
        col(spec.scan_model.completed_at).label("completed_at"),
        col(spec.scan_model.created_at).label("created_at"),
        func.row_number()
        .over(
            partition_by=spec.scan_target_fk,
            order_by=latest_scan_order(spec),
        )
        .label("rn"),
    )
    if completed_only:
        query = query.where(spec.scan_model.status == spec.scan_completed)
    inner = query.subquery()
    return select(inner).where(inner.c.rn == 1).subquery()


def _average_by_repo(
    session: Session, spec: OverviewSpec, repo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """Mean latest-completed-scan score per repository, for one engine.

    Repositories with no scored target are simply absent — an engine that has
    never run on a repo has no grade, which is a different statement from a
    bad one.
    """
    latest = latest_scan_subquery(spec, completed_only=True)
    target = spec.target_model

    if spec.key is Engine.cloud:
        # A cloud account hangs off an organisation, not a repository, so a
        # repo's cloud posture *is* its org's — which is exactly what the repo's
        # Cloud tab lists. Grouped by repository so every repo in an org reports
        # the same number, matching what that tab shows.
        rows = session.exec(
            select(col(Repository.id), func.avg(latest.c.score))
            .select_from(Repository)
            .join(CloudAccount, col(CloudAccount.org_id) == Repository.org_id)
            .join(latest, latest.c.target_id == CloudAccount.id)
            .where(col(Repository.id).in_(repo_ids))
            .where(latest.c.score.isnot(None))
            .group_by(col(Repository.id))
        ).all()
        return {repo_id: float(avg) for repo_id, avg in rows if avg is not None}

    query = (
        select(col(target.repo_id), func.avg(latest.c.score))
        .select_from(target)
        .join(latest, latest.c.target_id == target.id)
        .where(col(target.repo_id).in_(repo_ids))
        .where(latest.c.score.isnot(None))
    )
    if spec.target_join is not None:
        join_model, onclause = spec.target_join
        query = query.join(join_model, onclause)
    if spec.target_extra is not None:
        query = query.where(spec.target_extra)
    rows = session.exec(query.group_by(col(target.repo_id))).all()
    return {repo_id: float(avg) for repo_id, avg in rows if avg is not None}


def repo_engine_grades(
    session: Session, repo_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[Engine, tuple[float, str]]]:
    """Every engine's average score and grade, per repository.

    The CI number is taken from ``compute_avg_scores_batch`` rather than
    recomputed here, so ``RepositoryPublic.grade`` and this engine's entry are
    the same number by construction rather than by two definitions agreeing.
    """
    if not repo_ids:
        return {}

    result: dict[uuid.UUID, dict[Engine, tuple[float, str]]] = {
        repo_id: {} for repo_id in repo_ids
    }
    for spec in OVERVIEW_SPECS:
        if spec.key is Engine.workflow:
            averages = {
                repo_id: score
                for repo_id, score in compute_avg_scores_batch(
                    session, repo_ids
                ).items()
                if score is not None
            }
        else:
            averages = _average_by_repo(session, spec, repo_ids)
        for repo_id, average in averages.items():
            rounded = round(average, 1)
            result[repo_id][spec.key] = (rounded, score_to_grade(rounded))
    return result
