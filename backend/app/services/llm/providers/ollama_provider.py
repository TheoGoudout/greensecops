from langchain_ollama import ChatOllama

from app.services.llm.base import BaseLLMProvider, LLMResponse


class OllamaProvider(BaseLLMProvider):
    def __init__(
        self, model: str = "llama3.2", base_url: str = "http://localhost:11434"
    ) -> None:
        self._model = model
        self._llm = ChatOllama(model=model, base_url=base_url, temperature=0.1)

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = await self._llm.ainvoke(messages)
        usage = response.usage_metadata or {}
        return LLMResponse(
            content=str(response.content),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            model=self._model,
        )
