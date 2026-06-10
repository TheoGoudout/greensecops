import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import Fix, FixPublic, FixStatus
from app.workers.tasks.fix_delivery import deliver_fix
from app.workers.tasks.fix_generation import run_fix_generation

router = APIRouter(prefix="/fixes", tags=["fixes"])


@router.get("/", response_model=list[FixPublic])
def list_fixes(
    session: SessionDep,
    current_user: CurrentUser,
    issue_id: uuid.UUID | None = None,
    status: FixStatus | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
) -> list[Fix]:
    query = select(Fix)
    if issue_id:
        query = query.where(Fix.issue_id == issue_id)
    if status:
        query = query.where(Fix.status == status)
    query = query.order_by(Fix.created_at.desc()).offset(skip).limit(limit)  # type: ignore[arg-type]
    return list(session.exec(query).all())


@router.get("/{fix_id}", response_model=FixPublic)
def get_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Fix:
    fix = session.get(Fix, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    return fix


@router.post("/generate/{issue_id}", status_code=202)
def trigger_fix_generation(
    issue_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str]:
    from app.models import Issue
    issue = session.get(Issue, issue_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")
    run_fix_generation.delay(issue_id=str(issue_id))
    return {"status": "queued", "issue_id": str(issue_id)}


@router.post("/{fix_id}/deliver", status_code=202)
def trigger_fix_delivery(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str]:
    fix = session.get(Fix, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    if fix.status != FixStatus.ready:
        raise HTTPException(status_code=409, detail=f"Fix is not ready (status: {fix.status})")
    deliver_fix.delay(fix_id=str(fix_id))
    return {"status": "queued", "fix_id": str(fix_id)}


@router.delete("/{fix_id}", status_code=204)
def reject_fix(
    fix_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    fix = session.get(Fix, fix_id)
    if not fix:
        raise HTTPException(status_code=404, detail="Fix not found")
    fix.status = FixStatus.rejected
    session.add(fix)
    session.commit()
