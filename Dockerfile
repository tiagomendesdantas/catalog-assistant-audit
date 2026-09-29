FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY web ./web
COPY data/catalog ./data/catalog
RUN uv sync --frozen --no-dev

RUN useradd --create-home app && chown -R app /app
USER app

# Railway injects PORT. Forwarded headers let the rate limiter see the visitor's address.
CMD ["sh", "-c", ".venv/bin/uvicorn catalog_audit.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
