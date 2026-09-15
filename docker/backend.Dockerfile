FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=120 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/extrio \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/README.md backend/hatch_build.py backend/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --frozen --no-dev --no-install-project \
    && mkdir -p /ms-playwright \
    && /opt/extrio/bin/python -m playwright install --with-deps chromium \
    && CRAWL4AI_MODE=api /opt/extrio/bin/crawl4ai-setup \
    && chmod -R a+rX /ms-playwright

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && mkdir -p /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && printf '%s\n' 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

COPY LICENSE NOTICE ./
COPY docs/contracts docs/contracts
COPY backend/src backend/src
COPY backend/migrations backend/migrations

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --frozen --no-dev

ENV PATH="/opt/extrio/bin:${PATH}"

RUN useradd --create-home --uid 10001 extrio \
    && mkdir -p /var/lib/extrio \
    && chown -R extrio:extrio /var/lib/extrio

USER extrio
EXPOSE 8000

CMD ["extrio-api"]
