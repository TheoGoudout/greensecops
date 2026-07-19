from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    run_id: str | None = None  # LangSmith run ID


class BaseLLMProvider(ABC):
    """Wraps a langchain chat model. Subclasses set ``_llm`` and ``_model``."""

    _llm: "BaseChatModel"
    _model: str

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Generate a completion."""
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = await self._llm.ainvoke(messages)
        usage = getattr(response, "usage_metadata", None) or {}
        return LLMResponse(
            content=str(response.content),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            model=self._model,
        )
