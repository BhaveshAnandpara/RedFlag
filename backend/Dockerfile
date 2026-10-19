FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Dependencies first so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY bots ./bots
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# Apply migrations, then serve. Hosts set PORT; default to 8000 locally.
CMD ["sh", "-c", "alembic upgrade head && uvicorn redflag_backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
