#requirements:
#psycopg[binary]
#psycopg_pool
#requests
#google-genai
#python-dotenv

from typing import Any, Dict


def main() -> Dict[str, Any]:
    """Job agendado: envia mensagens pendentes de disparo_mensagens em lotes,
    respeitando o limite de taxa configurado (campaign-csv-broadcast).

    Configure o cron deste job manualmente na UI do Windmill (não é
    provisionado automaticamente) — sugestão inicial: a cada 2 minutos. Ver
    openspec/changes/campaign-csv-broadcast/tasks.md, seção 3.
    """
    import sys

    if "/whatbot" not in sys.path:
        sys.path.insert(0, "/whatbot")

    from whatbot.config import bootstrap_env
    from whatbot.main import send_campaign_queue

    bootstrap_env()
    return send_campaign_queue()
