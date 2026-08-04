#requirements:
#psycopg[binary]
#psycopg_pool
#requests
#google-genai
#python-dotenv

from typing import Any, Dict


def main() -> Dict[str, Any]:
    """Job agendado: sincroniza produtos_catalogo a partir do catálogo do WhatsApp Business."""
    import sys

    if "/whatbot" not in sys.path:
        sys.path.insert(0, "/whatbot")

    from whatbot.config import bootstrap_env
    from whatbot.main import sync_catalog

    bootstrap_env()
    return sync_catalog()
