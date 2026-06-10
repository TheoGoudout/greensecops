from langchain_openai import ChatOpenAI

from app.services.llm.base import BaseLLMProvider, LLMResponse


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None) -> None:
        self._model = model
        self._llm = ChatOpenAI(
            model=model,
            api_key=api_key,  # type: ignore[arg-type]
            temperature=0.1,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        response = await self._llm.ainvoke(messages)
        usage = response.usage_metadata or {}
        return LLMResponse(
            content=str(response.content),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            model=self._model,
        )
