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
    "pause",
    "mark_active_client",
    "set_tipo_cliente",
    "summary",
    "help",
    "complete_all",
    "unknown",
]


@dataclass
class AdminIntent:
    action: IntentAction
    query: str = ""
    # `contact-segmentation-b2b-b2c`: desired `contatos.tipo_cliente` value
    # ("b2b"/"b2c"), only set when `action == "set_tipo_cliente"`.
    tipo_cliente: str | None = None


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

# `admin-bot-pause`: manual pause, distinct verbs from `_REACTIVATE`
# ("pausar/desativar/desligar" vs. "reativar/libera") so the two never
# collide. The "para (o/a) " alternative is tried first (alternation order
# matters — Python `re` picks the first alternative that matches at a given
# position, not the longest) so a trailing "para o João"/"para a Maria" gets
# swallowed along with the trigger itself, leaving a clean name for
# `search_contacts_for_admin`'s raw substring match (same concern as
# `_MARK_ACTIVE_CLIENT_PREFIX` above — a stray leading "para" would make an
# otherwise-matching `push_name` miss entirely).
_PAUSE_VERB = r"(?:pausa(?:r)?|desativa(?:r)?|desliga(?:r)?)"
_PAUSE = re.compile(
    rf"\b{_PAUSE_VERB}\s+(?:o\s+)?bot\s+para\s+(?:o\s+|a\s+)?"
    rf"|\b{_PAUSE_VERB}\s+(?:o\s+)?bot\b",
    re.I,
)
_SUMMARY = re.compile(r"\b(resumo|estat[ií]sticas|stats)\b", re.I)
_HELP = re.compile(r"^(ajuda|help|\?)$", re.I)
_COMPLETE_ALL = re.compile(r"\b(atender\s+todos|limpar\s+(?:a\s+)?fila)\b", re.I)

# `contact-interest-memory`: manual confirmation that a contact became a
# paying/active client (`contatos.status = "cliente_ativo"`) — the automatic
# transitions (`whatbot/session_state.py::next_status`) deliberately never
# reach this stage on their own. Two shapes, both name-bearing:
#   - trigger word(s) BEFORE the name: "confirma venda da Maria",
#     "virou cliente a Maria" -> `_strip_intent_prefix`.
#   - trigger phrase AFTER the name: "marca a Maria como cliente ativo"
#     -> `_strip_intent_suffix` (name is what's left before "cliente ativo").
#
# Each trigger has a "swallow the filler article" alternative tried first
# (e.g. "marca a " / "venda da " / "cliente a ") so the leftover query is a
# clean name — `search_contacts_for_admin` (unlike `find_waiting_matches`)
# matches the query as a raw substring, not tokenized, so a stray leading
# "a"/"da" would make an otherwise-matching `push_name` miss entirely.
_MARK_ACTIVE_CLIENT_PREFIX = re.compile(
    r"\bmarca(?:r)?\s+(?:a|o)\s+"
    r"|\bmarque\s+(?:a|o)\s+"
    r"|\bconfirma(?:r)?\s+(?:a\s+)?venda\s+(?:da|do|de)\s+"
    r"|\bvirou\s+cliente\s+(?:a|o)\s+"
    r"|\b(?:marca(?:r)?|marque|confirma(?:r)?\s+(?:a\s+)?venda|virou\s+cliente)\b",
    re.I,
)
_MARK_ACTIVE_CLIENT_SUFFIX = re.compile(r"\b(?:como\s+)?cliente\s+ativo\b", re.I)

# `contact-segmentation-b2b-b2c`: manual admin command to label a contact as
# a company (`b2b`) or an individual (`b2c`) — `contatos.tipo_cliente`, a
# different axis from `status`/`cliente_ativo` above. Suffix-only phrasing
# ("marca a Maria como empresa", "define Maria como B2B"), same shape as
# `_MARK_ACTIVE_CLIENT_SUFFIX`: requiring "como X" as the trigger (not a bare
# "empresa"/"b2b" anywhere in the text) avoids false positives on a company
# name mentioned in conversation. Checked BEFORE
# `_MARK_ACTIVE_CLIENT_PREFIX`'s bare fallback (line further below) — both
# share trigger verbs ("marca"/"marque"), so without this ordering "marca a
# Maria como empresa" would be mis-parsed as `mark_active_client` once the
# (non-matching) `_MARK_ACTIVE_CLIENT_SUFFIX` check falls through to the bare
# prefix check.
_SET_TIPO_CLIENTE_B2B_SUFFIX = re.compile(r"\bcomo\s+(?:empresa|b2b)\b", re.I)
_SET_TIPO_CLIENTE_B2C_SUFFIX = re.compile(
    r"\bcomo\s+pessoa\s+f[ií]sica\b|\bcomo\s+b2c\b", re.I
)
# Prefix triggers shared by both directions above — "swallow the filler
# article" alternative tried first (e.g. "marca a "), same reasoning as
# `_MARK_ACTIVE_CLIENT_PREFIX`: `search_contacts_for_admin` matches the
# leftover query as a raw substring, not tokenized, so a stray leading
# "a"/"o" would make an otherwise-matching `push_name` miss entirely.
_SET_TIPO_CLIENTE_PREFIX = re.compile(
    r"\bmarca(?:r)?\s+(?:a|o)\s+"
    r"|\bmarque\s+(?:a|o)\s+"
    r"|\bdefin(?:e|ir)\s+"
    r"|\b(?:marca(?:r)?|marque|defin(?:e|ir))\b",
    re.I,
)


def _strip_intent_prefix(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    if not match:
        return text.strip()
    return text[match.end() :].strip(" :,-–—")


def _strip_intent_suffix(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    if not match:
        return text.strip()
    return text[: match.start()].strip(" :,-–—")


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

    if _PAUSE.search(lower):
        query = _strip_intent_prefix(raw, _PAUSE)
        return AdminIntent("pause", query or raw)

    if _MARK_ACTIVE_CLIENT_SUFFIX.search(lower):
        query = _strip_intent_suffix(raw, _MARK_ACTIVE_CLIENT_SUFFIX)
        query = _strip_intent_prefix(query, _MARK_ACTIVE_CLIENT_PREFIX)
        return AdminIntent("mark_active_client", query or raw)

    # Checked before the `_MARK_ACTIVE_CLIENT_PREFIX` bare fallback below —
    # see comment on `_SET_TIPO_CLIENTE_B2B_SUFFIX` above.
    if _SET_TIPO_CLIENTE_B2B_SUFFIX.search(lower):
        query = _strip_intent_suffix(raw, _SET_TIPO_CLIENTE_B2B_SUFFIX)
        query = _strip_intent_prefix(query, _SET_TIPO_CLIENTE_PREFIX)
        return AdminIntent("set_tipo_cliente", query or raw, tipo_cliente="b2b")

    if _SET_TIPO_CLIENTE_B2C_SUFFIX.search(lower):
        query = _strip_intent_suffix(raw, _SET_TIPO_CLIENTE_B2C_SUFFIX)
        query = _strip_intent_prefix(query, _SET_TIPO_CLIENTE_PREFIX)
        return AdminIntent("set_tipo_cliente", query or raw, tipo_cliente="b2c")

    if _MARK_ACTIVE_CLIENT_PREFIX.search(lower):
        query = _strip_intent_prefix(raw, _MARK_ACTIVE_CLIENT_PREFIX)
        return AdminIntent("mark_active_client", query or raw)

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
