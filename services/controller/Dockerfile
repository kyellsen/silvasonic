# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files
COPY services/controller/pyproject.toml ./
COPY packages/core /packages/core

ENV VIRTUAL_ENV=/app/.venv
# 2. Create venv and install dependencies
RUN uv venv
RUN uv pip install /packages/core
# Removed invalid install command


# 3. Copy source code
COPY services/controller/src ./src
COPY services/controller/README.md ./
# Note: packages/core source is already installed via pip install /packages/core? 
# In recorder Dockerfile it does: COPY packages/core/src ./packages/core/src
# But uv pip install /packages/core should install it into site-packages.
# Let's match the recorder pattern exactly to be safe.
COPY packages/core/src ./packages/core/src

# 4. Install the project
RUN uv pip install .

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

# Install System Dependencies (ALSA, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "silvasonic.controller.main"]
