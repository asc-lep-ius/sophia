# Multi-stage build with uv for fast installs
FROM python:3.12-slim AS base
ENV TERM=xterm-256color LANG=C.UTF-8 LC_ALL=C.UTF-8
RUN pip install uv

FROM base AS builder
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv sync --no-dev --frozen

FROM base AS runtime
WORKDIR /app
COPY --from=builder /app /app
ENV SOPHIA_DATA_DIR=/data
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", \
    "import sqlite3; sqlite3.connect('/data/sophia.db').execute('SELECT 1')"]
ENTRYPOINT ["/app/.venv/bin/python", "-m", "sophia"]
