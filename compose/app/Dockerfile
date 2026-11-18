# App image for the MCP servers (S5; S6, S7 and the agent reuse it). Build context
# is the repo root (.dockerignore keeps .env, .run, logs and .venv out).
# SKIP_NLP=1 leaves out spaCy, Presidio and the 560 MB English model: the MCP
# servers never mask (the agent masks tool results on its side, D5).
ARG PY_IMAGE=python:3.12.13-slim-bookworm
FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM ${PY_IMAGE}
ARG SKIP_NLP=1
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN skip=""; if [ "$SKIP_NLP" = 1 ]; then \
      skip="--no-install-package en-core-web-lg --no-install-package spacy --no-install-package presidio-analyzer"; fi; \
    uv sync --frozen --no-dev --no-install-project $skip
COPY src ./src
RUN skip=""; if [ "$SKIP_NLP" = 1 ]; then \
      skip="--no-install-package en-core-web-lg --no-install-package spacy --no-install-package presidio-analyzer"; fi; \
    uv sync --frozen --no-dev $skip
RUN useradd --system --uid 10001 --no-create-home app && mkdir -p /logs && chown app /logs
USER app
