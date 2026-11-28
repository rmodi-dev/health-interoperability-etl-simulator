# syntax=docker/dockerfile:1
# Stage 1: resolve deps + install the project non-editable into .venv
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.10 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Stage 2: runtime carries only the venv (project installed inside it)
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
# Interim CMD (flagged stub): proves the image imports the package.
# Replaced by uvicorn + /healthz HEALTHCHECK in Stage 7 when the API exists.
CMD ["python", "-c", "import health_interop; print('image OK', health_interop.__version__)"]
