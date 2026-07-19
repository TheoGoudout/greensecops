from langchain_ollama import ChatOllama

from app.services.llm.base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    def __init__(
        self, model: str = "llama3.2", base_url: str = "http://localhost:11434"
    ) -> None:
        self._model = model
        self._llm = ChatOllama(model=model, base_url=base_url, temperature=0.1)
