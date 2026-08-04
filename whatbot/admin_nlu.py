"""Natural-language intents for secretariat admin messages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

IntentAction = Literal[
    "list_queue",
    "assume",
    "complete",
    "reactivate",
    "summary",
    "help",
    "complete_all",
    "unknown",
]


@dataclass
class AdminIntent:
    action: IntentAction
    query: str = ""


_LIST = re.compile(
    r"\b(fila|aguardando|espera|pendentes|quem\s+(?:ta|est[aá]|t[aá])\s+(?:na\s+)?espera|lista)\b",
    re.I,
)
_ASSUME = re.compile(
    r"\b(assumir|assumo|pego|vou\s+atender|fico\s+com)\b",
    re.I,
)
_COMPLETE = re.compile(
    r"\b(atender|atendi|finalizei|finalizado|conclu[ií]|resolvido|pronto|encerr(?:ar|ei)|remover\s+da\s+fila)\b",
    re.I,
)
_REACTIVATE = re.compile(
    r"\b(reativar|libera(?:r)?\s+(?:o\s+)?bot|volta(?:r)?\s+(?:o\s+)?bot|bot\s+(?:pode|volta)\b|pode\s+voltar\s+a\s+falar)\b",
    re.I,
)
_SUMMARY = re.compile(r"\b(resumo|estat[ií]sticas|stats)\b", re.I)
_HELP = re.compile(r"^(ajuda|help|\?)$", re.I)
_COMPLETE_ALL = re.compile(r"\b(atender\s+todos|limpar\s+(?:a\s+)?fila)\b", re.I)


def _strip_intent_prefix(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    if not match:
        return text.strip()
    return text[match.end() :].strip(" :,-–—")


def parse_admin_intent(text: str) -> AdminIntent:
    raw = text.strip()
    lower = raw.lower()

    if _HELP.match(lower):
        return AdminIntent("help")
    if _COMPLETE_ALL.search(lower):
        return AdminIntent("complete_all")
    if _SUMMARY.search(lower):
        return AdminIntent("summary")
    if _LIST.search(lower):
        return AdminIntent("list_queue")

    if _REACTIVATE.search(lower):
        query = _strip_intent_prefix(raw, _REACTIVATE)
        return AdminIntent("reactivate", query or raw)

    if _ASSUME.search(lower):
        query = _strip_intent_prefix(raw, _ASSUME)
        return AdminIntent("assume", query or raw)

    if _COMPLETE.search(lower):
        query = _strip_intent_prefix(raw, _COMPLETE)
        return AdminIntent("complete", query or raw)

    # Short replies that might be names only after a prompt
    if len(raw.split()) <= 4 and not raw.startswith("#"):
        return AdminIntent("unknown", raw)

    return AdminIntent("unknown", raw)


_CASUAL_TEST = re.compile(
    r"^(teste|testando|test|oi|olá|ola|hello|hi|hey|bom\s+dia|boa\s+tarde|boa\s+noite)[\s!.?]*$",
    re.I,
)

DEFAULT_CASUAL_TEST_MESSAGE = (
    "Olá, quero saber mais sobre os produtos e preços."
)


def is_casual_test_message(text: str) -> bool:
    """Short greetings/tests from admins — auto-run customer simulation."""
    return bool(_CASUAL_TEST.match(text.strip()))


def parse_simulate_command(text: str) -> tuple[str | None, str] | None:
    """Parse `#simular [phone] message` (one-shot) from admin test messages.

    A bare `#simular` (no phone, no message) is NOT a one-shot command — it
    toggles the persistent simulation mode instead (see
    `is_simulate_start_command`), so this returns `None` for it and lets the
    caller check that separately.
    """
    raw = text.strip()
    if not raw.lower().startswith("#simular"):
        return None
    body = raw[len("#simular") :].strip()
    if not body:
        return None
    phone_match = re.match(r"^(\d{10,15})\s+(.+)$", body, re.DOTALL)
    if phone_match:
        return phone_match.group(1), phone_match.group(2).strip()
    return None, body


_SIMULATE_START = re.compile(r"^#simular$", re.I)
_SIMULATE_END = re.compile(r"^#end-simular$", re.I)


def is_simulate_start_command(text: str) -> bool:
    """`#simular` alone in the message — turns on persistent simulation
    mode, where every following admin message is treated as the simulated
    customer speaking, until `#end-simular`. Distinct from
    `parse_simulate_command`'s one-shot `#simular <phone> <mensagem>` (which
    has content after the command and never matches this)."""
    return bool(_SIMULATE_START.match(text.strip()))


def is_simulate_end_command(text: str) -> bool:
    """`#end-simular` alone in the message — turns persistent simulation
    mode back off."""
    return bool(_SIMULATE_END.match(text.strip()))
