import functools
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings as app_settings
from app.models import (
    AIProviderInfo,
    AIProvidersPublic,
    Organization,
    OrganizationAIUpdate,
    OrganizationPublic,
    OrgMember,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])

_DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "ai_providers.json"

_KEY_ENV: dict[str, str | None] = {
    "openai": app_settings.OPENAI_API_KEY,
    "anthropic": app_settings.ANTHROPIC_API_KEY,
    "gemini": app_settings.GOOGLE_API_KEY,
    "ollama": app_settings.OLLAMA_BASE_URL,
}


@functools.lru_cache(maxsize=1)
def _load_provider_catalog() -> list[dict]:
    config_path = app_settings.AI_PROVIDERS_CONFIG
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    with path.open() as f:
        return json.load(f)["providers"]


def _is_available(provider_id: str) -> bool:
    val = _KEY_ENV.get(provider_id)
    return bool(val)


@router.get("/ai-providers", response_model=AIProvidersPublic)
def list_ai_providers(
    current_user: CurrentUser,  # noqa: ARG001
) -> AIProvidersPublic:
    """Return only available LLM providers with per-provider default model."""
    catalog = _load_provider_catalog()
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


@router.get("/", response_model=list[OrganizationPublic])
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


@router.patch("/{org_id}/ai-preferences", response_model=OrganizationPublic)
def update_org_ai_preferences(
    org_id: uuid.UUID,
    body: OrganizationAIUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> OrganizationPublic:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    member = session.exec(
        select(OrgMember).where(
            OrgMember.org_id == org_id, OrgMember.user_id == current_user.id
        )
    ).first()
    if not current_user.is_superuser and not member:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
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
