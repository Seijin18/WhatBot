"""Configuration and system prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Dict
import os
import socket
from urllib.parse import urlparse

SYSTEM_PROMPTS: Dict[str, str] = {
    "novo_lead": (
        "VENDAS: Você atende pelo WhatsApp da associação (dados na base abaixo). "
        "Seu objetivo é qualificar leads, apresentar modalidades, horários e matrícula. "
        "Use SOMENTE a base de conhecimento incluída abaixo — nunca invente preços, horários "
        "ou modalidades. "
        "Responda em tom conversacional e acolhedor, como um atendente humano no WhatsApp. "
        "Encaminhe à secretaria SOMENTE se o cliente pedir humano ou se a informação "
        "não existir na base (use [HUMAN_HANDOVER])."
    ),
    "matriculado": (
        "SECRETARIA: Você ajuda associados matriculados com aulas, pagamentos e matrícula. "
        "Use apenas a base de conhecimento abaixo. Resposta conversacional em português. "
        "Use [HUMAN_HANDOVER] apenas se o cliente pedir humano ou faltar informação essencial."
    ),
    "cancelado": (
        "REATIVACAO: Você foca em reativação e retenção de associados. "
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
DEFAULT_TEST_PHONE = os.getenv("DEFAULT_TEST_PHONE", "5511999999999")
FALLBACK_SIMULATE_PHONE = "5511999999999"
ENV_ASSOCIATION_PHONE = "ASSOCIATION_PHONE"


def get_association_phone() -> str | None:
    raw = os.getenv(ENV_ASSOCIATION_PHONE, "").strip()
    if not raw:
        return None
    import re

    digits = re.sub(r"\D", "", raw.split("@")[0])
    return digits or None


def resolve_simulate_phone(sim_phone: str | None = None) -> str:
    """Phone used as fake customer in admin simulations (never the association line)."""
    import re

    raw = (sim_phone or DEFAULT_TEST_PHONE or FALLBACK_SIMULATE_PHONE).strip()
    digits = re.sub(r"\D", "", raw.split("@")[0])
    assoc = get_association_phone()
    if assoc and digits == assoc:
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


def get_test_phones() -> list[str]:
    """Phones allowed to receive bot replies when TEST_MODE is enabled."""
    return _parse_phone_list(os.getenv(ENV_TEST_PHONES, ""))


def is_test_phone(phone: str) -> bool:
    import re

    normalized = re.sub(r"\D", "", phone.split("@", 1)[0])
    return normalized in get_test_phones()


def should_respond_to_customer(phone: str) -> bool:
    """Whether an inbound customer message should be processed."""
    if not is_test_mode():
        return True
    return is_test_phone(phone)


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


def bootstrap_env() -> None:
    """Load .env and make Docker service hostnames reachable from Windmill jobs."""
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


PLACEHOLDER_VALUES = {
    "",
    "your_evolution_api_key",
    "your_instance_name",
    "your_gemini_api_key",
}


def is_placeholder(value: str | None) -> bool:
    return value is None or value.strip() in PLACEHOLDER_VALUES
