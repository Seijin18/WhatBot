#requirements:
#psycopg[binary]
#psycopg_pool
#requests
#google-genai
#python-dotenv

from typing import Any, Dict


def main() -> Dict[str, Any]:
    """Job agendado: alerta admin sobre contatos esperando há muito tempo."""
    import sys

    if "/whatbot" not in sys.path:
        sys.path.insert(0, "/whatbot")

    from whatbot.config import bootstrap_env
    from whatbot.main import check_queue

    bootstrap_env()
    return check_queue()
