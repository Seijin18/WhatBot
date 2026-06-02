"""Gemini (Google Generative AI) client wrapper."""

from __future__ import annotations

import time
from typing import List
import logging

try:
    from google import genai
    from google.genai import types

    _SDK_KIND = "google-genai"
except Exception:  # pragma: no cover - fallback for older container images
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
    _SDK_KIND = "google-generativeai"

try:  # pragma: no cover - fallback path is environment dependent
    import google.generativeai as legacy_genai
except Exception:  # pragma: no cover - fallback path is environment dependent
    legacy_genai = None  # type: ignore[assignment]

from .config import (
    GEMINI_MODEL,
    GEMINI_MODEL_FALLBACKS,
    GEMINI_TEMPERATURE,
    gemini_use_tools,
)
from .db import MessageRecord
from .llm import LlmUnavailableError
from .prompt_builder import build_enriched_system_prompt
from .tools import AGENT_TOOLS, execute_tool

MAX_TOOL_ROUNDS = 5
FINAL_ANSWER_NUDGE = (
    "Com base nas informações consultadas, responda ao cliente em português "
    "brasileiro, de forma natural, acolhedora e conversacional. "
    "Não use formato P:/R: nem copie dumps de ferramentas."
)


class GeminiQuotaError(LlmUnavailableError):
    """Gemini API free-tier or billing quota exhausted."""


def _model_candidates() -> list[str]:
    models = [GEMINI_MODEL, *GEMINI_MODEL_FALLBACKS]
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if model not in seen:
            seen.add(model)
            ordered.append(model)
    return ordered


def _is_transient_error(exc: Exception) -> bool:
    if _is_quota_error(exc):
        return False
    status_code = getattr(exc, "status_code", None)
    if status_code in {429, 503}:
        return status_code == 503
    message = str(exc).lower()
    if "quota exceeded" in message or "resource_exhausted" in message:
        return False
    return any(
        token in message
        for token in ("503", "unavailable", "high demand")
    )


def _is_quota_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    message = str(exc).lower()
    return "quota exceeded" in message or "resource_exhausted" in message


def _is_model_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    if status_code in {404, 400}:
        return True
    return any(
        token in message
        for token in ("not found", "deprecated", "invalid model", "does not exist")
    )


def _response_text(response) -> str:
    if response is None:
        return ""
    try:
        text = response.text
        if text:
            return str(text).strip()
    except Exception:
        pass
    if getattr(response, "candidates", None):
        candidate = response.candidates[0]
        try:
            candidate_text = candidate.text
            if candidate_text:
                return str(candidate_text).strip()
        except Exception:
            pass
        content = getattr(candidate, "content", None)
        if content and getattr(content, "parts", None):
            chunks: list[str] = []
            for part in content.parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    chunks.append(str(part_text))
            if chunks:
                return "\n".join(chunks).strip()
    return ""


def _collect_function_calls(response) -> list:
    calls = list(getattr(response, "function_calls", None) or [])
    if calls:
        return calls
    collected: list = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            if fc is not None:
                collected.append(fc)
    return collected


def _call_name(call) -> str:
    name = getattr(call, "name", None)
    if name:
        return str(name)
    inner = getattr(call, "function_call", None)
    if inner is not None:
        return str(getattr(inner, "name", "") or "")
    return ""


def _call_args(call) -> dict:
    args = getattr(call, "args", None)
    if args is not None:
        return dict(args)
    inner = getattr(call, "function_call", None)
    if inner is not None and getattr(inner, "args", None) is not None:
        return dict(inner.args)
    return {}


def _generation_config(
    system_prompt: str,
    *,
    tools: list | None = None,
) -> types.GenerateContentConfig:
    kwargs = {
        "system_instruction": system_prompt,
        "temperature": GEMINI_TEMPERATURE,
        "max_output_tokens": 800,
    }
    if tools is not None:
        kwargs["tools"] = tools
    try:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    except Exception:
        pass
    return types.GenerateContentConfig(**kwargs)


