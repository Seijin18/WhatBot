"""Validate LLM replies and replace hallucinations with knowledge-base answers."""

from __future__ import annotations

import logging
import re
import unicodedata

from .claim_validator import get_claim_validator
from .intent_router import route_intent
from .knowledge import get_knowledge_store
from .knowledge_facts import get_knowledge_facts
from .reply_composer import default_closing, get_reply_composer
from .session_state import SessionState
from .tools import buscar_faq, buscar_info_negocio, buscar_precos, listar_itens

logger = logging.getLogger("whatbot.grounding")

_STOPWORDS = frozenset(
    {
        "somos",
        "temos",
        "voce",
        "você",
        "pode",
        "mais",
        "sobre",
        "horario",
        "horário",
        "horarios",
        "horários",
        "ajudar",
        "ajuda",
        "gostaria",
        "interessado",
        "interessada",
        "praticar",
        "informacao",
        "informações",
        "informacoes",
        "deseja",
        "quer",
        "quero",
        "qual",
        "quais",
        "como",
        "onde",
        "quando",
        "precisa",
        "preciso",
        "segue",
        "segunda",
        "segundas",
        "terca",
        "terça",
        "quarta",
        "quinta",
        "sexta",
        "sabado",
        "sábado",
        "domingo",
        "manha",
        "manhã",
        "tarde",
        "noite",
        "aulas",
        "aula",
        "valores",
        "valor",
        "plano",
        "planos",
        "mensal",
        "semestral",
        "desconto",
        "secretaria",
        "contato",
        "endereco",
        "endereço",
        "associacao",
        "associação",
        "item",
        "itens",
        "atividade",
        "atividades",
        "oferece",
        "oferecemos",
        "disponivel",
        "disponível",
        "consulte",
        "agendar",
        "experimental",
        "matricula",
        "matrícula",
    }
)

_ORG_CLAIM = re.compile(
    # Meant to catch a fabricated business-identity claim ("O TimeVivo é uma
    # associação..."), not any "o/a <substantivo> é" sentence — which is one
    # of the most common constructions in Portuguese. The captured phrase
    # is required to start with a capital letter (case-sensitive on
    # purpose, unlike the surrounding article/verb) as a proper-noun
    # heuristic: without it, ordinary replies like "O prazo é de até 5
    # dias" or "O frete é calculado por pedido" matched on "prazo"/"frete"
    # and got flagged as impersonating a fake organization — reproduced,
    # high-frequency false positive on the *primary* reply path (every
    # non-fallback LLM turn goes through `detect_hallucination`), found
    # during a final pipeline sanity check in this session (see
    # docs/REVISAO_CAMADA_CONVERSACIONAL.md).
    r"\b(?i:o|a|somos\s+(?:a|o))\s+([A-ZÀ-Ú][A-Za-zÀ-ú0-9\s]{1,30}?)\s+(?i:é|e\s+uma)\b",
)
_LIST_LINE = re.compile(r"^[\-*•\d\.)]+\s*")
_MAX_GROUNDED_REPLY_LEN = 1200


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower().strip())


def _knowledge_blob() -> str:
    return _norm(get_knowledge_store().format_full_context_for_prompt())


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^[\-*•\d\.)]+\s*", "", line.strip())


def _is_list_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and _LIST_LINE.match(stripped))


def _line_claims_item(line: str) -> bool:
    stripped = _strip_list_marker(line)
    return bool(re.search(r"\*\*[^*]+\*\*|:\s*\S", stripped) or len(stripped) > 20)


def _token_known(token: str, blob: str) -> bool:
    """Loosely tolerant of simple plural/gender suffix drift (e.g. "tamanho"
    in the KB vs. "tamanhos" in a natural-sounding reply) — a plain
    substring check on the raw token flags harmless morphology as a
    hallucination (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.3)."""
    if token in blob:
        return True
    if token.endswith("s") and token[:-1] in blob:
        return True
    return f"{token}s" in blob


def _unknown_significant_tokens(text: str, blob: str) -> list[str]:
    unknown: list[str] = []
    for token in re.findall(r"\b[a-z]{5,}\b", _norm(text)):
        if token in _STOPWORDS or _token_known(token, blob):
            continue
        unknown.append(token)
    return unknown


