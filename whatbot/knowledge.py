"""Load and query association knowledge from a Markdown file."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Item:
    nome: str
    campos: Dict[str, str] = field(default_factory=dict)

    def as_text(self) -> str:
        lines = [f"Item: {self.nome}"]
        for key, value in self.campos.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)


@dataclass
class KnowledgeBase:
    titulo: str
    secoes: Dict[str, str]
    itens: Dict[str, Item]
    faq: Dict[str, str]
    secao_titulos: Dict[str, str] = field(default_factory=dict)

    def listar_itens(self) -> List[str]:
        return sorted(self.itens.keys())

    def titulo_secao(self, key: str) -> str:
        """Original heading text for a section (e.g. "Como comprar e pagamento"),
        keyed by its normalized form. Falls back to a title-cased version of
        the key itself when the section isn't in the file (or, since the
        normalized key is ASCII-folded, loses accents as a last resort)."""
        return self.secao_titulos.get(key) or key.title()


# Generic question/pronoun/verb words that show up in almost every FAQ
# question regardless of topic — excluded from `buscar_faq`'s keyword
# overlap scoring so two unrelated questions don't "match" just because
# they're both phrased as "Vocês fazem...?" (docs/REVISAO_CAMADA_CONVERSACIONAL.md,
# P1.4). Mirrors `knowledge_facts._GENERIC_QUESTION_WORDS` but kept
# independent to avoid a circular import (knowledge_facts imports this
# module, not the other way around).
_FAQ_FILLER_WORDS = frozenset(
    {
        "que", "quem", "qual", "quais", "quanto", "quando", "como", "onde",
        "para", "por", "com", "sem", "uma", "um", "umas", "uns", "dos", "das",
        "meu", "minha", "meus", "minhas", "seu", "sua", "seus", "suas",
        "ele", "ela", "eles", "elas", "isso", "essa", "esse", "essas", "esses",
        "voces", "vcs", "tem", "sao", "esta", "estao", "pode", "podem",
        "fazer", "fazem", "faz", "ficar", "pronto", "outro", "outros",
        "outra", "outras",
    }
)


def _stems_match(a: str, b: str) -> bool:
    """Loose match tolerant of simple verb/plural drift (e.g. "entrega" vs.
    "entregam"): true on an exact match, or when the shorter token is a
    5+ char prefix of the longer one."""
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 5 and longer.startswith(shorter)


def _faq_content_overlap(query_tokens: set, key_tokens: set) -> int:
    query_content = query_tokens - _FAQ_FILLER_WORDS
    key_content = key_tokens - _FAQ_FILLER_WORDS
    score = 0
    for qt in query_content:
        if any(_stems_match(qt, kt) for kt in key_content):
            score += 1
    return score


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text.lower().strip())


def _parse_bullet_fields(lines: List[str]) -> Dict[str, str]:
    campos: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if ":" in body:
            key, value = body.split(":", 1)
            campos[key.strip()] = value.strip()
        else:
            campos.setdefault("info", body)
    return campos


def _parse_markdown(text: str) -> KnowledgeBase:
    lines = text.splitlines()
    titulo = "Negócio"
    if lines and lines[0].startswith("# "):
        titulo = lines[0][2:].strip()

    secoes: Dict[str, str] = {}
    secao_titulos: Dict[str, str] = {}
    itens: Dict[str, Item] = {}
    faq: Dict[str, str] = {}

    current_h2: Optional[str] = None
    current_h3: Optional[str] = None
    buffer: List[str] = []
    item_buffer: List[str] = []

    def flush_section() -> None:
        nonlocal buffer, current_h2, current_h3, item_buffer
        if not current_h2:
            buffer = []
            item_buffer = []
            return

        norm_h2 = _normalize(current_h2)
        content = "\n".join(buffer).strip()

        if norm_h2 == "itens" and current_h3:
            campos = _parse_bullet_fields(item_buffer)
            itens[_normalize(current_h3)] = Item(
                nome=current_h3, campos=campos
            )
        elif norm_h2 == "faq" and current_h3:
            faq[_normalize(current_h3)] = content or current_h3
        elif current_h3 is None:
            secoes[norm_h2] = content
            secao_titulos[norm_h2] = current_h2

        buffer = []
        item_buffer = []

    for line in lines[1:]:
        if line.startswith("## "):
            flush_section()
            current_h2 = line[3:].strip()
            current_h3 = None
            continue
        if line.startswith("### "):
            flush_section()
            current_h3 = line[4:].strip()
            continue

        if current_h2 and _normalize(current_h2) == "itens" and current_h3:
            item_buffer.append(line)
        else:
            buffer.append(line)

    flush_section()
    return KnowledgeBase(
        titulo=titulo,
        secoes=secoes,
        itens=itens,
        faq=faq,
        secao_titulos=secao_titulos,
    )


def _project_root() -> Path:
    """Project root inside Docker (/whatbot) or repo root on the host."""
    docker_root = Path("/whatbot")
    if docker_root.is_dir():
        return docker_root
    return Path(__file__).resolve().parent.parent


def resolve_knowledge_path(path: str | None = None) -> Path:
    """Resolve KNOWLEDGE_PATH relative to the project root."""
    raw = (path or os.getenv("KNOWLEDGE_PATH", "")).strip()
    if raw:
        resolved = Path(raw)
        if not resolved.is_absolute():
            resolved = _project_root() / resolved
        return resolved
    default = _project_root() / "knowledge" / "base.md"
    if default.exists():
        return default
    return Path("knowledge/base.md")


def default_knowledge_path() -> Path:
    return resolve_knowledge_path()


class KnowledgeStore:
    def __init__(self, path: Path | None = None):
        self._path = path or default_knowledge_path()
        self._mtime: float | None = None
        self._base: KnowledgeBase | None = None

    @property
    def path(self) -> Path:
        return self._path

    def reload(self) -> KnowledgeBase:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Arquivo de conhecimento não encontrado: {self._path}"
            )
        text = self._path.read_text(encoding="utf-8")
        return self.reload_from_text(text)

    def reload_from_text(self, text: str) -> KnowledgeBase:
        from .knowledge_facts import reset_knowledge_facts_cache

        self._base = _parse_markdown(text)
        self._mtime = self._path.stat().st_mtime if self._path.exists() else None
        reset_knowledge_facts_cache()
        return self._base

    def get(self) -> KnowledgeBase:
        if self._base is None or not self._path.exists():
            return self.reload()
        mtime = self._path.stat().st_mtime
        if self._mtime != mtime:
            return self.reload()
        return self._base

    def _match_item(self, item: str) -> Optional[Item]:
        base = self.get()
        query = _normalize(item)
        if query in base.itens:
            return base.itens[query]
        for key, candidate in base.itens.items():
            if query in key or key in query:
                return candidate
            if query in _normalize(candidate.nome):
                return candidate
        return None

    def match_items(self, text: str) -> List[str]:
        from .knowledge_facts import match_items_in_text

        return match_items_in_text(text, self.get())

    def listar_itens(self) -> str:
        """"What do you have?" answer. A class-schedule business (with a
        `## Itens` section) gets that listing; a catalog-style business has
        no such section, so this falls back to the price table instead of
        a bare "Nenhum item cadastrado no momento." — that fallback string
        used to be sent to customers verbatim whenever this path was
        reached for a business without itens
        (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.1/P1.3)."""
        base = self.get()
        if not base.itens:
            return self.buscar_precos()
        lines = ["Itens disponíveis:"]
        for item in base.itens.values():
            horarios = item.campos.get("Horários", "consultar atendimento")
            preco = item.campos.get("Preço mensal", "consultar atendimento")
            lines.append(f"- {item.nome}: {horarios} | {preco}")
        return "\n".join(lines)

    def registered_item_names(self) -> List[str]:
        return [item.nome for item in self.get().itens.values()]

    def business_label(self) -> str:
        """Short business name from the knowledge file's title."""
        return self.get().titulo

    def format_grounding_rules_for_prompt(self) -> str:
        """Behavior rules derived from the current knowledge file (not hardcoded).

        Kept business-agnostic on purpose: earlier wording talked about
        "modalidades" and fell back to "consulte a seção de modalidades
        abaixo" (a section that may not exist in a non-class-schedule
        business, e.g. a product catalog) — see
        docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.8.
        """
        label = self.business_label()
        return "\n".join(
            [
                "REGRAS DE ATENDIMENTO:",
                "1. Use EXCLUSIVAMENTE os dados da base de conhecimento abaixo — "
                "nunca invente produtos, serviços, preços, prazos ou informações "
                "que não estejam cadastrados.",
                f"2. Você atende em nome de: {label}.",
                "3. Se a informação não estiver na base, diga com naturalidade que "
                "não tem esse dado no momento e ofereça encaminhar para atendimento "
                "humano (use [HUMAN_HANDOVER]).",
                "4. Respostas curtas (2–4 frases), tom acolhedor e natural de "
                "WhatsApp — como uma pessoa da equipe respondendo, não um sistema.",
                "5. Nunca copie rótulos técnicos da base (como \"P:\", \"R:\", "
                "nomes de seção) — converta tudo para fala natural.",
            ]
        )

    def format_full_context_for_prompt(self) -> str:
        """Full knowledge block for LLM system prompts (single source of truth)."""
        base = self.get()
        parts = [
            f"NOME OFICIAL: {base.titulo}",
        ]
        sobre = base.secoes.get("sobre")
        if sobre:
            parts.extend(["", f"{base.titulo_secao('sobre')}:", sobre])
        contato = base.secoes.get("endereco e contato")
        if contato:
            parts.extend(["", f"{base.titulo_secao('endereco e contato')}:", contato])
        # Only inject this block (and its "nunca cite outros" warning) when
        # the KB actually has a `## Itens` section — otherwise this header
        # used to appear in every single prompt with nothing under it, an
        # unconditional domain-specific string bleeding into businesses
        # that don't model themselves as a set of registered "itens"
        # (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P0.1/P1.8).
        if base.itens:
            parts.extend(
                [
                    "",
                    "ITENS CADASTRADOS (somente estes existem — nunca cite outros):",
                ]
            )
            for item in base.itens.values():
                parts.extend(["", item.as_text()])
        precos = base.secoes.get("precos")
        if precos:
            parts.extend(["", f"{base.titulo_secao('precos')}:", precos])
        como_comprar = base.secoes.get("como comprar e pagamento")
        if como_comprar:
            parts.extend(
                ["", f"{base.titulo_secao('como comprar e pagamento')}:", como_comprar]
            )
        if base.faq:
            parts.append("")
            parts.append("FAQ:")
            for question, answer in base.faq.items():
                parts.append(f"- {question}: {answer}")
        return "\n".join(parts)

    def buscar_horarios(self, item: str) -> str:
        found = self._match_item(item)
        if found is None:
            return (
                f"Item '{item}' não encontrado. "
                f"Disponíveis: {', '.join(self.get().listar_itens())}."
            )
        horarios = found.campos.get("Horários")
        if horarios:
            extra = found.campos.get("Observações")
            text = f"{found.nome}: {horarios}"
            if extra:
                text += f". Observações: {extra}"
            return text
        return f"Horários de {found.nome} não informados. Consulte o atendimento."

    def buscar_precos(self, item: str | None = None) -> str:
        base = self.get()
        if item:
            found = self._match_item(item)
            if found is None:
                return f"Item '{item}' não encontrado."
            mensal = found.campos.get("Preço mensal", "Preço mensal não informado.")
            semestral = found.campos.get("Preço semestral")
            desconto = found.campos.get("Desconto")
            parts = [f"{found.nome}: {mensal}"]
            if semestral:
                parts.append(f"Semestral: {semestral}")
            if desconto:
                parts.append(desconto)
            return ". ".join(parts)

        como_comprar = base.secoes.get("como comprar e pagamento", "")
        precos = base.secoes.get("precos", "")
        lines: list[str] = []
        # Only businesses with a `## Itens` section (class schedules,
        # service tiers) get this per-item table — a product catalog
        # without that structure previously still got the heading with
        # nothing under it (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.1).
        if base.itens:
            lines.append("Tabela de preços por item:")
            for candidate in base.itens.values():
                mensal = candidate.campos.get("Preço mensal", "consultar atendimento")
                semestral = candidate.campos.get("Preço semestral")
                entry = f"- {candidate.nome}: {mensal}"
                if semestral:
                    entry += f" | {semestral}"
                lines.append(entry)
        if precos:
            if lines:
                lines.append("")
            lines.append(f"{base.titulo_secao('precos')}:")
            lines.append(precos)
        if como_comprar:
            lines.append("")
            lines.append(f"{base.titulo_secao('como comprar e pagamento')}:")
            lines.append(como_comprar)
        return "\n".join(lines) if lines else "Preços não cadastrados no momento."

    def buscar_info(self, topico: str) -> str:
        base = self.get()
        query = _normalize(topico)

        for key, content in base.secoes.items():
            if query in key or key in query:
                title = base.titulo_secao(key)
                return f"{title}:\n{content}" if content else title

        if query in {"contato", "endereco", "endereço", "telefone"}:
            contato = base.secoes.get("endereco e contato")
            if contato:
                return f"{base.titulo_secao('endereco e contato')}:\n{contato}"

        if query in {"item", "itens", "atividades", "aulas"}:
            return self.listar_itens()

        # Keyword search across sections
        hits: List[str] = []
        for key, content in base.secoes.items():
            blob = f"{key} {content}".lower()
            if any(token in blob for token in query.split()):
                hits.append(f"{base.titulo_secao(key)}:\n{content}")

        if hits:
            return "\n\n".join(hits[:3])

        topics = ", ".join(base.titulo_secao(k) for k in base.secoes.keys())
        return (
            f"Não encontrei informações sobre '{topico}'. "
            f"Tópicos disponíveis: {topics}."
        )

    def buscar_faq(self, pergunta: str) -> str:
        """Best-matching FAQ entry, or an explicit "não encontrei" when
        nothing scores a real keyword overlap.

        The previous scoring used `token in key` as a substring check
        against the *whole key string*, not per-word — so a single
        one-or-two-letter token (e.g. "o", "de") "matched" almost any FAQ
        key, and any match with `score > 0` was accepted. That let an
        unrelated question win and get echoed back as if it were the
        customer's own (e.g. "vcs tem instagram?" returning the FAQ entry
        for delivery time) — docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.4.
        Scoring now only counts overlap between *content* words (generic
        ones like "você", "tem", "fazem" are excluded on both sides — they
        matched almost every question pair and could outscore a real,
        single-content-word match), with light tolerance for simple verb/
        plural drift (e.g. "entrega" vs. "entregam") via a shared prefix.
        """
        base = self.get()
        if not base.faq:
            return "FAQ não disponível no momento."

        query_norm = _normalize(pergunta)
        query_tokens = {t for t in re.findall(r"[a-z0-9]+", query_norm) if len(t) >= 3}
        if not query_tokens:
            return self._faq_not_found(base)

        best_key: Optional[str] = None
        best_score = 0
        for key in base.faq:
            key_tokens = set(re.findall(r"[a-z0-9]+", key))
            score = _faq_content_overlap(query_tokens, key_tokens)
            if query_norm == key:
                score += 5
            if score > best_score:
                best_score = score
                best_key = key

        if best_key and best_score >= 1:
            for question, answer in base.faq.items():
                if _normalize(question) == best_key:
                    return f"P: {question}\nR: {answer}"

        return self._faq_not_found(base)

    def _faq_not_found(self, base: KnowledgeBase) -> str:
        return (
            "Não encontrei essa pergunta no FAQ. "
            f"Perguntas frequentes: {', '.join(base.faq.keys())}."
        )


_store: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store
