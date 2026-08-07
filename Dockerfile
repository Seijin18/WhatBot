FROM python:3.11-slim
WORKDIR /app

# Install system deps (minimal)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

# cloudflared (conversation-history-media-storage / túnel do painel temporário
# whatbot/static/admin_ui.html): permite o próprio serviço whatbot-ingress
# subir um quick tunnel para si mesmo (http://localhost:$IG_INGRESS_PORT) sob
# demanda, via `whatbot/tunnel_control.py` — sem depender de um processo no
# host nem de acesso ao socket do Docker.
#
# Copiado do contexto de build (`docker/vendor/cloudflared-linux-amd64`), não
# baixado aqui: `curl` para `github.com/cloudflare/cloudflared/releases` não
# é confiável em toda rede (neste host, especificamente, trava sem baixar
# nada — só os espelhos Debian do apt acima funcionam). Se o arquivo não
# existir, baixe manualmente e coloque nesse caminho antes do build:
#   mkdir -p docker/vendor && curl -fsSL -o docker/vendor/cloudflared-linux-amd64 \
#     https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
# Trocar por `cloudflared-linux-arm64` se a imagem for construída em ARM.
COPY docker/vendor/cloudflared-linux-amd64 /usr/local/bin/cloudflared
RUN chmod +x /usr/local/bin/cloudflared

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "whatbot.main"]
