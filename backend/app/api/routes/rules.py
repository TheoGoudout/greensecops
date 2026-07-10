import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import IssueCategory, Rule, RulePublic

router = APIRouter(prefix="/rules", tags=["rules"])


@router.get("/", response_model=list[RulePublic])
def list_rules(
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
    category: IssueCategory | None = None,
    enabled: bool | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=200),
) -> list[Rule]:
    query = select(Rule)
    if category:
        query = query.where(Rule.category == category)
    if enabled is not None:
        query = query.where(Rule.enabled == enabled)
    query = (
        query.order_by(Rule.severity_weight.desc(), Rule.title)
        .offset(skip)
        .limit(limit)
    )  # type: ignore[union-attr]
    return list(session.exec(query).all())


@router.get("/{rule_id}", response_model=RulePublic)
def get_rule(
    rule_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,  # noqa: ARG001
) -> Rule:
    rule = session.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch(
    "/{rule_id}/toggle",
    response_model=RulePublic,
    dependencies=[Depends(get_current_active_superuser)],
)
def toggle_rule(
    rule_id: uuid.UUID,
    session: SessionDep,
    enabled: bool,
) -> Rule:
    rule = session.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.enabled = enabled
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule
