# AgentZline — production image (Python 3.12 slim + uv)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /code

# uv binary (official installer layer)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Deps first (better layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Run as non-root in production
RUN useradd -m appuser && chown -R appuser:appuser /code
USER appuser

EXPOSE 8000

# Migrate, then serve. Single replica only (APScheduler in-process).
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
