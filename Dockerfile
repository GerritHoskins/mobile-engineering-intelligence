FROM python:3.13-slim

# Pinned to the uv version that produced uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so they cache independently of app code.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic/ alembic/
COPY app/ app/
COPY scripts/start.sh scripts/start.sh

EXPOSE 8000
CMD ["scripts/start.sh"]
