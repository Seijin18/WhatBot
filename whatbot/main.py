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
from .channels import (
    INSTAGRAM,
    WHATSAPP,
    ChannelError,
    ChannelRouter,
    EvolutionApiClient,
    UnknownChannelError,
    normalize_channel,
    validate_channel,
)
from .channels.instagram import InstagramClient, instagram_last_inbound_lookup
from .db import Database
from .instagram_health import record_send_result
from .llm import LlmUnavailableError, create_llm_client
from .domain import (
    build_handover_customer_message,
    detectar_intencao_human_handoff,
    detectar_pedido_atendimento_humano,
    executar_handover_para_secretaria,
)
from .fallback import build_knowledge_fallback, trim_history_for_chat
from .grounding import ensure_grounded_reply
from .intent_router import route_intent
from .prompt_builder import build_enriched_system_prompt
from .session_state import SessionState, history_summary, update_session_state
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
from .message_log import log_inbound, log_llm_turn, log_outbound

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatbot")

MODEL_UNAVAILABLE_MSG = (
    "Estou com instabilidade no momento. Tente novamente em instantes "
    "ou digite *quero falar com um atendente* se precisar de ajuda humana."
)


_db: Database | None = None
_router: ChannelRouter | None = None
_llm = None


def _register_instagram_client_if_configured(router: ChannelRouter, db: Database) -> None:
    """Register `InstagramClient` only once a real credential has been stored.

    The Instagram OAuth flow (`scripts/ig_oauth.py`) is a manual, external
    step run by an operator against the real Meta app — it cannot happen
    inside `_init_infra()`. Until `canal_credenciais` has a row for
    `instagram`, the channel simply isn't registered: the WhatsApp path
    keeps working unaffected, and `ChannelRouter` already raises
    `UnknownChannelError` (not a silent no-op) for any Instagram traffic in
    the meantime, per the "Canal sem cliente registrado falha
    explicitamente" requirement in `openspec/specs/channels/spec.md`.
    """
    try:
        credential = db.get_channel_credential(INSTAGRAM)
    except Exception:
        logger.exception("Erro consultando credencial do Instagram; canal não registrado")
        return
    if credential is None:
        logger.info(
            "Nenhuma credencial do Instagram em canal_credenciais — canal não "
            "registrado (rode scripts/ig_oauth.py para ativar)"
        )
        return
    router.register(
        InstagramClient(
            access_token=credential.access_token,
            account_id=credential.account_id,
            last_inbound_lookup=instagram_last_inbound_lookup(db),
        )
    )


