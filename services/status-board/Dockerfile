# STAGE 1: Builder
FROM python:3.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files ONLY
COPY pyproject.toml uv.lock ./

# Copied from web_interface structure implies we might need the workspace packages available
# For now, we assume packages/core needs to be installable.
# In a monorepo, usually we copy the packages we depend on.
# The web_interface Dockerfile assumed `uv sync` works. 
# If web_interface relies on a workspace uv.lock at root, we need to replicate that context or copy packages.
# Let's check if web_interface has its own uv.lock. (It was in the file list earlier).
# We also need to copy silvasonic-core to be able to install it if it's a path dependency in a workspace.
# However, in the pyproject.toml I defined "silvasonic-core" as a dependency.
# If it's a monorepo workspace, uv handles it. If not, I might need to copy it.
# Given the user context: `packages/core` exists.
# I will assume for now I need to copy `packages/core` to install it if it's local.
# BUT, looking at `web_interface/Dockerfile`, it didn't copy `packages/core`.
# This suggests either `web_interface` doesn't depend on `core` (unlikely for a real app, but possible for empty shell)
# OR the build context for `web_interface` includes the root.
# Wait, `web_interface/Dockerfile` says `COPY pyproject.toml uv.lock ./`.
# If `silvasonic-core` is in `pyproject.toml`, `uv sync` will try to find it.
# If it's a registry package, fine. If it's local, we need it.
# `web_interface` pyproject.toml had `dependencies = []`. It had NO dependencies.
# This explains why it didn't need to copy core.
# My `status-board` NEEDS core. So I must allow access to it.
# To keep it simple and strictly "dev mode prod-like", I will try to COPY packages/core into the build env
# OR Use a workspace-like approach.
# For this specific step, I'll stick to a self-contained Dockerfile but add the necessary copy for core if needed.
# Actually, the most robust way in a simple dockerfile context for a sub-project depending on a sibling
# is often to mount it or copy it.
# Let's look at the web_interface Dockerfile again... it was very simple.
# I will assume standard pip/uv installable behavior.
# I will ADD `COPY packages /packages` to the builder stage to be safe, assuming build context is project root.
# BUT `docker-compose` usually sets context.
# `podman-compose.yml` for database set context: `services/database`.
# So the context is LOCAL to the service.
# This means I cannot copy `../../packages/core` easily without changing context to root.
# I will change the build context in `podman-compose.yml` to root for this service, OR use a relative path if supported.
# Standard practice: Set context to root, dockerfile to `services/status-board/Dockerfile`.
# I will write the Dockerfile assuming context is the SERVICE directory for now, but I might need to adjust.
# Wait, if I change context to root, `COPY pyproject.toml` becomes `COPY services/status-board/pyproject.toml`.
# Let's stick to the prompt: "The Status Board must use the exact same technology stack".
# "Exact same" implies keeping it simple.
# If I set `silvasonic-core` as a dependency, how does it resolve?
# If I don't publish `silvasonic-core`, I can't install it without the code.
# I will configure the `podman-compose` to mount the core library in DEV mode, which is the primary mode here.
# So for the Dockerfile build, I might just omit `silvasonic-core` from *build* time if I can, or `COPY` it if I change context.
# Let's look at `podman-compose.yml` again.
# `gateway` context: `services/gateway`.
# `database` context: `services/database`.
# None use root context.
# Configuring `status-board` to use root context is the safest way to include `packages/core`.
# So:
# 1. Dockerfile expects `packages/core` at `/packages/core` (relative to build root).
# 2. compose file sets `context: .` and `dockerfile: services/status-board/Dockerfile`.

# Dockerfile Content:
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files
COPY services/status-board/pyproject.toml services/status-board/uv.lock* ./
# Note: uv.lock might not exist yet.

# 2. Copy core package for installation
COPY packages/core /packages/core

# 3. Install dependencies
# We need to tell UV where to find silvasonic-core.
# We can use a workspace `uv.lock` or add it as an editable/path dependency in pyproject.toml?
# In `pyproject.toml`, I put "silvasonic-core".
# If I change it to `silvasonic-core @ file:///packages/core`, it works.
# For now, I'll rely on the `uv sync` to handle it if I set up the environment right.
# OR simpler: just install it directly.
RUN uv venv && uv pip install -r pyproject.toml -e /packages/core

# 3. Copy source code
COPY services/status-board/src ./src
COPY services/status-board/README.md ./

# 4. Install the project itself
RUN uv pip install -e .

# STAGE 2: Runtime
FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

# Copy source (if not installed in venv as package, but it is)
# We still copy src for runtime binding if needed, but usually venv is enough if installed.
# But for dev mode with bind mounts, this is overshadowed.
COPY --from=builder /app/src /app/src

CMD ["uvicorn", "silvasonic.status_board.main:app", "--host", "0.0.0.0", "--port", "8000"]
