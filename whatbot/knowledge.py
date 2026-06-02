"""Load and query association knowledge from a Markdown file."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Modalidade:
    nome: str
    campos: Dict[str, str] = field(default_factory=dict)

    def as_text(self) -> str:
        lines = [f"Modalidade: {self.nome}"]
        for key, value in self.campos.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)


@dataclass
class KnowledgeBase:
    titulo: str
    secoes: Dict[str, str]
    modalidades: Dict[str, Modalidade]
    faq: Dict[str, str]

    def listar_modalidades(self) -> List[str]:
        return sorted(self.modalidades.keys())


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
    titulo = "Associação"
    if lines and lines[0].startswith("# "):
        titulo = lines[0][2:].strip()

    secoes: Dict[str, str] = {}
    modalidades: Dict[str, Modalidade] = {}
    faq: Dict[str, str] = {}

    current_h2: Optional[str] = None
    current_h3: Optional[str] = None
    buffer: List[str] = []
    modalidade_buffer: List[str] = []

    def flush_section() -> None:
        nonlocal buffer, current_h2, current_h3, modalidade_buffer
        if not current_h2:
            buffer = []
            modalidade_buffer = []
            return

        norm_h2 = _normalize(current_h2)
        content = "\n".join(buffer).strip()

        if norm_h2 == "modalidades" and current_h3:
            campos = _parse_bullet_fields(modalidade_buffer)
            modalidades[_normalize(current_h3)] = Modalidade(
                nome=current_h3, campos=campos
            )
        elif norm_h2 == "faq" and current_h3:
            faq[_normalize(current_h3)] = content or current_h3
        elif current_h3 is None:
            secoes[norm_h2] = content

        buffer = []
        modalidade_buffer = []

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

        if current_h2 and _normalize(current_h2) == "modalidades" and current_h3:
            modalidade_buffer.append(line)
        else:
            buffer.append(line)

    flush_section()
    return KnowledgeBase(
        titulo=titulo, secoes=secoes, modalidades=modalidades, faq=faq
    )


def _project_root() -> Path:
    """Project root inside Docker (/whatbot) or repo root on the host."""
    docker_root = Path("/whatbot")
    if docker_root.is_dir():
        return docker_root
    return Path(__file__).resolve().parent.parent


def resolve_knowledge_path(path: str | None = None) -> Path:
    """Resolve ASSOCIACAO_KNOWLEDGE_PATH relative to the project root."""
    raw = (path or os.getenv("ASSOCIACAO_KNOWLEDGE_PATH", "")).strip()
    if raw:
        resolved = Path(raw)
        if not resolved.is_absolute():
            resolved = _project_root() / resolved
        return resolved
    default = _project_root() / "knowledge" / "associacao.md"
    if default.exists():
        return default
    return Path("knowledge/associacao.md")


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

    def _match_modalidade(self, modalidade: str) -> Optional[Modalidade]:
        base = self.get()
        query = _normalize(modalidade)
        if query in base.modalidades:
            return base.modalidades[query]
        for key, item in base.modalidades.items():
            if query in key or key in query:
                return item
            if query in _normalize(item.nome):
                return item
        return None

    def match_modalidades(self, text: str) -> List[str]:
        from .knowledge_facts import match_modalidades_in_text

        return match_modalidades_in_text(text, self.get())

    def listar_modalidades(self) -> str:
        base = self.get()
        if not base.modalidades:
            return "Nenhuma modalidade cadastrada no momento."
        lines = ["Modalidades disponíveis:"]
        for item in base.modalidades.values():
            horarios = item.campos.get("Horários", "consultar secretaria")
            preco = item.campos.get("Preço mensal", "consultar secretaria")
            lines.append(f"- {item.nome}: {horarios} | {preco}")
        return "\n".join(lines)

    def registered_modalidade_names(self) -> List[str]:
        return [item.nome for item in self.get().modalidades.values()]

    def association_label(self) -> str:
        """Short association name extracted from the knowledge file."""
        base = self.get()
        sobre = base.secoes.get("sobre a associacao", "")
        match = re.search(r"associaç[aã]o\s+([^,\.\n]+)", sobre, re.I)
        if match:
            return match.group(1).strip()
        return base.titulo

    def format_grounding_rules_for_prompt(self) -> str:
        """Behavior rules derived from the current knowledge file (not hardcoded)."""
        base = self.get()
        names = self.registered_modalidade_names()
        modalidades = ", ".join(names) if names else "consulte a seção de modalidades abaixo"
        label = self.association_label()
        return "\n".join(
            [
                "REGRAS DE ATENDIMENTO:",
                "1. Use EXCLUSIVAMENTE os dados da base abaixo — nunca invente modalidades, horários, preços ou nomes.",
                f"2. A associação: {label}. Cite somente as modalidades cadastradas: {modalidades}.",
                "3. Se a informação não estiver na base, diga que não tem esse dado e use [HUMAN_HANDOVER].",
                "4. Respostas curtas (2–4 frases), tom acolhedor de WhatsApp, sem emojis.",
                "5. Não copie rótulos técnicos (P:/R:, \"Modalidade:\") — fale como pessoa real.",
            ]
        )

    def format_full_context_for_prompt(self) -> str:
        """Full knowledge block for LLM system prompts (single source of truth)."""
        base = self.get()
        parts = [
            f"NOME OFICIAL DA ASSOCIAÇÃO: {base.titulo}",
        ]
        sobre = base.secoes.get("sobre a associacao")
        if sobre:
            parts.extend(["", "Sobre:", sobre])
        contato = base.secoes.get("endereco e contato")
        if contato:
            parts.extend(["", "Endereço e contato:", contato])
        parts.extend(
            [
                "",
                "MODALIDADES CADASTRADAS (somente estas existem — nunca cite outras):",
            ]
        )
        for item in base.modalidades.values():
            parts.extend(["", item.as_text()])
        precos = base.secoes.get("precos")
        if precos:
            parts.extend(["", "Preços:", precos])
        matricula = base.secoes.get("matricula e pagamentos")
        if matricula:
            parts.extend(["", "Matrícula e pagamentos:", matricula])
        if base.faq:
            parts.append("")
            parts.append("FAQ:")
            for question, answer in base.faq.items():
                parts.append(f"- {question}: {answer}")
        return "\n".join(parts)

    def buscar_horarios(self, modalidade: str) -> str:
        item = self._match_modalidade(modalidade)
        if item is None:
            return (
                f"Modalidade '{modalidade}' não encontrada. "
                f"Disponíveis: {', '.join(self.get().listar_modalidades())}."
            )
        horarios = item.campos.get("Horários")
        if horarios:
            extra = item.campos.get("Observações")
            text = f"{item.nome}: {horarios}"
            if extra:
                text += f". Observações: {extra}"
            return text
        return f"Horários de {item.nome} não informados. Consulte a secretaria."

    def buscar_precos(self, modalidade: str | None = None) -> str:
        base = self.get()
        if modalidade:
            item = self._match_modalidade(modalidade)
            if item is None:
                return f"Modalidade '{modalidade}' não encontrada."
            mensal = item.campos.get("Preço mensal", "Preço mensal não informado.")
            semestral = item.campos.get("Preço semestral")
            desconto = item.campos.get("Desconto")
            parts = [f"{item.nome}: {mensal}"]
            if semestral:
                parts.append(f"Semestral: {semestral}")
            if desconto:
                parts.append(desconto)
            return ". ".join(parts)

        matricula = base.secoes.get("matricula e pagamentos", "")
        precos = base.secoes.get("precos", "")
        lines = ["Tabela de preços por modalidade:"]
        for item in base.modalidades.values():
            mensal = item.campos.get("Preço mensal", "consultar secretaria")
            semestral = item.campos.get("Preço semestral")
            entry = f"- {item.nome}: {mensal}"
            if semestral:
                entry += f" | {semestral}"
            lines.append(entry)
        if precos:
            lines.append("")
            lines.append("Preços:")
            lines.append(precos)
        if matricula:
            lines.append("")
            lines.append("Matrícula e pagamentos:")
            lines.append(matricula)
        return "\n".join(lines)

    def buscar_info(self, topico: str) -> str:
        base = self.get()
        query = _normalize(topico)

        for key, content in base.secoes.items():
            if query in key or key in query:
                title = key.title()
                return f"{title}:\n{content}" if content else title

        if query in {"contato", "endereco", "endereço", "telefone"}:
            contato = base.secoes.get("endereco e contato")
            if contato:
                return f"Endereço e contato:\n{contato}"

        if query in {"modalidade", "modalidades", "atividades", "aulas"}:
            return self.listar_modalidades()

        # Keyword search across sections
        hits: List[str] = []
        for key, content in base.secoes.items():
            blob = f"{key} {content}".lower()
            if any(token in blob for token in query.split()):
                hits.append(f"{key.title()}:\n{content}")

        if hits:
            return "\n\n".join(hits[:3])

        topics = ", ".join(k.title() for k in base.secoes.keys())
        return (
            f"Não encontrei informações sobre '{topico}'. "
            f"Tópicos disponíveis: {topics}."
        )

    def buscar_faq(self, pergunta: str) -> str:
        base = self.get()
        if not base.faq:
            return "FAQ não disponível no momento."

        query = _normalize(pergunta)
        best_key: Optional[str] = None
        best_score = 0

        for key, answer in base.faq.items():
            score = sum(1 for token in query.split() if token in key)
            if query in key or key in query:
                score += 3
            if score > best_score:
                best_score = score
                best_key = key

        if best_key and best_score > 0:
            for question, answer in base.faq.items():
                if _normalize(question) == best_key:
                    return f"P: {question}\nR: {answer}"

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