def detect_hallucination(reply: str) -> bool:
    """True when the reply cites data absent from the knowledge base."""
    if not reply.strip():
        return False

    blob = _knowledge_blob()
    reply_norm = _norm(reply)

    for line in reply.splitlines():
        if not _is_list_line(line) or not _line_claims_item(line):
            continue
        line_norm = _norm(_strip_list_marker(line))
        significant = [
            token
            for token in re.findall(r"\b[a-z]{5,}\b", line_norm)
            if token not in _STOPWORDS
        ]
        if not significant:
            continue
        if all(_token_known(token, blob) for token in significant):
            continue
        return True

    for match in _ORG_CLAIM.finditer(reply):
        claimed = _norm(match.group(1))
        if claimed and claimed not in blob:
            return True

    if any(
        marker in reply_norm
        for marker in ("item", "atividade", "temos", "oferece", "oferecemos")
    ):
        # Only check the structured (list) part of the reply against the KB —
        # free-flowing conversational sentences naturally reword things (e.g.
        # "opções", "prefere", plurals) without that being a hallucinated
        # claim. Falling back to scanning the *whole* reply when there's no
        # list used to defeat this exact reasoning and flag good, fully
        # grounded conversational replies as hallucinations (see
        # docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.3 — reproduced case:
        # "Temos miniaturas ... nos tamanhos mini (9cm) e padrão (12cm)").
        list_text = "\n".join(line for line in reply.splitlines() if _is_list_line(line))
        if list_text:
            unknown = _unknown_significant_tokens(list_text, blob)
            if unknown:
                return True

    return False


def build_knowledge_reply(user_message: str, session: SessionState | None = None) -> str | None:
    """Build a short reply using intent-aware composition (fallback to legacy FAQ)."""
    session = session or SessionState()
    intent = route_intent(user_message, session)
    composed = get_reply_composer().compose(intent, user_message, session)
    if composed and len(composed) <= _MAX_GROUNDED_REPLY_LEN:
        return composed

    store = get_knowledge_store()
    norm = _norm(user_message)
    parts: list[str] = []

    if any(token in norm for token in ("preco", "preço", "valor", "mensalidade", "plano")):
        prices = buscar_precos("")
        if prices:
            parts.append(prices)

    if any(token in norm for token in ("experimental", "matricula", "matrícula", "inscri", "encomend", "comprar")):
        enrollment = buscar_info_negocio("como comprar")
        if enrollment and "não encontrei" not in enrollment.lower():
            parts.append(enrollment.strip())

    if any(
        token in norm
        for token in (
            "item",
            "itens",
            "atividade",
            "horario",
            "horário",
        )
    ):
        listing = listar_itens()
        if listing:
            parts.append(listing)

    if not parts:
        faq = buscar_faq(user_message)
        if faq and "não encontrei" not in faq.lower():
            cleaned = faq.replace("P:", "").replace("R:", "").strip()
            if len(cleaned) < 600:
                parts.append(cleaned)

    if not parts:
        listing = listar_itens()
        if listing:
            parts.append(listing)

    body = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if not body or len(body) > _MAX_GROUNDED_REPLY_LEN:
        # `composed` was already tried and rejected above for the same
        # reason (empty or too long) — returning it here was a no-op guard
        # that always handed back the value it had just discarded
        # (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.5). `None` tells the
        # caller (`ensure_grounded_reply`) there's no short grounded
        # alternative, so it keeps the original LLM reply instead.
        return None

    return f"{body}\n\n{default_closing(get_knowledge_facts())}"


def ensure_grounded_reply(
    llm_reply: str,
    user_message: str,
    session: SessionState | None = None,
) -> tuple[str, bool, dict]:
    """Return a knowledge-grounded reply when validation or heuristics fail."""
    session = session or SessionState()
    meta: dict = {"validation_passed": True, "violations": [], "response_mode": "llm"}

    validation = get_claim_validator().validate(llm_reply, user_message, session)
    if not validation.valid:
        meta["validation_passed"] = False
        meta["violations"] = validation.violations
        intent = route_intent(user_message, session)
        composed = get_reply_composer().compose(
            intent,
            user_message,
            session,
            violation_codes=validation.violation_codes,
        )
        if composed:
            meta["response_mode"] = "grounding_fix"
            logger.warning(
                "Resposta substituída por validação factual: %s",
                validation.violations,
            )
            return composed, True, meta

    if not detect_hallucination(llm_reply):
        return llm_reply, False, meta

    grounded = build_knowledge_reply(user_message, session)
    if not grounded:
        logger.warning(
            "Alucinação detectada, mas não foi possível montar resposta da base: %s",
            llm_reply[:120],
        )
        return llm_reply, False, meta

    meta["validation_passed"] = False
    meta["response_mode"] = "grounding_fix"
    logger.warning(
        "Resposta do LLM substituída por versão ancorada na base de conhecimento"
    )
    return grounded, True, meta
