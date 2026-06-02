"""
Script Windmill: cole este código em um Script Python no Windmill
e habilite o webhook do script.

Requisitos no Windmill:
- Variáveis de ambiente iguais ao .env do projeto
- Dependências: psycopg, requests, google-genai
- Ou monte o repositório WhatBot como workspace/resource
"""

from typing import Any, Dict


def main(payload: Dict[str, Any]) -> Dict[str, Any]:
    from whatbot.main import main as whatbot_main

    return whatbot_main(payload)
