"""Configuration and system prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Dict
import os
import socket
from urllib.parse import urlparse

SYSTEM_PROMPTS: Dict[str, str] = {
    "novo_lead": (
        "VENDAS: Você atende pelo WhatsApp do negócio (dados na base abaixo). "
        "Seu objetivo é entender o que o cliente precisa e apresentar os produtos/serviços, "
        "preços e formas de compra ou agendamento. "
        "Use SOMENTE a base de conhecimento incluída abaixo — nunca invente preços, prazos "
        "ou itens que não estejam cadastrados. "
        "Responda em tom conversacional e acolhedor, como um atendente humano no WhatsApp. "
        "Encaminhe para atendimento humano SOMENTE se o cliente pedir ou se a informação "
        "não existir na base (use [HUMAN_HANDOVER])."
    ),
    "cliente_ativo": (
        "ATENDIMENTO: Você ajuda clientes já cadastrados com pedidos, pagamentos e dúvidas. "
        "Use apenas a base de conhecimento abaixo. Resposta conversacional em português. "
        "Use [HUMAN_HANDOVER] apenas se o cliente pedir humano ou faltar informação essencial."
    ),
    "cancelado": (
        "REATIVACAO: Você foca em reativação e retenção de clientes inativos. "
        "Use a base de conhecimento abaixo. Proponha caminhos com base nos dados reais. "
        "Use [HUMAN_HANDOVER] apenas se necessário."
    ),
}

GEMINI_USE_TOOLS = os.getenv("GEMINI_USE_TOOLS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def gemini_use_tools() -> bool:
    return GEMINI_USE_TOOLS

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MODEL_FALLBACKS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_MODEL_FALLBACKS", "gemini-2.0-flash,gemini-2.0-flash-lite"
    ).split(",")
    if m.strip()
]
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.1"))

ENV_LLM_PROVIDER = "LLM_PROVIDER"
ENV_OLLAMA_BASE_URL = "OLLAMA_BASE_URL"
ENV_OLLAMA_MODEL = "OLLAMA_MODEL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

ENV_ADMIN_NOTIFY_PHONES = "ADMIN_NOTIFY_PHONES"
ENV_TEST_MODE = "TEST_MODE"
ENV_TEST_PHONES = "TEST_PHONES"
ENV_TEST_IGSIDS = "TEST_IGSIDS"

# Test-mode allowlist env var per channel (see design.md, Decisão 6). A
# channel missing from this map has no allowlist at all, which makes
# `should_respond_to_customer` fail-closed for it.
_TEST_LIST_ENV_BY_CHANNEL = {
    "whatsapp": ENV_TEST_PHONES,
    "instagram": ENV_TEST_IGSIDS,
}
NOTIFY_QUEUE_BATCH = int(os.getenv("NOTIFY_QUEUE_BATCH", "5"))
NOTIFY_LONG_WAIT_MINUTES = int(os.getenv("NOTIFY_LONG_WAIT_MINUTES", "15"))
NOTIFY_IMMEDIATE_ON_HANDOVER = os.getenv(
    "NOTIFY_IMMEDIATE_ON_HANDOVER", "true"
).lower() in {"1", "true", "yes", "on"}
NOTIFY_ON_ASSUMIR = os.getenv("NOTIFY_ON_ASSUMIR", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DAILY_SUMMARY_HOUR = int(os.getenv("DAILY_SUMMARY_HOUR", "20"))
ENV_TIMEZONE = "WHATBOT_TIMEZONE"


def get_timezone() -> str:
    return os.getenv(ENV_TIMEZONE, "America/Sao_Paulo")


AUTO_REACTIVATE_HOURS = int(os.getenv("AUTO_REACTIVATE_HOURS", "24"))

# campaign-csv-broadcast: três camadas independentes de limite de taxa
# (design.md, Decisão 2) — tamanho do lote por execução do worker, pausa
# entre envios dentro do lote, e o intervalo do cron do Windmill (configurado
# fora do código, na UI, ver windmill/f/whatbot/send_campaign_queue.py e
# tasks.md 3.8). Lidos por `whatbot/main.py::send_campaign_queue` via estes
# nomes (não via `os.getenv` direto), para que os testes possam sobrescrever
# por caso com `patch.object(main_mod, "CAMPAIGN_BATCH_SIZE", N)`.
CAMPAIGN_BATCH_SIZE = int(os.getenv("CAMPAIGN_BATCH_SIZE", "20"))
CAMPAIGN_MAX_RETRIES = int(os.getenv("CAMPAIGN_MAX_RETRIES", "3"))
CAMPAIGN_SEND_INTERVAL_SECONDS = int(os.getenv("CAMPAIGN_SEND_INTERVAL_SECONDS", "3"))
DEFAULT_TEST_PHONE = os.getenv("DEFAULT_TEST_PHONE", "5511999999999")
FALLBACK_SIMULATE_PHONE = "5511999999999"
ENV_BUSINESS_PHONE = "BUSINESS_PHONE"


def get_business_phone() -> str | None:
    raw = os.getenv(ENV_BUSINESS_PHONE, "").strip()
    if not raw:
        return None
    import re

    digits = re.sub(r"\D", "", raw.split("@")[0])
    return digits or None


def resolve_simulate_phone(sim_phone: str | None = None) -> str:
    """Phone used as fake customer in admin simulations (never the business's own line)."""
    import re

    raw = (sim_phone or DEFAULT_TEST_PHONE or FALLBACK_SIMULATE_PHONE).strip()
    digits = re.sub(r"\D", "", raw.split("@")[0])
    business_phone = get_business_phone()
    if business_phone and digits == business_phone:
        digits = re.sub(r"\D", "", FALLBACK_SIMULATE_PHONE)
    return digits or FALLBACK_SIMULATE_PHONE


def _parse_phone_list(raw: str) -> list[str]:
    """Normalize comma-separated phone numbers (DDI+DDD+número)."""
    if not raw.strip():
        return []
    import re

    phones: list[str] = []
    for part in raw.split(","):
        digits = re.sub(r"\D", "", part.strip().split("@")[0])
        if digits:
            phones.append(digits)
    return phones


def is_test_mode() -> bool:
    return os.getenv(ENV_TEST_MODE, "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _normalize_canal(canal: str | None) -> str:
    """Normalize a channel name, delegating to `whatbot.channels.base`.

    Imported lazily (inside the function, not at module load time):
    `whatbot.channels/__init__.py` imports `whatbot.channels.whatsapp_evolution`,
    which does `from ..config import EVOLUTION_API_BASE_URL` — a top-level
    import here would run while `whatbot.config` is still being loaded,
    creating a circular import. By the time this function is actually
    called, `whatbot.config` has finished loading, so the cycle never
    triggers.
    """
    from .channels.base import normalize_channel

    return normalize_channel(canal)


def get_test_identities(canal: str | None = None) -> list[str]:
    """Test-mode allowlist for a channel (`TEST_PHONES` for WhatsApp,
    `TEST_IGSIDS` for Instagram). A channel without a configured env var
    returns an empty list, which is what makes `should_respond_to_customer`
    fail-closed for it."""
    canal = _normalize_canal(canal)
    env_var = _TEST_LIST_ENV_BY_CHANNEL.get(canal)
    if not env_var:
        return []
    raw = os.getenv(env_var, "")
    if canal == "whatsapp":
        return _parse_phone_list(raw)
    return [v.strip() for v in raw.split(",") if v.strip()]


def get_test_phones() -> list[str]:
    """Phones allowed to receive bot replies when TEST_MODE is enabled (WhatsApp)."""
    return get_test_identities("whatsapp")


def is_test_identity(external_id: str, canal: str | None = None) -> bool:
    canal = _normalize_canal(canal)
    if canal == "whatsapp":
        import re

        normalized = re.sub(r"\D", "", external_id.split("@", 1)[0])
    else:
        normalized = external_id
    return normalized in get_test_identities(canal)


def is_test_phone(phone: str) -> bool:
    return is_test_identity(phone, "whatsapp")


def should_respond_to_customer(external_id: str, canal: str | None = None) -> bool:
    """Whether an inbound customer message should be processed."""
    if not is_test_mode():
        return True
    return is_test_identity(external_id, canal)


def get_admin_phones() -> list[str]:
    """Normalized admin phone numbers (comma-separated in ADMIN_NOTIFY_PHONES)."""
    return _parse_phone_list(os.getenv(ENV_ADMIN_NOTIFY_PHONES, ""))


EVOLUTION_API_BASE_URL = os.getenv("EVOLUTION_API_BASE_URL", "http://localhost:8080")


def _compose_service_fallback() -> str:
    """Reach published compose ports from the host when service DNS is unavailable."""
    return "localhost"


def _replace_unresolvable_host(value: str, host: str, fallback: str | None = None) -> str:
    fb = fallback or _compose_service_fallback()
    try:
        socket.gethostbyname(host)
    except OSError:
        return value.replace(f"@{host}:", f"@{fb}:").replace(
            f"://{host}:", f"://{fb}:"
        ).replace(f"://{host}/", f"://{fb}/")
    return value


_ipv4_dns_forced = False


def force_ipv4_dns() -> None:
    """Make every stdlib-backed HTTP client in this process resolve IPv4 only.

    whatsapp-send-resilience: containers on this host resolve AAAA (IPv6)
    records for external hosts (`generativelanguage.googleapis.com`,
    `graph.facebook.com`) but have no IPv6 route — `socket.create_connection`
    is supposed to fall through to the next resolved address on failure, but
    in practice both `requests` (Evolution/Instagram/WhatsApp Cloud clients)
    and `httpx`/`httpcore` (Gemini) have been observed raising
    `Network is unreachable` instead of falling back to the working IPv4
    address, confirmed by a direct socket test against both families.
    `evolution-api` (Node) already works around the equivalent problem via
    `NODE_OPTIONS=--dns-result-order=ipv4first`; there is no such env var for
    Python. Patching `socket.getaddrinfo` — the one function every one of
    those HTTP stacks ultimately calls to resolve a hostname — fixes it at
    the lowest common layer instead of separately for each library.

    Idempotent: safe to call more than once per process (`bootstrap_env()`
    may run several times), only ever patches the *original* function once.
    """
    global _ipv4_dns_forced
    if _ipv4_dns_forced:
        return
    original_getaddrinfo = socket.getaddrinfo

    def _ipv4_only_getaddrinfo(*args, **kwargs):
        results = original_getaddrinfo(*args, **kwargs)
        ipv4_results = [r for r in results if r[0] == socket.AF_INET]
        # Fall back to the unfiltered list rather than returning an empty
        # one — an IPv6-only host (none in this project's infra today, but
        # not impossible) must still be able to connect, degraded rather
        # than broken.
        return ipv4_results or results

    socket.getaddrinfo = _ipv4_only_getaddrinfo
    _ipv4_dns_forced = True


def bootstrap_env() -> None:
    """Load .env and make Docker service hostnames reachable from Windmill jobs."""
    force_ipv4_dns()
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    for path in (Path("/whatbot/.env"), Path(".env")):
        if path.exists():
            load_dotenv(path, override=False)
            break

    dsn = resolve_db_dsn(os.getenv(ENV_DB_DSN))
    if dsn:
        os.environ[ENV_DB_DSN] = dsn

    evolution_url = resolve_evolution_base_url(os.getenv("EVOLUTION_API_BASE_URL"))
    if evolution_url:
        os.environ["EVOLUTION_API_BASE_URL"] = evolution_url


def resolve_db_dsn(dsn: str | None = None) -> str:
    """Use host.docker.internal when compose service names are unavailable."""
    raw = (dsn or os.getenv(ENV_DB_DSN) or "").strip()
    if not raw:
        return raw
    for host in ("db", "evolution-db"):
        raw = _replace_unresolvable_host(raw, host)
    return raw


def resolve_evolution_base_url(url: str | None = None) -> str:
    """Return Evolution API URL reachable from host, Windmill jobs, or compose."""
    raw = (url or os.getenv("EVOLUTION_API_BASE_URL") or "http://localhost:8080").rstrip(
        "/"
    )
    host = urlparse(raw).hostname or ""
    if host in {"evolution-api", "db"}:
        try:
            socket.gethostbyname(host)
        except OSError:
            return raw.replace(host, _compose_service_fallback())
    return raw


def resolve_ollama_base_url(url: str | None = None) -> str:
    return (url or os.getenv(ENV_OLLAMA_BASE_URL) or DEFAULT_OLLAMA_BASE_URL).rstrip(
        "/"
    )


# Environment variable names
ENV_DB_DSN = "DB_DSN"
ENV_EVOLUTION_API_KEY = "EVOLUTION_API_KEY"
ENV_EVOLUTION_API_INSTANCE_NAME = "EVOLUTION_API_INSTANCE_NAME"
ENV_GEMINI_API_KEY = "GEMINI_API_KEY"

# instagram-ingestion-service: naming follows the Meta webhook convention
# (`hub.verify_token` handshake, `X-Hub-Signature-256` app-secret HMAC) —
# there is no equivalent WhatsApp/Evolution convention to mirror, since
# Evolution API does not implement Meta's webhook verification protocol.
ENV_IG_WEBHOOK_VERIFY_TOKEN = "IG_WEBHOOK_VERIFY_TOKEN"
ENV_IG_APP_SECRET = "IG_APP_SECRET"
ENV_IG_APP_ID = "IG_APP_ID"
ENV_IG_CLIENT_SECRET = "IG_CLIENT_SECRET"
ENV_IG_INGRESS_PORT = "IG_INGRESS_PORT"
# Alinhado com `.env.example` e `docker-compose.yml` (serviço `whatbot-ingress`,
# perfil "instagram") — os três devem concordar, ver critic MENOR 5.
DEFAULT_IG_INGRESS_PORT = 8090

# Alertas de saúde da integração (Requirement "Alertas de saúde da
# integração"): os dois limiares e seus defaults são definidos aqui — o
# change `instagram-operability` só documenta runbook/mensagens finais.
ENV_IG_ALERT_FAIL_STREAK = "IG_ALERT_FAIL_STREAK"
ENV_IG_ALERT_SILENCE_MINUTES = "IG_ALERT_SILENCE_MINUTES"
DEFAULT_IG_ALERT_FAIL_STREAK = 5
DEFAULT_IG_ALERT_SILENCE_MINUTES = 120

# whatsapp-cloud-channel-client: selects which client is registered under
# canal "whatsapp" in `whatbot/main.py::_init_infra()` — see
# `openspec/changes/whatsapp-cloud-channel-client/design.md`, "Decisão:
# WHATSAPP_PROVIDER com default evolution até validação". Default stays
# `evolution` (today's behavior, unchanged) until an operator explicitly
# opts into the Cloud API after completing Meta's onboarding.
ENV_WHATSAPP_PROVIDER = "WHATSAPP_PROVIDER"
WHATSAPP_PROVIDER_EVOLUTION = "evolution"
WHATSAPP_PROVIDER_CLOUD = "cloud"
DEFAULT_WHATSAPP_PROVIDER = WHATSAPP_PROVIDER_EVOLUTION

# Meta webhook verification for the WhatsApp Cloud API — same protocol as
# ENV_IG_WEBHOOK_VERIFY_TOKEN/ENV_IG_APP_SECRET (hub.challenge handshake,
# X-Hub-Signature-256 HMAC), separate env vars because WhatsApp is
# registered as its own product/webhook subscription in Meta Business
# Manager, independent of the Instagram one.
ENV_WA_CLOUD_WEBHOOK_VERIFY_TOKEN = "WA_CLOUD_WEBHOOK_VERIFY_TOKEN"
ENV_WA_CLOUD_APP_SECRET = "WA_CLOUD_APP_SECRET"


def resolve_whatsapp_provider(value: str | None = None) -> str:
    """Normalize `WHATSAPP_PROVIDER`, falling back to the safe default.

    An unset, empty, or unrecognized value resolves to `"evolution"` — the
    default is never `"cloud"` by accident, matching the design decision
    that switching providers is an explicit operator action, not something
    a missing/malformed env var can trigger.
    """
    raw = (value if value is not None else os.getenv(ENV_WHATSAPP_PROVIDER, "")).strip().lower()
    if raw not in (WHATSAPP_PROVIDER_EVOLUTION, WHATSAPP_PROVIDER_CLOUD):
        return DEFAULT_WHATSAPP_PROVIDER
    return raw

# A credencial é considerada "perto de expirar" (Requirement "Renovação
# automática de credencial") dentro desta janela.
IG_CREDENTIAL_EXPIRY_WARNING_DAYS = 7

# Vida útil padrão de um long-lived token do Instagram quando a resposta da
# renovação não traz `expires_in` (critic MENOR 6): usado só para não gerar
# alerta falso logo após uma renovação que não teve erro — a Meta documenta
# 60 dias para o long-lived token do Instagram API with Instagram Login.
DEFAULT_IG_TOKEN_LIFETIME_DAYS = 60


def ig_alert_fail_streak() -> int:
    try:
        return max(1, int(os.getenv(ENV_IG_ALERT_FAIL_STREAK, str(DEFAULT_IG_ALERT_FAIL_STREAK))))
    except ValueError:
        return DEFAULT_IG_ALERT_FAIL_STREAK


def ig_alert_silence_minutes() -> int:
    try:
        return max(
            1, int(os.getenv(ENV_IG_ALERT_SILENCE_MINUTES, str(DEFAULT_IG_ALERT_SILENCE_MINUTES)))
        )
    except ValueError:
        return DEFAULT_IG_ALERT_SILENCE_MINUTES


PLACEHOLDER_VALUES = {
    "",
    "your_evolution_api_key",
    "your_instance_name",
    "your_gemini_api_key",
}


def is_placeholder(value: str | None) -> bool:
    return value is None or value.strip() in PLACEHOLDER_VALUES
