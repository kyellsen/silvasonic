# ==============================================================================
# Silvasonic Controller Service
# API and orchestration service.
# Self-contained multi-stage build — no shared base image required.
# ==============================================================================

ARG PYTHON_VERSION=3.11-slim-bookworm

# --- Stage 1: Builder ---
FROM docker.io/python:${PYTHON_VERSION} AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /build

# Copy dependency manifests first (cache-friendly layer ordering)
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY services/controller/ services/controller/

# Install only this service's dependencies (not the entire workspace)
RUN uv sync --frozen --no-dev \
    --package silvasonic-controller

# --- Stage 2: Runtime ---
FROM docker.io/python:${PYTHON_VERSION}

LABEL org.opencontainers.image.title="silvasonic-controller"
LABEL org.opencontainers.image.description="Control logic and API for Silvasonic bioacoustic monitoring"

# Runtime system dependencies (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder /build/.venv /app/.venv

# Ensure the venv Python is on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

EXPOSE 9100

# NOTE: No USER directive — container runs as root inside.
# Podman rootless maps container-root → host user automatically.
# Docker runs as host-root (acceptable for this edge device).

ENTRYPOINT ["python", "-m"]
CMD ["silvasonic.controller"]
