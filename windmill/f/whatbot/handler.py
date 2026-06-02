#requirements:
#psycopg[binary]
#psycopg_pool
#requests
#google-genai
#python-dotenv

from typing import Any, Dict


def main(
    event: str | None = None,
    instance: str | None = None,
    data: dict | None = None,
    body: dict | None = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Webhook Windmill: recebe payload da Evolution API e executa o WhatBot."""
    import sys

    if "/whatbot" not in sys.path:
        sys.path.insert(0, "/whatbot")

    from whatbot.config import bootstrap_env
    from whatbot.main import main as whatbot_main

    bootstrap_env()

    if body:
        payload = body
    elif event or data is not None or instance:
        payload = {"event": event, "instance": instance, "data": data, **kwargs}
    elif kwargs:
        payload = kwargs
    else:
        try:
            import wmill  # type: ignore[import-untyped]

            payload = wmill.get_payload() or {}
        except Exception:
            payload = {}

    return whatbot_main(payload)
