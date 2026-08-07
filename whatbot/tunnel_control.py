"""Manages a cloudflared quick tunnel exposing `whatbot-ingress` publicly.

Ferramenta temporária a serviço do visualizador de conversas
(`whatbot/static/admin_ui.html`, botão "iniciar túnel") — a WhatsApp Cloud
API só entrega webhooks numa URL pública, e o quick tunnel gratuito do
Cloudflare (`trycloudflare.com`) troca de URL a cada reinício (ver
`docs/INSTAGRAM_INTEGRATION_PLAN.md`, linha 77). Não é uma capability de
produto — não tem change OpenSpec — é a mesma categoria de utilitário
operacional que já existe em `scripts/`.

Duas formas independentes de rodar um túnel coexistem, compartilhando só o
arquivo `.tunnel-url` (raiz do repositório) como fonte única de verdade de
"qual é a URL pública atual":

- `start-tunnel.sh` / `stop-tunnel.sh` (scripts de shell, mesmo padrão de
  `start-whatbot.sh`) — uso manual, fora do Docker.
- Este módulo, chamado pelas rotas `/admin/tunnel/*`
  (`whatbot/ingress.py`) — sobe o `cloudflared` **dentro do mesmo
  container** do FastAPI (a imagem já inclui o binário, ver `Dockerfile`),
  apontando para `http://localhost:{port}` (ele mesmo). Preferido a dar ao
  container acesso ao host (exigiria montar o socket do Docker, uma
  permissão bem maior do que o necessário) ou a um segundo serviço de
  controle rodando à parte no host (mais uma peça móvel para uma
  ferramenta temporária).

Status é sempre uma checagem de alcançabilidade **ao vivo** (`GET
{url}/health`), nunca uma checagem de PID — os dois mecanismos acima
rodam em namespaces de PID diferentes (host vs. container), então um PID
gravado por um não significa nada para o outro; alcançabilidade também é
um sinal estritamente melhor de qualquer forma (prova que o caminho
público inteiro funciona, não só que algum processo existe).
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict

import requests

logger = logging.getLogger("whatbot.tunnel_control")

_REPO_ROOT = Path(__file__).resolve().parent.parent
URL_FILE = _REPO_ROOT / ".tunnel-url"
_LOG_FILE = _REPO_ROOT / "tunnel-ui.log"

_QUICK_TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

_lock = threading.Lock()
_process: subprocess.Popen | None = None


def _read_url() -> str | None:
    try:
        url = URL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return url or None


def _write_url(url: str) -> None:
    URL_FILE.write_text(url + "\n", encoding="utf-8")


def check_reachable(url: str, timeout: float = 8.0, attempts: int = 2) -> bool:
    """`True` se `{url}/health` responder OK — prova ponta a ponta que o
    túnel está de pé, não só que um processo local existe.

    Duas tentativas por padrão: a borda do quick tunnel gratuito às vezes
    tem uma primeira resposta lenta/instável (visto na prática: o
    indicador da UI piscando "inativo" com o túnel de pé) — uma falha
    isolada não deve virar "inativo" na tela.
    """
    for attempt in range(attempts):
        try:
            response = requests.get(f"{url}/health", timeout=timeout)
            if response.ok:
                return True
        except requests.RequestException:
            pass
        if attempt < attempts - 1:
            time.sleep(0.5)
    return False


def get_status() -> Dict[str, Any]:
    """Última URL conhecida + se ela responde agora."""
    url = _read_url()
    reachable = check_reachable(url) if url else False
    return {"url": url, "reachable": reachable}


def _scan_log_for_url(timeout_seconds: float = 15.0) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            text = _LOG_FILE.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        match = _QUICK_TUNNEL_URL_RE.search(text)
        if match:
            return match.group(0)
        time.sleep(0.5)
    return None


def start_tunnel(port: int) -> Dict[str, Any]:
    """Inicia (ou reaproveita) um cloudflared quick tunnel para
    `http://localhost:{port}`.

    Idempotente: se a última URL conhecida já responde, ou um subprocesso
    iniciado por este mesmo processo Python ainda está de pé, não faz
    nada e só devolve o status atual — evita empilhar túneis duplicados
    se o botão for clicado mais de uma vez.
    """
    global _process

    with _lock:
        current = get_status()
        if current["reachable"]:
            return {**current, "started": False, "detail": "já estava ativo"}
        if _process is not None and _process.poll() is None:
            return {
                **current,
                "started": False,
                "detail": "processo já em andamento, aguardando URL aparecer",
            }

        logger.info("Iniciando cloudflared quick tunnel para localhost:%s", port)
        try:
            log_handle = open(_LOG_FILE, "w", encoding="utf-8")
        except OSError as e:
            return {
                "url": None,
                "reachable": False,
                "started": False,
                "detail": f"falha abrindo log do túnel: {e}",
            }
        try:
            _process = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        except FileNotFoundError:
            log_handle.close()
            logger.error("cloudflared não encontrado — imagem precisa de rebuild")
            return {
                "url": None,
                "reachable": False,
                "started": False,
                "detail": "cloudflared não encontrado nesta imagem — rode "
                "'docker compose build whatbot-ingress' após atualizar o Dockerfile",
            }

    url = _scan_log_for_url()
    if url is None:
        return {
            "url": None,
            "reachable": False,
            "started": True,
            "detail": "túnel iniciado, mas a URL ainda não apareceu nos primeiros "
            "15s — confira o status de novo em alguns segundos",
        }
    _write_url(url)
    return {
        "url": url,
        "reachable": check_reachable(url),
        "started": True,
        "detail": None,
    }