def _init_infra() -> None:
    global _db, _router, _llm
    bootstrap_env()
    if _db is None:
        dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
        if is_placeholder(dsn):
            raise RuntimeError("DB_DSN não configurado")
        _db = Database(dsn)
        _db.ensure_schema()
    if _router is None:
        api_key = os.getenv(ENV_EVOLUTION_API_KEY)
        instance_name = os.getenv(ENV_EVOLUTION_API_INSTANCE_NAME)
        base_url = resolve_evolution_base_url(os.getenv("EVOLUTION_API_BASE_URL"))
        if is_placeholder(api_key) or is_placeholder(instance_name):
            raise RuntimeError(
                "EVOLUTION_API_KEY ou EVOLUTION_API_INSTANCE_NAME não configurados"
            )
        _router = ChannelRouter()
        _router.register(
            EvolutionApiClient(
                api_key=api_key, instance_name=instance_name, base_url=base_url
            )
        )
        _register_instagram_client_if_configured(_router, _db)
        logger.info("Canais ativos: %s", ", ".join(_router.channels))
    if _llm is None:
        _llm = create_llm_client()
    if is_test_mode():
        from .config import get_test_identities

        logger.warning(
            "TEST_MODE ativo — o bot responde apenas às listas por canal "
            "(TEST_PHONES para whatsapp: %s | TEST_IGSIDS para instagram: %s)",
            ", ".join(get_test_identities("whatsapp")) or "(lista vazia)",
            ", ".join(get_test_identities("instagram")) or "(lista vazia)",
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
    canal: str | None = None,
) -> Dict[str, Any]:
    admin_phone = normalize_phone(admin_phone)
    canal = normalize_channel(canal)
    if canal == WHATSAPP:
        sim_phone = normalize_phone(resolve_simulate_phone(sim_phone))
    else:
        sim_phone = sim_phone or resolve_simulate_phone(None)
    logger.info(
        "Simulação cliente %s (%s) por admin %s", sim_phone, canal, admin_phone
    )
    result = process_customer_message(
        sim_phone,
        sim_text,
        push_name=f"Simulado por {push_name or admin_phone}",
        simulated=True,
        canal=canal,
    )
    reply = result.get("model_reply") or result.get("message") or str(result)
    if result.get("handed_to_human"):
        reply = (
            f"{reply}\n\n_(Handover simulado — o bot pararia de responder a este cliente.)_"
        )
    try:
        _router.send_admin_text(
            admin_phone,
            f"🧪 *Teste como cliente* ({sim_phone}):\n{reply}",
            source="simulation",
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
    return {"ok": True, **run_periodic_queue_checks(_db, _router)}


def process_customer_message(
    phone: str,
    text: str,
    push_name: str | None = None,
    simulated: bool = False,
    canal: str | None = None,
) -> Dict[str, Any]:
    """Handle an inbound customer message (or admin simulation)."""
    canal = normalize_channel(canal)
    queue_check: Dict[str, Any] = {}
    try:
        queue_check = check_long_wait_notifications(_db, _router)
    except Exception:
        logger.exception("Falha ao verificar fila de espera prolongada")

    try:
        _db.process_auto_reactivations()
    except Exception:
        logger.exception("Falha na reativação automática do bot")

    try:
        contact = _db.get_contact_by_phone(phone, canal=canal)
        if contact is None:
            contact = _db.create_contact(
                phone=phone,
                status="novo_lead",
                ia_ativa=True,
                push_name=push_name,
                canal=canal,
            )
            logger.info("Criado novo contato: %s", contact.label)
        else:
            if push_name and not simulated:
                # Guarded by `not simulated`: an admin simulation must never
                # overwrite a real contact's push_name (e.g. "Maria Real" ->
                # "Simulado por 5511900000001") if `sim_phone` happens to
                # collide with an existing customer.
                _db.update_contact_push_name(contact.id, push_name)
            logger.info(
                "Contato existente: %s (ia_ativa=%s)", contact.label, contact.ia_ativa
            )
    except Exception as e:
        logger.exception("Erro DB ao obter/criar contato: %s", e)
        return {"ok": False, "error": "db_error", "detail": str(e)}

    if not simulated:
        try:
            # Feeds the Instagram messaging-window check (whatbot/channels/instagram.py);
            # harmless to record for every channel, kept here since this is the
            # single canal-agnostic entry point for inbound customer messages.
            # Guarded by `not simulated`: an admin testing the bot via
            # simulation must never make it look like the real customer just
            # wrote in — that would reopen a messaging window that is
            # actually closed and let real sends through that Meta would
            # refuse/penalize (see critic Bloqueador 3).
            _db.update_contact_last_inbound(contact.id)
        except Exception:
            logger.exception("Falha ao registrar last_inbound_at; prosseguindo")

    if not contact.ia_ativa:
        logger.info("IA desativada para %s - early return", contact.label)
        if not simulated:
            # Guarded by `not simulated`: a simulation must never leave a
            # trace in the real contact's message history.
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

    if not simulated:
        # Guarded by `not simulated`: a simulated conversation must never be
        # recorded in the real contact's message history.
        try:
            _db.save_message(contact.id, direction="in", text=text)
        except Exception:
            logger.exception("Falha ao salvar mensagem de entrada; prosseguindo")

    log_inbound(
        phone,
        text,
        canal=canal,
        push_name=push_name,
        contact_id=contact.id,
        source="customer",
        simulated=simulated,
        contact_status=contact.status,
        ia_ativa=contact.ia_ativa,
    )

    if detectar_pedido_atendimento_humano(text):
        try:
            result = executar_handover_para_secretaria(
                phone=phone,
                contact_id=contact.id,
                router=_router,
                db=_db,
                logger=logger,
                motivo="pedido_do_cliente",
                push_name=push_name,
                user_message=text,
                simulated=simulated,
                canal=canal,
            )
            result["queue_check"] = queue_check
            result["simulated"] = simulated
            return result
        except Exception as e:
            logger.exception("Erro durante handover: %s", e)
            return {"ok": False, "error": "handover_failed", "detail": str(e)}

    try:
        history = trim_history_for_chat(
            _db.get_recent_messages(contact.id, limit=6), text
        )
    except Exception:
        logger.exception("Falha ao carregar histórico; prosseguindo sem histórico")
        history = []

    session = SessionState.from_dict(contact.session_state or {})
    intent_result = route_intent(text, session, history)
    session = update_session_state(session, text, intent_result.intent, history)
    hist_summary = history_summary(history)

    system_prompt = build_enriched_system_prompt(
        build_system_prompt_for_status(contact.status),
        intent=intent_result,
        session=session,
        history_summary=hist_summary,
    )
    model_reply: str | None = None
    used_fallback = False
    response_mode = "llm"
    grounding_meta: Dict[str, Any] = {}

    # Every customer message goes to the LLM first — no intent bypasses it
    # with a canned template. Factual correctness for high-stakes replies
    # (prices, deadlines, etc.) is enforced *after* generation by
    # `ensure_grounded_reply()` below, which reprompts/corrects rather than
    # skipping the model outright (docs/REVISAO_CAMADA_CONVERSACIONAL.md, P1.2:
    # a pre-generation template gate here previously replaced every reply for
    # a "high risk" intent, defeating the point of having an LLM).
    if model_reply is None:
        try:
            model_reply = _llm.chat(
                system_prompt=system_prompt,
                recent_history=history,
                user_message=text,
            )
        except LlmUnavailableError as e:
            logger.warning("LLM indisponível: %s", e)
            reason = "quota" if "quota" in str(e).lower() or "resource_exhausted" in str(e).lower() else "error"
            model_reply = build_knowledge_fallback(text, reason=reason)
            used_fallback = bool(model_reply)
            response_mode = "fallback"
            if not model_reply:
                if not simulated:
                    _router.send_text(
                        phone,
                        MODEL_UNAVAILABLE_MSG,
                        canal=canal,
                        source="system",
                        contact_id=contact.id,
                    )
                    # The message above already reached the customer at this
                    # point — a bookkeeping failure below must not surface as
                    # an exception (it would be caught upstream in `main()`
                    # as `processing_failed`, roll back the webhook
                    # idempotency record and cause the retry to resend this
                    # same notice to the real customer; critic: risco de
                    # envio duplicado).
                    try:
                        _db.save_message(
                            contact.id, direction="out", text=MODEL_UNAVAILABLE_MSG
                        )
                    except Exception:
                        logger.exception(
                            "Falha ao salvar aviso de indisponibilidade; "
                            "prosseguindo (mensagem já foi entregue ao cliente)"
                        )
                return {"ok": False, "error": "gemini_quota", "detail": str(e)}
        except Exception as e:
            logger.exception("Erro no modelo após retries Gemini: %s", e)
            model_reply = build_knowledge_fallback(text)
            used_fallback = bool(model_reply)
            response_mode = "fallback"
            if not model_reply:
                if not simulated:
                    _router.send_text(
                        phone,
                        MODEL_UNAVAILABLE_MSG,
                        canal=canal,
                        source="system",
                        contact_id=contact.id,
                    )
                    # Same reasoning as the `LlmUnavailableError` branch above:
                    # the message already reached the customer, so a
                    # bookkeeping failure here must stay best-effort and not
                    # trigger a webhook-idempotency rollback + resend.
                    try:
                        _db.save_message(
                            contact.id, direction="out", text=MODEL_UNAVAILABLE_MSG
                        )
                    except Exception:
                        logger.exception(
                            "Falha ao salvar aviso de indisponibilidade; "
                            "prosseguindo (mensagem já foi entregue ao cliente)"
                        )
                return {"ok": False, "error": "model_error", "detail": str(e)}

    if used_fallback:
        logger.warning("Resposta via fallback offline (Gemini indisponível)")

    grounding_corrected = False
    original_llm_reply = model_reply
    if model_reply and not used_fallback and response_mode == "llm":
        model_reply, grounding_corrected, grounding_meta = ensure_grounded_reply(
            model_reply, text, session
        )
        if grounding_corrected:
            response_mode = grounding_meta.get("response_mode", "grounding_fix")

    if not simulated:
        # Guarded by `not simulated`: a simulation must not mutate the real
        # contact's conversational session state.
        try:
            _db.update_contact_session_state(contact.id, session.to_dict())
        except Exception:
            logger.exception("Falha ao persistir session_state")

    llm_model = os.getenv("OLLAMA_MODEL") if os.getenv("LLM_PROVIDER", "gemini") == "ollama" else os.getenv("GEMINI_MODEL")
    log_llm_turn(
        phone,
        text,
        model_reply or "",
        canal=canal,
        contact_id=contact.id,
        contact_status=contact.status,
        used_fallback=used_fallback,
        llm_model=llm_model,
        simulated=simulated,
        grounding_corrected=grounding_corrected,
        original_llm_reply=original_llm_reply if grounding_corrected else None,
        intent=intent_result.intent,
        response_mode=response_mode,
        validation_passed=grounding_meta.get("validation_passed", True),
        violations=grounding_meta.get("violations"),
    )

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
                router=_router,
                db=_db,
                logger=logger,
                motivo="decisao_do_modelo",
                push_name=push_name,
                user_message=text,
                simulated=simulated,
                customer_message=build_handover_customer_message(model_reply),
                canal=canal,
            )
            result["queue_check"] = queue_check
            result["simulated"] = simulated
            return result
        except Exception as e:
            logger.exception("Erro durante handover: %s", e)
            return {"ok": False, "error": "handover_failed", "detail": str(e)}

    try:
        if not simulated:
            _router.send_text(
                phone,
                model_reply,
                canal=canal,
                source="bot",
                contact_id=contact.id,
            )
            if canal == INSTAGRAM:
                # Requirement "Alertas de saúde da integração": the real
                # send path is the only place a consecutive-failure streak
                # can be observed (critic BLOQUEADOR 1 — previously nothing
                # called this outside of tests, so the alert never fired in
                # production). `record_send_result` is best-effort and never
                # raises.
                record_send_result(_db, _router, canal, success=True)
        else:
            log_outbound(
                phone,
                model_reply,
                canal=canal,
                source="bot",
                contact_id=contact.id,
                simulated=True,
                delivery="skipped",
            )
            logger.info("Simulação: resposta não enviada ao cliente fictício %s", phone)
    except ChannelError as e:
        logger.exception("Falha de entrega no canal %s: %s", e.canal, e)
        if e.canal == INSTAGRAM:
            record_send_result(_db, _router, e.canal, success=False)
        return {
            "ok": False,
            "error": "send_failed",
            "canal": e.canal,
            "retryable": e.retryable,
            "detail": str(e),
        }
    except Exception as e:
        logger.exception("Erro ao enviar resposta ao cliente: %s", e)
        return {"ok": False, "error": "send_failed", "detail": str(e)}

    # The reply is already delivered to the customer (or this is a
    # simulation, where nothing was sent) at this point — a bookkeeping
    # failure below must stay best-effort and never turn the return into
    # `ok: False`. `main()` deletes the webhook-idempotency record whenever
    # `ok` is falsy, and the next redelivery of the same `message_id` would
    # reprocess from scratch and resend this reply to the real customer
    # (critic: risco de envio duplicado ao cliente real).
    if not simulated:
        # Guarded by `not simulated`: a simulation must never leave a trace
        # in the real contact's message history.
        try:
            _db.save_message(contact.id, direction="out", text=model_reply)
        except Exception:
            logger.exception(
                "Falha ao salvar mensagem de saída; prosseguindo (envio já ocorreu)"
            )

    return {
        "ok": True,
        "sent": True,
        "model_reply": model_reply,
        "queue_check": queue_check,
        "simulated": simulated,
        "intent": intent_result.intent,
        "response_mode": response_mode,
    }


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
            log_outbound(
                to_phone,
                text,
                source="staff",
                delivery="whatsapp_business",
                canal=outgoing.get("canal") or WHATSAPP,
            )
            if is_admin_phone(to_phone) and text:
                sim = _resolve_admin_simulate(text)
                if sim:
                    sim_phone, sim_text = sim
                    return run_admin_simulation(
                        to_phone, sim_phone, sim_text, canal=outgoing.get("canal")
                    )
                return {
                    "ok": True,
                    "ignored": True,
                    "reason": "outgoing_to_admin",
                    "hint": "Use o celular pessoal admin ou #simular para testar o bot",
                }
            result = handle_staff_outgoing_message(
                outgoing["to_number"], _db, _router
            )
            try:
                result["queue_check"] = check_long_wait_notifications(_db, _router)
            except Exception:
                logger.exception("Falha ao verificar fila após resposta staff")
            return result

    payload = normalize_payload(payload)
    logger.info(
        "Recebido payload: %s",
        {k: payload.get(k) for k in ("from_number", "text", "push_name")},
    )

    try:
        canal = validate_channel(payload.get("canal"))
    except UnknownChannelError as e:
        logger.warning("Payload recusado na borda: %s", e)
        return {
            "ok": False,
            "error": "unsupported_channel",
            "canal": payload.get("canal"),
            "detail": str(e),
        }

    # Idempotência de entrega de webhook (instagram-ingestion-service): a
    # reentrega de um evento já visto é descartada aqui, na porta de entrada
    # compartilhada por qualquer transporte (Windmill síncrono para
    # WhatsApp, `whatbot/ingress.py` em background para o Instagram) — evita
    # duplicar a resposta ao cliente sem depender de dedupe no transporte.
    message_id = payload.get("message_id")
    if message_id:
        try:
            is_new_event = _db.record_webhook_event(canal, message_id)
        except Exception:
            logger.exception(
                "Falha ao checar idempotência do evento; prosseguindo sem dedupe"
            )
            is_new_event = True
        if not is_new_event:
            logger.info(
                "Evento duplicado descartado: canal=%s message_id=%s", canal, message_id
            )
            return {"ok": True, "ignored": True, "reason": "duplicate_message_id"}

        # Bloqueador 2 (critic): se o processamento falhar *depois* do
        # registro acima, a reentrega da Meta seria descartada como
        # duplicata para sempre e o cliente nunca receberia resposta —
        # perda silenciosa. Desfaz o registro (`delete_webhook_event`)
        # sempre que o processamento não termina em sucesso, para que a
        # próxima reentrega do mesmo `message_id` seja reprocessada em vez
        # de descartada. Best-effort: se o rollback em si falhar, loga e
        # segue — pior caso volta ao comportamento anterior (perda), não
        # cria um novo modo de falha.
        try:
            result = _dispatch_payload(payload, original, canal)
        except Exception as e:
            logger.exception(
                "Erro processando evento; desfazendo idempotência para permitir reentrega: %s",
                e,
            )
            try:
                _db.delete_webhook_event(canal, message_id)
            except Exception:
                logger.exception("Falha ao desfazer idempotência do evento")
            return {"ok": False, "error": "processing_failed", "detail": str(e)}
        if not result.get("ok", True):
            try:
                _db.delete_webhook_event(canal, message_id)
            except Exception:
                logger.exception("Falha ao desfazer idempotência do evento")
        return result

    return _dispatch_payload(payload, original, canal)