class GeminiClient:
    def __init__(self, api_key: str):
        self._logger = logging.getLogger("whatbot.gemini")
        self._sdk_kind = _SDK_KIND
        try:
            if genai is not None:
                self._client = genai.Client(api_key=api_key)
            elif legacy_genai is not None:
                legacy_genai.configure(api_key=api_key)
                self._client = legacy_genai
            else:
                raise ImportError("Nenhum SDK do Gemini está instalado")
            self._logger.info("Gemini SDK ativo: %s", self._sdk_kind)
        except Exception as e:
            self._logger.exception("Erro configurando Gemini SDK: %s", e)
            raise

    def _build_contents(
        self, recent_history: List[MessageRecord], user_message: str
    ) -> list:
        contents = []
        for m in reversed(recent_history):
            role = "user" if m.direction == "in" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part(text=m.text)],
                )
            )
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=user_message)],
            )
        )
        return contents

    def _legacy_system_prompt(self, system_prompt: str) -> str:
        if "=== BASE DE CONHECIMENTO" in system_prompt:
            return system_prompt
        return build_enriched_system_prompt(system_prompt)

    def _generate_plain(
        self,
        model: str,
        system_prompt: str,
        recent_history: List[MessageRecord],
        user_message: str,
    ) -> str:
        contents = self._build_contents(recent_history, user_message)
        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=_generation_config(
                self._legacy_system_prompt(system_prompt),
            ),
        )
        return _response_text(response)

    def _finalize_after_tools(
        self,
        model: str,
        system_prompt: str,
        contents: list,
    ) -> str:
        """Ask the model to produce a natural-language answer after tool calls."""
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=FINAL_ANSWER_NUDGE)],
            )
        )
        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=_generation_config(system_prompt),
        )
        return _response_text(response)

    def _generate_with_tools(
        self,
        model: str,
        system_prompt: str,
        recent_history: List[MessageRecord],
        user_message: str,
    ) -> str:
        contents = self._build_contents(recent_history, user_message)
        tool_declarations = [
            types.FunctionDeclaration.from_callable(
                client=self._client, callable=fn
            )
            for fn in AGENT_TOOLS
        ]
        tool = types.Tool(function_declarations=tool_declarations)
        config = _generation_config(system_prompt, tools=[tool])
        response = None

        for round_idx in range(MAX_TOOL_ROUNDS):
            response = self._client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            function_calls = _collect_function_calls(response)
            if not function_calls:
                text = _response_text(response)
                if text:
                    return text
                self._logger.warning(
                    "Resposta vazia após tools (round=%s); pedindo resposta final",
                    round_idx + 1,
                )
                return self._finalize_after_tools(model, system_prompt, contents)

            if response.candidates:
                contents.append(response.candidates[0].content)

            tool_parts = []
            for call in function_calls:
                name = _call_name(call)
                args = _call_args(call)
                self._logger.info("Tool call: %s(%s)", name, args)
                result = execute_tool(name, args)
                tool_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"result": result},
                    )
                )

            contents.append(types.Content(role="tool", parts=tool_parts))

        self._logger.warning("Limite de tool rounds atingido")
        finalized = self._finalize_after_tools(model, system_prompt, contents)
        if finalized:
            return finalized
        return _response_text(response) if response else ""

    def _generate_with_model(
        self,
        model: str,
        system_prompt: str,
        recent_history: List[MessageRecord],
        user_message: str,
        *,
        use_tools: bool = True,
    ) -> str:
        if self._sdk_kind != "google-genai":
            enriched_prompt = self._legacy_system_prompt(system_prompt)
            prompt_parts = [f"SYSTEM: {enriched_prompt}"]
            for m in reversed(recent_history):
                prefix = "USER" if m.direction == "in" else "ASSISTANT"
                prompt_parts.append(f"{prefix}: {m.text}")
            prompt_parts.append(f"USER: {user_message}")
            prompt_parts.append("ASSISTANT:")
            prompt = "\n\n".join(prompt_parts)

            legacy_model = self._client.GenerativeModel(model)
            response = legacy_model.generate_content(
                prompt,
                generation_config={
                    "temperature": GEMINI_TEMPERATURE,
                    "max_output_tokens": 800,
                },
            )
            return _response_text(response)

        if use_tools:
            try:
                text = self._generate_with_tools(
                    model, system_prompt, recent_history, user_message
                )
                if text.strip():
                    return text
                self._logger.warning(
                    "Tools retornaram vazio no model=%s; tentando sem tools", model
                )
            except Exception as exc:
                self._logger.warning(
                    "Function calling falhou (%s); tentando sem tools", exc
                )

        return self._generate_plain(
            model, system_prompt, recent_history, user_message
        )

    def chat(
        self,
        system_prompt: str,
        recent_history: List[MessageRecord],
        user_message: str,
    ) -> str:
        use_tools = gemini_use_tools()
        last_error: Exception | None = None
        quota_hit = False

        for model in _model_candidates():
            try:
                self._logger.info(
                    "Chamando Gemini model=%s (tools=%s)", model, use_tools
                )
                text = self._generate_with_model(
                    model,
                    system_prompt,
                    recent_history,
                    user_message,
                    use_tools=use_tools,
                )
                if text.strip():
                    return text
                self._logger.warning(
                    "Gemini retornou vazio (model=%s); tentando sem historico",
                    model,
                )
                text = self._generate_with_model(
                    model,
                    system_prompt,
                    [],
                    user_message,
                    use_tools=use_tools,
                )
                if text.strip():
                    return text
                last_error = RuntimeError(f"Resposta vazia do modelo {model}")
            except Exception as e:
                last_error = e
                if _is_quota_error(e):
                    quota_hit = True
                    self._logger.warning("Cota Gemini esgotada para %s", model)
                    continue
                if _is_model_unavailable_error(e):
                    self._logger.warning("Modelo indisponivel (%s): %s", model, e)
                    continue
                if _is_transient_error(e):
                    self._logger.warning(
                        "Gemini indisponivel (model=%s): %s — uma tentativa",
                        model,
                        e,
                    )
                    time.sleep(2)
                    try:
                        text = self._generate_with_model(
                            model,
                            system_prompt,
                            recent_history,
                            user_message,
                            use_tools=use_tools,
                        )
                        if text.strip():
                            return text
                    except Exception as retry_exc:
                        last_error = retry_exc
                        if _is_quota_error(retry_exc):
                            quota_hit = True
                            continue
                    continue
                self._logger.exception("Erro chamando Gemini: %s", e)
                raise

        if quota_hit:
            raise GeminiQuotaError(str(last_error or "Cota da API Gemini esgotada"))
        if last_error is not None:
            self._logger.exception("Erro chamando Gemini apos fallbacks: %s", last_error)
            raise last_error
        raise RuntimeError("Nenhum modelo Gemini disponivel")
