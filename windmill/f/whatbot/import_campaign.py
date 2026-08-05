#requirements:
#psycopg[binary]
#psycopg_pool
#requests
#google-genai
#python-dotenv

from typing import Any, Dict


def main(csv_content: str, lote: str) -> Dict[str, Any]:
    """Disparo manual do admin pela UI do Windmill: importa um CSV de
    campanha (campaign-csv-broadcast). Não é um endpoint HTTP novo — mesmo
    modelo operacional de refresh_ig_token.py, rodado sob demanda."""
    import sys

    if "/whatbot" not in sys.path:
        sys.path.insert(0, "/whatbot")

    from whatbot.config import bootstrap_env
    from whatbot.main import import_campaign

    bootstrap_env()
    return import_campaign(csv_content, lote)
