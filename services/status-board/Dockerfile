# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency definition
COPY services/status-board/pyproject.toml ./
# Create empty lock file if it doesn't exist to satisfy copy (adding it to copy list implies it exists)
# We'll just skip lock for now if it's not strictly managed yet, or copy if exists.
# Better: Just copy pyproject. 

# 2. Copy the core library
COPY packages/core /packages/core

# 3. Create venv and install dependencies
# We install silvasonic-core first, then the rest. 
# We remove 'silvasonic-core' from pyproject.toml requirement if it conflicts, 
# but technically pip handles path installs fine if we point to it.
# However, to be safe, we explicitly install the local package.
RUN uv venv
RUN uv pip install /packages/core
RUN uv pip install -r pyproject.toml

# 4. Copy source code and install project
COPY services/status-board/src ./src
COPY services/status-board/README.md ./
RUN uv pip install .

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy source code (optional if installed as package, but good for keeping context)
COPY --from=builder /app/src /app/src

# Default command
CMD ["uvicorn", "silvasonic.status_board.main:app", "--host", "0.0.0.0", "--port", "8000"]
