FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="Veskald Execution Bridge"
LABEL org.opencontainers.image.description="Automated trading bot for Binance, Bybit, Kraken, OKX, Coinbase — connects to a central WebSocket hub and executes trading commands."
LABEL org.opencontainers.image.source="https://gitlab.com/veskald/veskald-execution-bridge"
LABEL org.opencontainers.image.url="https://gitlab.com/veskald/veskald-execution-bridge"
LABEL org.opencontainers.image.vendor="Veskald"
LABEL org.opencontainers.image.licenses="AGPL-3.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        tzdata \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash --uid 1000 trader
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps "coinbase-advanced-py>=1.8.2"

COPY . /app
RUN mkdir -p /app/logs && chown -R trader:trader /app

USER trader

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

# Container is healthy if the bot wrote to its log file within the last 5 minutes.
# Empty log == bot not started yet; stale log == socket loop wedged.
HEALTHCHECK --interval=60s --timeout=10s --start-period=45s --retries=3 \
    CMD test -f /app/logs/veskald_bridge.log && \
        test "$(find /app/logs/veskald_bridge.log -mmin -5)" || exit 1

CMD ["python", "run.py"]