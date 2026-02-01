# Docker Standards & Best Practices

All services in the Silvasonic project must adhere to the following strict guidelines when defining `Dockerfile`s. These rules ensure build efficiency, security, and reproducibility across the fleet.

## 1. Dependency Management with `uv`

*   **Mandatory Usage:** All Python-based services must use `uv` for dependency management.
*   **Lockfiles:** You **MUST** use `uv.lock` files.
    *   `uv sync --frozen` must be used in the build process to ensure that the installed dependencies exactly match the tested versions.
    *   Never run `uv pip install` without a lockfile in production/release builds.

## 2. Multi-Stage Builds

*   **Efficiency:** Production images must use multi-stage builds to keep the final image size small.
*   **Structure:**
    *   **Builder Stage:** Install system build dependencies (e.g., `build-essential`), compile code, and install Python packages into a virtual environment.
    *   **Runtime Stage:** Start from a slim base image (e.g., `python:3.11-slim`), copy *only* the virtual environment and application code from the builder stage.
    *   **Benefit:** This prevents build tools and cache artifacts from bloating the production image.

## 3. Layer Caching Optimization

*   **Order Matters:** Docker layers are cached. Changes in a layer invalidate the cache for all subsequent layers.
*   **Rule:** **Install dependencies BEFORE copying the full source code.**
    *   **Step 1:** Copy only the dependency definition files (`pyproject.toml`, `uv.lock`).
    *   **Step 2:** Run `uv sync` (or install command) to create the environment.
    *   **Step 3:** COPY the rest of the source code (`src/`).
*   **Reasoning:** Source code changes frequently; dependencies change rarely. This ensures that `uv sync` is cached and doesn't run on every code change, significantly speeding up builds.

### Example `Dockerfile` Pattern

```dockerfile
# STAGE 1: Builder
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 1. Copy dependency files ONLY
COPY pyproject.toml uv.lock ./

# 2. Install dependencies (cached if lockfile doesn't change)
#    --no-dev: Exclude development dependencies
#    --no-install-project: Don't install the project itself yet, just dependencies
RUN uv sync --frozen --no-dev --no-install-project

# 3. Copy source code
COPY src ./src
COPY README.md ./

# 4. Install the project itself
RUN uv sync --frozen --no-dev

# STAGE 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy the environment from builder
COPY --from=builder /app/.venv /app/.venv

# Update PATH
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
ENTRYPOINT ["python", "-m", "silvasonic.myservice"]
```
