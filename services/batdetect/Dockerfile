# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files
COPY services/batdetect/pyproject.toml ./
COPY packages/core /packages/core

ENV VIRTUAL_ENV=/app/.venv
# 2. Create venv and install dependencies
RUN uv venv
RUN uv pip install /packages/core
RUN uv pip install -r pyproject.toml

# 3. Copy source code
COPY services/batdetect/src ./src
COPY services/batdetect/README.md ./

# 4. Install the project
RUN uv pip install .

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "silvasonic.batdetect"]
