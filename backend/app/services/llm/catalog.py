import functools
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import LLMProvider
from app.services.llm.base import BaseLLMProvider

_DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "ai_providers.json"

_KEY_MAP: dict[str, str | None] = {
    "openai": settings.OPENAI_API_KEY,
    "anthropic": settings.ANTHROPIC_API_KEY,
    "gemini": settings.GOOGLE_API_KEY,
    "ollama": settings.OLLAMA_BASE_URL,
}


@functools.lru_cache(maxsize=1)
def load_provider_catalog() -> list[dict[str, Any]]:
    config_path = settings.AI_PROVIDERS_CONFIG
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    with path.open() as f:
        providers: list[dict[str, Any]] = json.load(f)["providers"]
    return providers


def get_default_model(provider_id: str) -> str | None:
    """Return the catalog default model for a provider, or None if unknown."""
    for p in load_provider_catalog():
        if p["id"] == provider_id:
            return p.get("default_model")
    return None


def get_first_available_provider() -> tuple[str, str]:
    """Return (provider_id, default_model) for the first provider with credentials configured."""
    for p in load_provider_catalog():
        if bool(_KEY_MAP.get(p["id"])):
            return p["id"], p["default_model"]
    raise RuntimeError(
        "No LLM provider is configured. Set at least one of: "
        "OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, OLLAMA_BASE_URL."
    )


def get_provider(
    provider: str | None = None,
    model: str | None = None,
) -> BaseLLMProvider:
    """Resolve the LLM provider. Falls back to first available provider with credentials."""
    if not provider:
        provider, fallback_model = get_first_available_provider()
        model = model or fallback_model
    resolved_provider = provider
    resolved_model = model or settings.DEFAULT_LLM_MODEL

    if resolved_provider == LLMProvider.openai:
        from app.services.llm.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(model=resolved_model, api_key=settings.OPENAI_API_KEY)

    if resolved_provider == LLMProvider.anthropic:
        from app.services.llm.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model=resolved_model, api_key=settings.ANTHROPIC_API_KEY
        )

    if resolved_provider == LLMProvider.gemini:
        from app.services.llm.providers.gemini_provider import GeminiProvider

        return GeminiProvider(model=resolved_model, api_key=settings.GOOGLE_API_KEY)

    if resolved_provider == LLMProvider.ollama:
        from app.services.llm.providers.ollama_provider import OllamaProvider

        return OllamaProvider(model=resolved_model, base_url=settings.OLLAMA_BASE_URL)

    raise ValueError(f"Unknown LLM provider: {resolved_provider!r}")