def _dispatch_payload(
    payload: Dict[str, Any], original: Dict[str, Any], canal: str
) -> Dict[str, Any]:
    """Routes a validated, deduplicated payload: admin command, ignored
    (incomplete/test-mode), or a customer message.

    Split out of `main()` so idempotency (above) can wrap the whole
    remaining flow and roll it back on failure (critic BLOQUEADOR 2), not
    just the final `process_customer_message()` call.
    """
    phone = (
        payload.get("from_number")
        or payload.get("from")
        or payload.get("external_id")
    )
    text = (payload.get("text") or payload.get("message") or "").strip()
    push_name = payload.get("push_name")

    if not phone or not text:
        if original.get("event"):
            logger.info("Evento Evolution ignorado: %s", original.get("event"))
            return {"ok": True, "ignored": True, "event": original.get("event")}
        logger.warning("Payload incompleto: phone/text ausentes")
        return {"ok": False, "error": "invalid_payload"}

    if canal == WHATSAPP and is_admin_phone(phone):
        log_inbound(
            normalize_phone(phone),
            text,
            canal=canal,
            push_name=push_name,
            source="admin",
        )
        sim = _resolve_admin_simulate(text)
        if sim:
            sim_phone, sim_text = sim
            return run_admin_simulation(
                phone, sim_phone, sim_text, push_name=push_name, canal=canal
            )

        try:
            contact = _ensure_admin_contact(phone, push_name)
            result = handle_admin_message(
                phone=phone,
                text=text,
                db=_db,
                router=_router,
                contact_id=contact.id,
            )
            return result
        except Exception as e:
            logger.exception("Erro no comando admin: %s", e)
            return {"ok": False, "error": "admin_command_failed", "detail": str(e)}

    if canal == WHATSAPP:
        phone = normalize_phone(phone)
    if not should_respond_to_customer(phone, canal=canal):
        logger.info(
            "Modo teste: ignorando mensagem de %s (%s) fora da lista de teste",
            phone,
            canal,
        )
        return {"ok": True, "ignored": True, "reason": "test_mode"}

    return process_customer_message(phone, text, push_name=push_name, canal=canal)


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
