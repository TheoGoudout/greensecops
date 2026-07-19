from langchain_anthropic import ChatAnthropic

from app.services.llm.base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    def __init__(
        self, model: str = "claude-haiku-4-5-20251001", api_key: str | None = None
    ) -> None:
        self._model = model
        self._llm = ChatAnthropic(  # type: ignore[call-arg]
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.1,
            max_tokens=4096,
        )
