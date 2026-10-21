# Experimental only. The normal backend Dockerfile and default image are unchanged.
FROM extrio/backend:slim-original AS runtime
USER root
ARG PRUNE_VARIANT=llvm
COPY scripts/prune-image-runtime.py /tmp/prune-image-runtime.py
RUN /opt/extrio/bin/python /tmp/prune-image-runtime.py "$PRUNE_VARIANT" \
    && rm /tmp/prune-image-runtime.py
USER extrio

# Only frozen Python test tools are added; no OS packages or browsers are installed.
FROM runtime AS verification
USER root
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --frozen
USER extrio
