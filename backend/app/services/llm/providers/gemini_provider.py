from langchain_google_genai import ChatGoogleGenerativeAI

from app.services.llm.base import BaseLLMProvider


class GeminiProvider(BaseLLMProvider):
    def __init__(
        self, model: str = "gemini-1.5-flash", api_key: str | None = None
    ) -> None:
        self._model = model
        self._llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,  # type: ignore[arg-type]
            temperature=0.1,
        )
