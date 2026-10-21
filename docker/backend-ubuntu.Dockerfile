# Independent experiment only; the default backend image is unchanged.
ARG UBUNTU_SUITE=noble
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS noble
ENV UV_PYTHON_PREFERENCE=only-system EXTRIO_PYTHON=/usr/bin/python3.12
FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944 AS resolute
ENV UV_PYTHON_PREFERENCE=only-managed EXTRIO_PYTHON=3.12.15
FROM ghcr.io/astral-sh/uv:0.12.23@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 AS uv
FROM ${UBUNTU_SUITE} AS runtime
ARG UBUNTU_SUITE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_HTTP_TIMEOUT=600 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/extrio \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEBIAN_FRONTEND=noninteractive
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app

RUN . /etc/os-release && test "$VERSION_CODENAME" = "$UBUNTU_SUITE" \
    && apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && mkdir -p /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && printf '%s\n' "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${UBUNTU_SUITE}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-16 \
    && if [ "$UBUNTU_SUITE" = noble ]; then apt-get install -y --no-install-recommends python3.12; fi

COPY backend/pyproject.toml backend/uv.lock backend/README.md backend/hatch_build.py backend/
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$UBUNTU_SUITE" = resolute ]; then uv python install 3.12.15; fi \
    && uv sync --project backend --python "$EXTRIO_PYTHON" --frozen --no-dev --no-install-project \
    && /opt/extrio/bin/python -m playwright install --with-deps --only-shell chromium \
    && mkdir -p /opt/python && chmod -R a+rX /ms-playwright /opt/python

COPY scripts/prune-image-runtime.py /tmp/prune-image-runtime.py
RUN EXTRIO_DISPOSABLE_IMAGE_BUILD=1 /opt/extrio/bin/python /tmp/prune-image-runtime.py only-shell \
    && rm /tmp/prune-image-runtime.py \
    && apt-get purge -y curl xvfb xserver-common \
    && rm -rf /var/lib/apt/lists/*

COPY LICENSE NOTICE ./
COPY docs/contracts docs/contracts
COPY backend/src backend/src
COPY backend/migrations backend/migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --python "$EXTRIO_PYTHON" --frozen --no-dev \
    && useradd --create-home --uid 10001 extrio \
    && mkdir -p /var/lib/extrio && chown extrio:extrio /var/lib/extrio
ENV PATH="/opt/extrio/bin:${PATH}"
USER extrio
EXPOSE 8000
CMD ["extrio-api"]

# Adds frozen Python test tools only, not replacement OS/browser dependencies.
FROM runtime AS verification
USER root
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --python "$EXTRIO_PYTHON" --frozen
USER extrio
