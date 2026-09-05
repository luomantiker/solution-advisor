FROM python:3.11-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-droid-fallback \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY frontend/src/assets/realthon-logo-mark.png /app/assets/realthon-logo-mark.png
ENV UV_INDEX_URL=https://pypi.org/simple
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "solution_advisor.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
