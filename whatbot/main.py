"""Windmill entrypoint: main(payload: dict)"""

from __future__ import annotations

import os
import logging
from typing import Dict, Any

from .config import (
    SYSTEM_PROMPTS,
    ENV_DB_DSN,
    ENV_EVOLUTION_API_KEY,
    ENV_EVOLUTION_API_INSTANCE_NAME,
    bootstrap_env,
    is_placeholder,
    is_test_mode,
    resolve_db_dsn,
    resolve_evolution_base_url,
    resolve_simulate_phone,
    should_respond_to_customer,
)
from .db import Database
from .whatsapp import WhatsAppClient
from .llm import LlmUnavailableError, create_llm_client
from .domain import (
    build_handover_customer_message,
    detectar_intencao_human_handoff,
    detectar_pedido_atendimento_humano,
    executar_handover_para_secretaria,
)
from .fallback import build_knowledge_fallback, trim_history_for_chat
from .webhook import parse_evolution_payload, parse_outgoing_staff_message
from .admin import handle_admin_message
from .admin_nlu import (
    DEFAULT_CASUAL_TEST_MESSAGE,
    is_casual_test_message,
    parse_simulate_command,
)
from .queue import (
    check_long_wait_notifications,
    handle_staff_outgoing_message,
    is_admin_phone,
    normalize_phone,
    run_periodic_queue_checks,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatbot")

MODEL_UNAVAILABLE_MSG = (
    "Estou com instabilidade no momento. Tente novamente em instantes "
    "ou digite *quero falar com a secretaria* se precisar de ajuda humana."
)


_db: Database | None = None
_whatsapp: WhatsAppClient | None = None
_llm = None


def _init_infra() -> None:
    global _db, _whatsapp, _llm
    bootstrap_env()
    if _db is None:
        dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
        if is_placeholder(dsn):
            raise RuntimeError("DB_DSN não configurado")
        _db = Database(dsn)
        _db.ensure_schema()
    if _whatsapp is None:
        api_key = os.getenv(ENV_EVOLUTION_API_KEY)
        instance_name = os.getenv(ENV_EVOLUTION_API_INSTANCE_NAME)
        base_url = resolve_evolution_base_url(os.getenv("EVOLUTION_API_BASE_URL"))
        if is_placeholder(api_key) or is_placeholder(instance_name):
            raise RuntimeError(
                "EVOLUTION_API_KEY ou EVOLUTION_API_INSTANCE_NAME não configurados"
            )
        _whatsapp = WhatsAppClient(
            api_key=api_key, instance_name=instance_name, base_url=base_url
        )
    if _llm is None:
        _llm = create_llm_client()
    if is_test_mode():
        from .config import get_test_phones

        logger.warning(
            "TEST_MODE ativo — o bot responde apenas a TEST_PHONES: %s",
            ", ".join(get_test_phones()) or "(lista vazia)",
        )


def build_system_prompt_for_status(status: str) -> str:
    return SYSTEM_PROMPTS.get(status, SYSTEM_PROMPTS["novo_lead"])


def normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Accept direct whatbot payloads or Evolution API webhook bodies."""
    if payload.get("from_number") or payload.get("from"):
        return payload
    if payload.get("event") and payload.get("data"):
        parsed = parse_evolution_payload(payload)
        if parsed:
            return parsed
    return payload


def _resolve_admin_simulate(text: str) -> tuple[str | None, str] | None:
    sim = parse_simulate_command(text)
    if sim:
        return sim
    if is_casual_test_message(text):
        return None, DEFAULT_CASUAL_TEST_MESSAGE
    return None


def _ensure_admin_contact(
    admin_phone: str, push_name: str | None = None
) -> Any:
    contact = _db.get_contact_by_phone(admin_phone)
    if contact is None:
        contact = _db.create_contact(
            phone=admin_phone, status="novo_lead", ia_ativa=True, push_name=push_name
        )
    elif push_name:
        _db.update_contact_push_name(contact.id, push_name)
    return contact


def run_admin_simulation(
    admin_phone: str,
    sim_phone: str | None,
    sim_text: str,
    push_name: str | None = None,
) -> Dict[str, Any]:
    admin_phone = normalize_phone(admin_phone)
    sim_phone = normalize_phone(resolve_simulate_phone(sim_phone))
    logger.info("Simulação cliente %s por admin %s", sim_phone, admin_phone)
    result = process_customer_message(
        sim_phone,
        sim_text,
        push_name=f"Simulado por {push_name or admin_phone}",
        simulated=True,
    )
    reply = result.get("model_reply") or result.get("message") or str(result)
    if result.get("handed_to_human"):
        reply = (
            f"{reply}\n\n_(Handover simulado — o bot pararia de responder a este cliente.)_"
        )
    try:
        _whatsapp.send_text(
            admin_phone,
            f"🧪 *Teste como cliente* ({sim_phone}):\n{reply}",
        )
    except Exception:
        logger.exception("Falha ao enviar simulação ao admin")
    result["simulated_by"] = admin_phone
    result["simulated_as"] = sim_phone
    return result


def check_queue(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Scheduled Windmill job: queue maintenance and daily summary."""
    try:
        _init_infra()
    except Exception as e:
        logger.exception("Erro inicializando infra: %s", e)
        return {"ok": False, "error": "infra_init_failed", "detail": str(e)}
    return {"ok": True, **run_periodic_queue_checks(_db, _whatsapp)}


def process_customer_message(
    phone: str,
    text: str,
    push_name: str | None = None,
    simulated: bool = False,
) -> Dict[str, Any]:
    """Handle an inbound customer message (or admin simulation)."""
    queue_check: Dict[str, Any] = {}
    try:
        queue_check = check_long_wait_notifications(_db, _whatsapp)
    except Exception:
        logger.exception("Falha ao verificar fila de espera prolongada")

    try:
        _db.process_auto_reactivations()
    except Exception:
        logger.exception("Falha na reativação automática do bot")

    try:
        contact = _db.get_contact_by_phone(phone)
        if contact is None:
            contact = _db.create_contact(
                phone=phone, status="novo_lead", ia_ativa=True, push_name=push_name
            )
            logger.info("Criado novo contato: %s", contact.phone)
        else:
            if push_name:
                _db.update_contact_push_name(contact.id, push_name)
            logger.info(
                "Contato existente: %s (ia_ativa=%s)", contact.phone, contact.ia_ativa
            )
    except Exception as e:
        logger.exception("Erro DB ao obter/criar contato: %s", e)
        return {"ok": False, "error": "db_error", "detail": str(e)}

    if not contact.ia_ativa:
        logger.info("IA desativada para %s - early return", contact.phone)
        try:
            _db.save_message(contact.id, direction="in", text=text)
        except Exception:
            logger.exception("Falha ao salvar mensagem na fila")
        return {
            "ok": True,
            "handed_to_human": True,
            "message": "IA desativada para este contato",
            "queue_check": queue_check,
            "simulated": simulated,
        }

    try:
        _db.save_message(contact.id, direction="in", text=text)
    except Exception:
        logger.exception("Falha ao salvar mensagem de entrada; prosseguindo")

    if detectar_pedido_atendimento_humano(text):
        try:
            result = executar_handover_para_secretaria(
                phone=phone,
                contact_id=contact.id,
                whatsapp=_whatsapp,
                db=_db,
                logger=logger,
                motivo="pedido_do_cliente",
                push_name=push_name,
                user_message=text,
                simulated=simulated,
            )
            result["queue_check"] = queue_check
            result["simulated"] = simulated
            return result
        except Exception as e:
            logger.exception("Erro durante handover: %s", e)
            return {"ok": False, "error": "handover_failed", "detail": str(e)}

    try:
        history = trim_history_for_chat(
            _db.get_recent_messages(contact.id, limit=10), text
        )
    except Exception:
        logger.exception("Falha ao carregar histórico; prosseguindo sem histórico")
        history = []

    system_prompt = build_system_prompt_for_status(contact.status)
    model_reply: str | None = None
    used_fallback = False

    try:
        model_reply = _llm.chat(
            system_prompt=system_prompt, recent_history=history, user_message=text
        )
    except LlmUnavailableError as e:
        logger.warning("LLM indisponível: %s", e)
        reason = "quota" if "quota" in str(e).lower() or "resource_exhausted" in str(e).lower() else "error"
        model_reply = build_knowledge_fallback(text, reason=reason)
        used_fallback = bool(model_reply)
        if not model_reply:
            if not simulated:
                _whatsapp.send_text(phone, MODEL_UNAVAILABLE_MSG)
                _db.save_message(contact.id, direction="out", text=MODEL_UNAVAILABLE_MSG)
            return {"ok": False, "error": "gemini_quota", "detail": str(e)}
    except Exception as e:
        logger.exception("Erro no modelo após retries Gemini: %s", e)
        model_reply = build_knowledge_fallback(text)
        used_fallback = bool(model_reply)
        if not model_reply:
            if not simulated:
                _whatsapp.send_text(phone, MODEL_UNAVAILABLE_MSG)
                _db.save_message(contact.id, direction="out", text=MODEL_UNAVAILABLE_MSG)
            return {"ok": False, "error": "model_error", "detail": str(e)}

    if used_fallback:
        logger.warning("Resposta via fallback offline (Gemini indisponível)")

    try:
        needs_human = detectar_intencao_human_handoff(model_reply)
    except Exception:
        logger.exception("Erro detectando necessidade de humano; assumindo False")
        needs_human = False

    if needs_human:
        try:
            result = executar_handover_para_secretaria(
                phone=phone,
                contact_id=contact.id,
                whatsapp=_whatsapp,
                db=_db,
                logger=logger,
                motivo="decisao_do_modelo",
                push_name=push_name,
                user_message=text,
                simulated=simulated,
                customer_message=build_handover_customer_message(model_reply),
            )
            result["queue_check"] = queue_check
            result["simulated"] = simulated
            return result
        except Exception as e:
            logger.exception("Erro durante handover: %s", e)
            return {"ok": False, "error": "handover_failed", "detail": str(e)}

    try:
        if not simulated:
            _whatsapp.send_text(phone, model_reply)
        else:
            logger.info("Simulação: resposta não enviada ao cliente fictício %s", phone)
        _db.save_message(contact.id, direction="out", text=model_reply)
        return {
            "ok": True,
            "sent": True,
            "model_reply": model_reply,
            "queue_check": queue_check,
            "simulated": simulated,
        }
    except Exception as e:
        logger.exception("Erro ao enviar mensagem via Evolution API: %s", e)
        return {"ok": False, "error": "send_failed", "detail": str(e)}


def main(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Entry function for Windmill. Accepts whatbot or Evolution API webhook payloads."""
    original = payload

    try:
        _init_infra()
    except Exception as e:
        logger.exception("Erro inicializando infra: %s", e)
        return {"ok": False, "error": "infra_init_failed", "detail": str(e)}

    # Secretariat replied to customer via WhatsApp Business (fromMe)
    if original.get("event"):
        outgoing = parse_outgoing_staff_message(original)
        if outgoing:
            to_phone = normalize_phone(outgoing["to_number"])
            text = (outgoing.get("text") or "").strip()
            if is_admin_phone(to_phone) and text:
                sim = _resolve_admin_simulate(text)
                if sim:
                    sim_phone, sim_text = sim
                    return run_admin_simulation(to_phone, sim_phone, sim_text)
                return {
                    "ok": True,
                    "ignored": True,
                    "reason": "outgoing_to_admin",
                    "hint": "Use o celular pessoal admin ou #simular para testar o bot",
                }
            result = handle_staff_outgoing_message(
                outgoing["to_number"], _db, _whatsapp
            )
            try:
                result["queue_check"] = check_long_wait_notifications(_db, _whatsapp)
            except Exception:
                logger.exception("Falha ao verificar fila após resposta staff")
            return result

    payload = normalize_payload(payload)
    logger.info(
        "Recebido payload: %s",
        {k: payload.get(k) for k in ("from_number", "text", "push_name")},
    )

    phone = payload.get("from_number") or payload.get("from")
    text = (payload.get("text") or payload.get("message") or "").strip()
    push_name = payload.get("push_name")

    if not phone or not text:
        if original.get("event"):
            logger.info("Evento Evolution ignorado: %s", original.get("event"))
            return {"ok": True, "ignored": True, "event": original.get("event")}
        logger.warning("Payload incompleto: phone/text ausentes")
        return {"ok": False, "error": "invalid_payload"}

    if is_admin_phone(phone):
        sim = _resolve_admin_simulate(text)
        if sim:
            sim_phone, sim_text = sim
            return run_admin_simulation(phone, sim_phone, sim_text, push_name=push_name)

        try:
            contact = _ensure_admin_contact(phone, push_name)
            result = handle_admin_message(
                phone=phone,
                text=text,
                db=_db,
                whatsapp=_whatsapp,
                contact_id=contact.id,
            )
            return result
        except Exception as e:
            logger.exception("Erro no comando admin: %s", e)
            return {"ok": False, "error": "admin_command_failed", "detail": str(e)}

    phone = normalize_phone(phone)
    if not should_respond_to_customer(phone):
        logger.info("Modo teste: ignorando mensagem de %s (fora de TEST_PHONES)", phone)
        return {"ok": True, "ignored": True, "reason": "test_mode"}

    return process_customer_message(phone, text, push_name=push_name)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        try:
            payload = json.loads(sys.argv[1])
            resultado = main(payload)
            print(json.dumps(resultado, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"Erro executando payload: {e}")
            sys.exit(1)
    else:
        sample = {
            "from_number": "5511999999999",
            "text": "Olá, quero informações sobre yoga",
        }
        out = main(sample)
        print(json.dumps(out, indent=2, ensure_ascii=False))
