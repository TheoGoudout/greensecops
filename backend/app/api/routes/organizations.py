import uuid

from fastapi import HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.api.router import Role, RoleRouter
from app.models import (
    AIProviderInfo,
    AIProvidersPublic,
    Organization,
    OrganizationPublic,
    OrganizationUpdate,
    OrgMember,
)
from app.services.llm.catalog import _KEY_MAP, load_provider_catalog

router = RoleRouter(prefix="/organizations", tags=["organizations"])


def _is_available(provider_id: str) -> bool:
    val = _KEY_MAP.get(provider_id)
    return bool(val)


@router.get("/ai-providers", role=Role.user, response_model=AIProvidersPublic)
def list_ai_providers(
    current_user: CurrentUser,  # noqa: ARG001
) -> AIProvidersPublic:
    """Return only available LLM providers with per-provider default model."""
    catalog = load_provider_catalog()
    return AIProvidersPublic(
        providers=[
            AIProviderInfo(
                id=p["id"],
                name=p["name"],
                available=True,
                default_model=p["default_model"],
                models=p["models"],
            )
            for p in catalog
            if _is_available(p["id"])
        ]
    )


@router.get("", role=Role.user, response_model=list[OrganizationPublic])
def list_my_organizations(
    session: SessionDep,
    current_user: CurrentUser,
) -> list[OrganizationPublic]:
    """Return all organizations the current user belongs to."""
    org_ids = session.exec(
        select(OrgMember.org_id).where(OrgMember.user_id == current_user.id)
    ).all()
    orgs = session.exec(select(Organization).where(Organization.id.in_(org_ids))).all()  # type: ignore[attr-defined]
    return [
        OrganizationPublic(
            id=o.id,
            name=o.name,
            tier=o.tier,
            default_llm_provider=o.default_llm_provider,
            default_llm_model=o.default_llm_model,
            fix_delivery_mode=o.fix_delivery_mode,
            created_at=o.created_at,
        )
        for o in orgs
    ]


@router.patch("/{org_id}", role=Role.org_admin, response_model=OrganizationPublic)
def update_organization(
    org_id: uuid.UUID,
    body: OrganizationUpdate,
    session: SessionDep,
) -> OrganizationPublic:
    # Membership and rank are enforced by role=Role.org_admin before this runs;
    # this endpoint's hand-rolled version of that check was the only place
    # OrgRole was ever consulted in the API layer.
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    org.default_llm_provider = body.default_llm_provider
    org.default_llm_model = body.default_llm_model
    session.add(org)
    session.commit()
    session.refresh(org)
    return OrganizationPublic(
        id=org.id,
        name=org.name,
        tier=org.tier,
        default_llm_provider=org.default_llm_provider,
        default_llm_model=org.default_llm_model,
        fix_delivery_mode=org.fix_delivery_mode,
        created_at=org.created_at,
    )
