"""LLM provider factory (Gemini, Ollama, ...)."""

from __future__ import annotations

import os
from typing import Protocol

from .config import (
    ENV_GEMINI_API_KEY,
    ENV_LLM_PROVIDER,
    ENV_OLLAMA_BASE_URL,
    ENV_OLLAMA_MODEL,
    is_placeholder,
    resolve_ollama_base_url,
)


class LlmUnavailableError(RuntimeError):
    """LLM provider unavailable (quota, connection, etc.)."""


class ChatClient(Protocol):
    def chat(
        self,
        system_prompt: str,
        recent_history,
        user_message: str,
    ) -> str: ...


def create_llm_client() -> ChatClient:
    provider = os.getenv(ENV_LLM_PROVIDER, "gemini").strip().lower()
    if provider == "ollama":
        from .ollama_client import OllamaClient

        return OllamaClient(
            base_url=resolve_ollama_base_url(os.getenv(ENV_OLLAMA_BASE_URL)),
            model=os.getenv(ENV_OLLAMA_MODEL, "llama3.2"),
        )
    if provider == "gemini":
        from .gemini_client import GeminiClient

        key = os.getenv(ENV_GEMINI_API_KEY, "").strip()
        if is_placeholder(key):
            raise RuntimeError(
                "GEMINI_API_KEY não configurado (LLM_PROVIDER=gemini). "
                "Use LLM_PROVIDER=ollama para modelo local."
            )
        return GeminiClient(api_key=key)
    raise RuntimeError(
        f"LLM_PROVIDER inválido: {provider!r}. Use 'gemini' ou 'ollama'."
    )
