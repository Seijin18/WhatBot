#!/usr/bin/env python3
"""Audit message log entries against structured knowledge facts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from whatbot.claim_validator import ClaimValidator
from whatbot.config import bootstrap_env
from whatbot.knowledge import KnowledgeStore, resolve_knowledge_path
from whatbot.knowledge_facts import build_facts_from_base, reset_knowledge_facts_cache
from whatbot.message_log import resolve_message_log_path
from whatbot.session_state import SessionState


def audit_log(path: Path) -> int:
    bootstrap_env()
    store = KnowledgeStore(path=resolve_knowledge_path())
    store.reload()
    reset_knowledge_facts_cache()
    facts = build_facts_from_base(store.get())
    validator = ClaimValidator(facts)

    issues = 0
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("kind") not in {"llm", "message"}:
                continue
            if entry.get("direction") == "in":
                continue
            text = entry.get("reply") or entry.get("text") or ""
            if not text or entry.get("source") not in {None, "bot"}:
                continue
            user_text = entry.get("user_text") or ""
            result = validator.validate(text, user_text, SessionState())
            if result.valid:
                continue
            issues += 1
            print(f"Line {line_no} phone={entry.get('phone')} violations:")
            for v in result.violations:
                print(f"  - {v}")
            snippet = text.replace("\n", " ")[:120]
            print(f"  snippet: {snippet}...")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit WhatBot message log")
    parser.add_argument(
        "--log",
        default=str(resolve_message_log_path() or ROOT / "logs" / "messages.jsonl"),
    )
    args = parser.parse_args()
    path = Path(args.log)
    if not path.exists():
        print(f"Log not found: {path}")
        sys.exit(1)
    count = audit_log(path)
    if count:
        print(f"\nTotal entries with violations: {count}")
        sys.exit(1)
    print("No factual violations detected in bot replies.")


if __name__ == "__main__":
    main()
