from langchain_openai import ChatOpenAI

from app.services.llm.base import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None) -> None:
        self._model = model
        self._llm = ChatOpenAI(
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.1,
        )
