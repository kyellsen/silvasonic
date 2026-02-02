# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files
COPY services/recorder/pyproject.toml ./
COPY packages/core /packages/core

ENV VIRTUAL_ENV=/app/.venv
# 2. Create venv and install dependencies
RUN uv venv
RUN uv pip install /packages/core
RUN uv pip install -r pyproject.toml

# 3. Copy source code
COPY services/recorder/src ./src
COPY services/recorder/README.md ./
COPY packages/core/src ./packages/core/src

# 4. Install the project
RUN uv pip install .

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

# Install System Dependencies (FFmpeg + ALSA)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/log/silvasonic && chown -R 1000:1000 /var/log/silvasonic

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

COPY services/recorder/src/silvasonic/recorder/healthcheck.py /app/healthcheck.py
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD ["python", "-m", "silvasonic.recorder.main"]
