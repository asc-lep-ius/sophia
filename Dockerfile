# Multi-stage build with uv for fast installs
FROM python:3.12-slim AS base
ENV TERM=xterm-256color LANG=C.UTF-8 LC_ALL=C.UTF-8
RUN pip install uv

FROM base AS builder
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# The lecture index's read side (#129): chromadb and sentence-transformers,
# with PyTorch's CPU build in place of the CUDA one the lock pins. The API
# embeds one short query at a time and has no GPU, and the CUDA wheels are
# most of the worker's 13 GB (docs/lecture-index-access.md). The skipped
# packages and the torch version are read from the lock, so an upgrade there
# cannot leave this list behind. Dependencies come before the source, so a
# change to src/ does not fetch PyTorch again.
RUN uv export --frozen --no-dev --extra index --no-emit-project --no-hashes > /tmp/index.txt \
    && sed -n 's/^\(torch\|triton\|cuda-[a-z-]*\|nvidia-[a-z0-9-]*\)==.*/--no-install-package \1/p' \
        /tmp/index.txt > /tmp/cuda-packages \
    && uv sync --no-dev --frozen --no-install-project --extra index $(cat /tmp/cuda-packages) \
    && uv pip install --python /app/.venv/bin/python --no-deps \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==$(sed -n 's/^torch==\([^ ;]*\).*/\1/p' /tmp/index.txt)+cpu"
COPY src/ src/
# --inexact, or the sync would remove the CPU torch it was told not to install.
RUN uv sync --no-dev --frozen --inexact --extra index $(cat /tmp/cuda-packages)

FROM base AS runtime
WORKDIR /app
COPY --from=builder /app /app
# The embedding model is cached on the data volume, beside the worker's, so a
# new container does not download its 2 GB again.
ENV SOPHIA_DATA_DIR=/data \
    HF_HOME=/data/cache/huggingface
RUN useradd --create-home --uid 1000 sophia
RUN mkdir -p /data && chown sophia:sophia /data
EXPOSE 8000
USER sophia
ENTRYPOINT ["/app/.venv/bin/python", "-m", "sophia"]
