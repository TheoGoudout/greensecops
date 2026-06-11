from app.core.config import settings
from app.models import LLMProvider
from app.services.llm.base import BaseLLMProvider


def get_provider(
    provider: str | None = None,
    model: str | None = None,
) -> BaseLLMProvider:
    """Resolve the LLM provider from config. Falls back to global default."""
    resolved_provider = provider or settings.DEFAULT_LLM_PROVIDER
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

    # Default fallback
    from app.services.llm.providers.openai_provider import OpenAIProvider

    return OpenAIProvider(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY)
