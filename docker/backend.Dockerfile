FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=120 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/extrio \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/README.md backend/
COPY LICENSE NOTICE ./
COPY docs/contracts docs/contracts
COPY backend/src backend/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --frozen --no-dev \
    && mkdir -p /ms-playwright \
    && /opt/extrio/bin/python -m playwright install --with-deps chromium \
    && CRAWL4AI_MODE=api /opt/extrio/bin/crawl4ai-setup \
    && chmod -R a+rX /ms-playwright

RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/extrio/bin:${PATH}"

RUN useradd --create-home --uid 10001 extrio \
    && mkdir -p /var/lib/extrio \
    && chown -R extrio:extrio /var/lib/extrio

USER extrio
EXPOSE 8000

CMD ["extrio-api"]
