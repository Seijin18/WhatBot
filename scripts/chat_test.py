#!/usr/bin/env python3
"""Teste local do WhatBot sem enviar mensagens ao WhatsApp.

Exemplos:
  python scripts/chat_test.py "Quais modalidades vocês têm?"
  python scripts/chat_test.py -i
  python scripts/chat_test.py --phone 5511999999999 "Quanto custa o yoga?"
  make chat-test MSG="Olá, quero judô"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from whatbot.config import bootstrap_env, resolve_simulate_phone  # noqa: E402
from whatbot.main import _init_infra, process_customer_message  # noqa: E402
from whatbot.message_log import resolve_message_log_path  # noqa: E402
from whatbot.queue import normalize_phone  # noqa: E402


def run_chat(phone: str, text: str, push_name: str = "Terminal Test") -> dict:
    bootstrap_env()
    _init_infra()
    return process_customer_message(
        normalize_phone(phone),
        text.strip(),
        push_name=push_name,
        simulated=True,
    )


def format_human(result: dict) -> str:
    lines: list[str] = []
    lines.append("─" * 60)

    if result.get("ignored"):
        lines.append(f"Ignorado: {result.get('reason', 'sem motivo')}")
    elif result.get("handed_to_human"):
        lines.append("Handover → secretaria")
        if result.get("model_reply"):
            lines.append("")
            lines.append(result["model_reply"])
    elif result.get("model_reply"):
        lines.append("Resposta do bot:")
        lines.append("")
        lines.append(str(result["model_reply"]))
    elif result.get("message"):
        lines.append(str(result["message"]))
    else:
        lines.append("(sem texto de resposta)")

    lines.append("")
    lines.append("─" * 60)
    meta: list[str] = []
    if result.get("ok") is False:
        meta.append(f"erro={result.get('error', '?')}")
        if result.get("detail"):
            meta.append(f"detalhe={result['detail']}")
    else:
        meta.append("ok")
    meta.append("simulado (nada enviado ao WhatsApp)")
    if result.get("simulated"):
        meta.append("via process_customer_message")
    lines.append(" | ".join(meta))

    log_path = resolve_message_log_path()
    if log_path:
        lines.append(f"Log JSONL: {log_path}")
    return "\n".join(lines)


def interactive_loop(phone: str) -> int:
    print(f"Chat de teste WhatBot (simulado) — cliente {phone}")
    print("Digite a mensagem e pressione Enter. Comandos: /sair, /json")
    print()

    json_mode = False
    while True:
        try:
            text = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not text:
            continue
        if text.lower() in {"/sair", "/exit", "/quit"}:
            return 0
        if text.lower() == "/json":
            json_mode = not json_mode
            print(f"modo json: {'on' if json_mode else 'off'}")
            continue

        try:
            result = run_chat(phone, text)
        except Exception as exc:
            print(f"ERRO: {exc}", file=sys.stderr)
            continue

        if json_mode:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_human(result))
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Testa o WhatBot localmente sem WhatsApp (simulated=True)."
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="Mensagem do cliente simulado",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Modo conversa contínua no terminal",
    )
    parser.add_argument(
        "--phone",
        default=resolve_simulate_phone(),
        help="Número simulado do cliente (padrão: DEFAULT_TEST_PHONE)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime o resultado bruto em JSON",
    )
    args = parser.parse_args(argv)

    phone = normalize_phone(args.phone)

    if args.interactive:
        return interactive_loop(phone)

    if not args.message:
        parser.error("informe a mensagem ou use -i para modo interativo")

    try:
        result = run_chat(phone, args.message)
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_human(result))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
