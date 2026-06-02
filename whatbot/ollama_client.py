"""Ollama local LLM client (OpenAI-compatible chat API)."""

from __future__ import annotations

import logging
from typing import List

import requests

from .config import GEMINI_TEMPERATURE
from .db import MessageRecord
from .llm import LlmUnavailableError
logger = logging.getLogger("whatbot.ollama")


class OllamaClient:
    """Chat via Ollama /api/chat — sem cota de nuvem, roda na sua máquina."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
        timeout_s: int = 120,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_s
        logger.info("Ollama ativo: %s model=%s", self._base_url, self._model)

    def _build_messages(
        self,
        system_prompt: str,
        recent_history: List[MessageRecord],
        user_message: str,
    ) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": system_prompt}]
        for record in reversed(recent_history):
            role = "user" if record.direction == "in" else "assistant"
            messages.append({"role": role, "content": record.text})
        messages.append({"role": "user", "content": user_message})
        return messages

    def chat(
        self,
        system_prompt: str,
        recent_history: List[MessageRecord],
        user_message: str,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": self._build_messages(
                system_prompt, recent_history, user_message
            ),
            "stream": False,
            "options": {"temperature": GEMINI_TEMPERATURE},
        }
        url = f"{self._base_url}/api/chat"
        try:
            logger.info("Chamando Ollama model=%s", self._model)
            response = requests.post(url, json=payload, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
        except requests.ConnectionError as exc:
            raise LlmUnavailableError(
                f"Ollama inacessível em {self._base_url}. "
                "Instale e rode: ollama serve"
            ) from exc
        except requests.HTTPError as exc:
            body = ""
            try:
                body = response.text[:300]
            except Exception:
                pass
            if response.status_code == 404 and "not found" in body.lower():
                raise LlmUnavailableError(
                    f"Modelo {self._model!r} não encontrado no Ollama. "
                    f"Execute: ollama pull {self._model}"
                ) from exc
            raise LlmUnavailableError(f"Ollama HTTP {response.status_code}: {body}") from exc
        except requests.RequestException as exc:
            raise LlmUnavailableError(f"Erro Ollama: {exc}") from exc

        message = data.get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            raise LlmUnavailableError("Ollama retornou resposta vazia")
        return text
