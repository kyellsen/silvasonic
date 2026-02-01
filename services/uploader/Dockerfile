# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files ONLY
COPY pyproject.toml uv.lock ./

# 2. Install dependencies (cached if lockfile doesn't change)
RUN uv sync --frozen --no-dev --no-install-project

# 3. Copy source code
COPY src ./src
COPY README.md ./

# 4. Install the project itself
RUN uv sync --frozen --no-dev

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies (rclone is required for uploader)
RUN apt-get update && apt-get install -y rclone && rm -rf /var/lib/apt/lists/*

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "silvasonic.uploader"]
