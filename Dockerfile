# syntax=docker/dockerfile:1.7
#
# Production image for the VIRA server.
# Ollama is intentionally a separate service (see compose.yaml).
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS wheels

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libcups2-dev \
        libdbus-1-dev \
        libx11-dev \
        libxext-dev \
        libxrandr-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /wheels
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRA_HOST=0.0.0.0 \
    VIRA_PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        tini \
        libcups2 \
        libdbus-1-3 \
        libx11-6 \
        libxext6 \
        libxrandr2 \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

ARG VIRA_UID=1000
ARG VIRA_GID=1000

RUN groupadd --gid "${VIRA_GID}" vira \
    && useradd --uid "${VIRA_UID}" --gid vira --create-home \
       --home-dir /home/vira --shell /usr/sbin/nologin vira

WORKDIR /app

COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

COPY --chown=vira:vira . .
RUN mkdir -p /app/data && chown -R vira:vira /app/data

USER vira

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/livez >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "run.py"]
