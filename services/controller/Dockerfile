# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PYTHONUNBUFFERED=1

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
COPY packages/core/alembic.ini ./
COPY packages/core/migrations ./migrations

# 4. Install the project
RUN uv pip install .

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

# Install System Dependencies (ALSA, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    alsa-utils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/log/silvasonic && chown -R 1000:1000 /var/log/silvasonic

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/migrations /app/migrations
COPY services/recorder/config/profiles /app/profiles

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "silvasonic.controller.main"]
