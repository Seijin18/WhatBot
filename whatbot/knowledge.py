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


def default_knowledge_path() -> Path:
    env_path = os.getenv("ASSOCIACAO_KNOWLEDGE_PATH", "").strip()
    if env_path:
        return Path(env_path)
    for candidate in (
        Path("/whatbot/knowledge/associacao.md"),
        Path("knowledge/associacao.md"),
    ):
        if candidate.exists():
            return candidate
    return Path("knowledge/associacao.md")


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
        self._base = _parse_markdown(text)
        self._mtime = self._path.stat().st_mtime
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
