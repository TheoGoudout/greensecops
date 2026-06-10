from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    run_id: str | None = None  # LangSmith run ID


class BaseLLMProvider(ABC):
    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Generate a completion."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (openai, anthropic, gemini, ollama)."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier."""
