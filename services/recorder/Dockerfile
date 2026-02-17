# ==============================================================================
# Silvasonic Recorder Service
# Audio capture service with hardware access (ALSA, GPIO).
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
COPY services/recorder/ services/recorder/

# Install only this service's dependencies (not the entire workspace)
RUN uv sync --frozen --no-dev --no-editable \
    --package silvasonic-recorder

# --- Stage 2: Runtime ---
FROM docker.io/python:${PYTHON_VERSION}

LABEL org.opencontainers.image.title="silvasonic-recorder"
LABEL org.opencontainers.image.description="Audio capture service for Silvasonic bioacoustic monitoring"

# Recorder-specific system dependencies
# curl: container healthcheck
# libasound2: ALSA audio library (sound recording)
# libgpiod2: GPIO access (hardware control, microphone switching)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libasound2 \
    alsa-utils \
    libgpiod2 \
    && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from the builder stage
COPY --from=builder /build/.venv /app/.venv

# Ensure the venv Python is on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

EXPOSE 9500

# NOTE: No USER directive — container runs as root inside.
# Podman rootless maps container-root → host user automatically.
# Root inside gives automatic access to mounted devices (ALSA, GPIO).

ENTRYPOINT ["python", "-m"]
CMD ["silvasonic.recorder"]
