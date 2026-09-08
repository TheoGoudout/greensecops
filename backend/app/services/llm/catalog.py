import functools
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models import LLMProvider
from app.services.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = Path(__file__).parent.parent.parent / "config" / "ai_providers.json"

# What every caller of the catalog indexes directly.
_REQUIRED_FIELDS = ("id", "name", "default_model", "models")

_KEY_MAP: dict[str, str | None] = {
    "openai": settings.OPENAI_API_KEY,
    "anthropic": settings.ANTHROPIC_API_KEY,
    "gemini": settings.GOOGLE_API_KEY,
    "ollama": settings.OLLAMA_BASE_URL,
}


def _read_catalog(path: Path) -> list[dict[str, Any]]:
    """Parse one catalog file, rejecting anything a caller would trip over.

    Callers index ``name``, ``default_model`` and ``models`` without checking,
    so an entry missing one of them fails later, elsewhere, and as a 500 rather
    than as the configuration error it is.
    """
    with path.open() as f:
        providers = json.load(f)["providers"]
    if not isinstance(providers, list) or not providers:
        raise ValueError("'providers' must be a non-empty list")
    for provider in providers:
        if not isinstance(provider, dict):
            raise ValueError("every provider must be an object")
        missing = [field for field in _REQUIRED_FIELDS if field not in provider]
        if missing:
            raise ValueError(
                f"provider {provider.get('id', '<unnamed>')!r} is missing "
                f"{', '.join(missing)}"
            )
    return providers


@functools.lru_cache(maxsize=1)
def load_provider_catalog() -> list[dict[str, Any]]:
    """The provider catalog: ``AI_PROVIDERS_CONFIG``, or the bundled copy.

    On the Coolify deployment that setting names a file an operator edits from
    the Coolify UI — ``deploy/coolify/compose.yml`` mounts it for exactly that
    — so a malformed catalog is an ordinary operational event rather than a
    packaging bug, and an unreadable one is what the container gets if Docker
    ever creates a directory at a bind-mount source that is not there yet.

    Fall back to the catalog shipped in the image instead of failing: the
    models the operator added are missing until the file is fixed, which is a
    smaller outage than every LLM route answering 500. Read once per process,
    so a corrected file takes effect on the next restart.
    """
    configured = settings.AI_PROVIDERS_CONFIG
    if configured:
        try:
            return _read_catalog(Path(configured))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.error(
                "AI_PROVIDERS_CONFIG=%s is unusable (%s); falling back to the "
                "provider catalog bundled in the image",
                configured,
                exc,
            )
    return _read_catalog(_DEFAULT_CONFIG)


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
