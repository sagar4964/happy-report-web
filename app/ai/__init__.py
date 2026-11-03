"""AI connection. The provider is chosen by the AI_PROVIDER setting so it can be changed later."""
import os
from .base import AIError, AIResult  # noqa: F401


def get_provider():
    name = os.environ.get("AI_PROVIDER", "openai").strip().lower()
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider()
    raise AIError("The AI provider setting is not recognised. An administrator must check "
                  "AI_PROVIDER (openai or gemini).", "config")
