"""Resolve waiting contacts by name or phone with disambiguation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .db import WaitingContact
from .queue import normalize_phone


@dataclass
class ContactMatch:
    contact: WaitingContact
    score: int


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return folded.encode("ascii", "ignore").decode("ascii")


def extract_phone_from_text(text: str) -> str | None:
    match = re.search(r"\d{10,15}", text)
    return normalize_phone(match.group(0)) if match else None


def _name_tokens(query: str) -> list[str]:
    folded = _fold(query)
    stop = {"o", "a", "os", "as", "de", "da", "do", "para", "pro", "pra", "cliente", "contato"}
    return [t for t in re.split(r"\W+", folded) if len(t) >= 2 and t not in stop]


def find_waiting_matches(
    query: str, waiting: list[WaitingContact]
) -> list[ContactMatch]:
    if not waiting:
        return []

    phone = extract_phone_from_text(query)
    if phone:
        exact = [c for c in waiting if c.phone == phone or c.phone.endswith(phone[-8:])]
        if exact:
            return [ContactMatch(c, 100) for c in exact]

    tokens = _name_tokens(query)
    if not tokens:
        return []

    matches: list[ContactMatch] = []
    for contact in waiting:
        name = _fold(contact.push_name or "")
        if not name:
            continue
        score = sum(1 for t in tokens if t in name)
        if tokens and name.startswith(tokens[0]):
            score += 2
        if len(tokens) >= 2 and all(t in name for t in tokens):
            score += 3
        if score > 0:
            matches.append(ContactMatch(contact, score))

    matches.sort(key=lambda m: (-m.score, m.contact.handover_at))
    top_score = matches[0].score if matches else 0
    return [m for m in matches if m.score >= max(1, top_score - 1)]


def format_disambiguation(matches: list[ContactMatch], acao: str) -> str:
    lines = [f"Encontrei *{len(matches)}* contatos parecidos. Qual deles?"]
    for idx, match in enumerate(matches[:5], start=1):
        c = match.contact
        name = c.push_name or "Sem nome"
        lines.append(f"*{idx}.* {name} — {c.phone} ({c.minutes_waiting} min)")
    lines.append("")
    lines.append(f"Responda com o *número* (1-{min(len(matches), 5)}) ou o *telefone* completo.")
    return "\n".join(lines)


def pick_from_disambiguation(
    reply: str, candidates: list[dict]
) -> WaitingContact | None:
    reply = reply.strip()
    if reply.isdigit():
        idx = int(reply)
        if 1 <= idx <= len(candidates):
            data = candidates[idx - 1]
            return _dict_to_waiting(data)
    phone = extract_phone_from_text(reply)
    if phone:
        for data in candidates:
            if data.get("phone") == phone:
                return _dict_to_waiting(data)
    return None


def waiting_to_dict(contact: WaitingContact) -> dict:
    return {
        "id": contact.id,
        "phone": contact.phone,
        "push_name": contact.push_name,
        "handover_motivo": contact.handover_motivo,
        "minutes_waiting": contact.minutes_waiting,
        "prioridade": contact.prioridade,
    }


def _dict_to_waiting(data: dict) -> WaitingContact:
    from datetime import datetime, timezone

    return WaitingContact(
        id=data["id"],
        phone=data["phone"],
        push_name=data.get("push_name"),
        handover_at=datetime.now(timezone.utc),
        handover_motivo=data.get("handover_motivo"),
        minutes_waiting=data.get("minutes_waiting", 0),
        prioridade=data.get("prioridade", 0),
        assumido_por=data.get("assumido_por"),
    )
