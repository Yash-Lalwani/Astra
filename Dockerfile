FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The prompts live inside src/astra/agents/prompts; sql/ holds the schema applied at startup.
COPY src ./src
COPY sql ./sql
RUN uv sync --frozen --no-dev

RUN useradd --create-home astra && chown -R astra /app
USER astra
ENV PATH="/app/.venv/bin:$PATH"

# Railway sets PORT. exec makes uvicorn the main process, so it receives the stop signal.
CMD ["sh", "-c", "exec uvicorn astra.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
