"""Organizations and their AI-provider preferences."""

import uuid
from datetime import datetime

from sqlmodel import SQLModel

from ..enums import (
    FixDeliveryMode,
    LLMProvider,
    UserTier,
)


class OrganizationPublic(SQLModel):
    id: uuid.UUID
    name: str
    tier: UserTier
    default_llm_provider: LLMProvider | None = None
    default_llm_model: str | None = None
    fix_delivery_mode: FixDeliveryMode
    created_at: datetime | None = None


class OrganizationAIUpdate(SQLModel):
    default_llm_provider: LLMProvider | None = None
    default_llm_model: str | None = None


class AIProviderInfo(SQLModel):
    id: str
    name: str
    available: bool
    default_model: str
    models: list[str]


class AIProvidersPublic(SQLModel):
    providers: list[AIProviderInfo]
