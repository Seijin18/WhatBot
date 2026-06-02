"""Validate LLM replies and replace hallucinations with knowledge-base answers."""

from __future__ import annotations

import logging
import re
import unicodedata

from .claim_validator import get_claim_validator
from .intent_router import route_intent
from .knowledge import get_knowledge_store
from .reply_composer import get_reply_composer
from .session_state import SessionState
from .tools import buscar_faq, buscar_info_associacao, buscar_precos, listar_modalidades

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
        "modalidade",
        "modalidades",
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
    r"\b(?:o|a|somos\s+(?:a|o))\s+([A-Za-zÀ-ú0-9][A-Za-zÀ-ú0-9\s]{2,30}?)\s+(?:é|e\s+uma)\b",
    re.I,
)
_LIST_LINE = re.compile(r"^[\-*•\d\.)]+\s*")
_MAX_GROUNDED_REPLY_LEN = 1200


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower().strip())


def _knowledge_blob() -> str:
    return _norm(get_knowledge_store().format_full_context_for_prompt())


def _registered_names_norm() -> list[str]:
    return [_norm(name) for name in get_knowledge_store().registered_modalidade_names()]


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^[\-*•\d\.)]+\s*", "", line.strip())


def _is_list_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and _LIST_LINE.match(stripped))


def _line_claims_modality(line: str) -> bool:
    stripped = _strip_list_marker(line)
    return bool(re.search(r"\*\*[^*]+\*\*|:\s*\S", stripped) or len(stripped) > 20)


def _unknown_significant_tokens(text: str, blob: str) -> list[str]:
    unknown: list[str] = []
    for token in re.findall(r"\b[a-z]{5,}\b", _norm(text)):
        if token in _STOPWORDS or token in blob:
            continue
        unknown.append(token)
    return unknown


def detect_hallucination(reply: str) -> bool:
    """True when the reply cites data absent from the knowledge base."""
    if not reply.strip():
        return False

    blob = _knowledge_blob()
    reply_norm = _norm(reply)
    names = _registered_names_norm()

    for line in reply.splitlines():
        if not _is_list_line(line) or not _line_claims_modality(line):
            continue
        line_norm = _norm(_strip_list_marker(line))
        if any(name in line_norm for name in names):
            continue
        return True

    for match in _ORG_CLAIM.finditer(reply):
        claimed = _norm(match.group(1))
        if claimed and claimed not in blob:
            return True

    if any(
        marker in reply_norm
        for marker in ("modalidade", "atividade", "temos", "oferece", "oferecemos")
    ):
        unknown = _unknown_significant_tokens(reply, blob)
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

    if any(token in norm for token in ("experimental", "matricula", "matrícula", "inscri")):
        enrollment = buscar_info_associacao("matrícula")
        if enrollment and "não encontrei" not in enrollment.lower():
            parts.append(enrollment.strip())

    if any(
        token in norm
        for token in (
            "modalidade",
            "modalidades",
            "atividade",
            "horario",
            "horário",
        )
    ):
        listing = listar_modalidades()
        if listing:
            parts.append(listing)

    if not parts:
        faq = buscar_faq(user_message)
        if faq and "não encontrei" not in faq.lower():
            cleaned = faq.replace("P:", "").replace("R:", "").strip()
            if len(cleaned) < 600:
                parts.append(cleaned)

    if not parts:
        listing = listar_modalidades()
        if listing:
            parts.append(listing)

    body = "\n\n".join(p.strip() for p in parts if p and p.strip())
    if not body or len(body) > _MAX_GROUNDED_REPLY_LEN:
        return composed

    return (
        f"{body}\n\n"
        "Se quiser agendar aula experimental ou falar com a secretaria, é só me avisar."
    )


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
