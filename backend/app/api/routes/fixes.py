import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import delete, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Analysis, Fix, FixPublic, FixStatus, Issue
from app.workers.tasks.fix_delivery import deliver_fix
from app.workers.tasks.fix_generation import (
    run_batch_fix_generation,
    run_fix_generation,
)

router = APIRouter(prefix="/fixes", tags=["fixes"])


@router.get("/", response_model=list[FixPublic])
def list_fixes(
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    issue_id: uuid.UUID | None = None,
    analysis_id: uuid.UUID | None = None,
    repo_id: uuid.UUID | None = None,
    status: FixStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[Fix]:
    query = select(Fix)
    if issue_id:
        query = query.where(Fix.issue_id == issue_id)
    if analysis_id or repo_id:
        query = query.join(Issue, Fix.issue_id == Issue.id)  # type: ignore[arg-type]
        if analysis_id:
            query = query.where(Issue.analysis_id == analysis_id)
        if repo_id:
            query = query.join(Analysis, Issue.analysis_id == Analysis.id).where(  # type: ignore[arg-type]
                Analysis.repo_id == repo_id
            )
    if status:
        query = query.where(Fix.status == status)
    query = query.order_by(Fix.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    return list(session.exec(query).all())


@router.get("/{fix_id}", response_model=FixPublic)
def get_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> Fix:
    fix = session.get(Fix, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    return fix


@router.post("/generate-for-repo/{repo_id}", status_code=202)
def trigger_fix_generation_for_repo(
    repo_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, int]:
    """Queue a single batch fix generation call per workflow file for all issues in a repo."""
    issues = session.exec(
        select(Issue)
        .join(Analysis, Issue.analysis_id == Analysis.id)  # type: ignore[arg-type]
        .where(Analysis.repo_id == repo_id)
    ).all()

    if not issues:
        return {"queued": 0}

    issue_ids = [i.id for i in issues]

    # Discard existing non-delivered fixes to allow fresh retry
    session.exec(
        delete(Fix).where(
            Fix.issue_id.in_(issue_ids),  # type: ignore[attr-defined]
            Fix.status != FixStatus.delivered,
        )
    )
    session.commit()

    # Group by analysis_id → one LLM call per workflow file
    by_analysis: dict[uuid.UUID, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_analysis[issue.analysis_id].append(issue)

    for group in by_analysis.values():
        run_batch_fix_generation.delay(issue_ids=[str(i.id) for i in group])

    return {"queued": len(issues)}


@router.post("/generate/{issue_id}", status_code=202)
def trigger_fix_generation(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, str]:
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Discard existing non-delivered fix to allow retry
    session.exec(
        delete(Fix).where(
            Fix.issue_id == issue_id,
            Fix.status != FixStatus.delivered,
        )
    )
    session.commit()

    run_fix_generation.delay(issue_id=str(issue_id))
    return {"status": "queued", "issue_id": str(issue_id)}


@router.post("/{fix_id}/deliver", status_code=202)
def trigger_fix_delivery(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> dict[str, str]:
    fix = session.get(Fix, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    if fix.status != FixStatus.ready:
        raise HTTPException(
            status_code=409, detail=f"Fix is not ready (status: {fix.status})"
        )
    deliver_fix.delay(fix_id=str(fix_id))
    return {"status": "queued", "fix_id": str(fix_id)}


@router.delete("/{fix_id}", status_code=204)
def reject_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> None:
    fix = session.get(Fix, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    fix.status = FixStatus.rejected
    session.add(fix)
    session.commit()
