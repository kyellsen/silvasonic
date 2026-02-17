# ADR-0001: Use uv as Python Package and Project Manager

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
In a complex Python project setup, especially one moving towards a workspace/monorepo structure (like Silvasonic), managing dependencies, virtual environments, and Python versions can become slow and cumbersome with traditional tools. We need a tool that provides deterministic builds, fast resolution times, and robust workspace support.

## 2. Decision
**We chose:** [uv](https://github.com/astral-sh/uv)

**Reasoning:**
*   **Performance:** `uv` is written in Rust and is significantly faster than `pip` and other Python-based package managers for resolution and installation.
*   **Unified Tooling:** It acts as a single replacement for `pip`, `pip-tools`, `virtualenv`, and even `pyenv` (managing Python versions).
*   **Workspaces:** It offers native support for Python workspaces, allowing multiple packages to be developed together with shared dependencies, which fits our microservice/monorepo architecture.
*   **Standards:** It uses standard `pyproject.toml` for configuration.

### 2.1. Strict Locking Policy
To ensure reproducibility, the following rules apply to all services:
1.  **Lockfiles are Mandatory:** All services **MUST** commit their `uv.lock` file to the repository.
2.  **Container Builds:** All Docker/Podman container builds **MUST** use the `uv.lock` file.
3.  **Frozen Installation:** CI/CD pipelines and container build steps **MUST** use `uv sync --frozen` (or `uv install --frozen` where appropriate) to ensure the installed dependencies exactly match the lockfile. *Do not update dependencies during build time.*

## 3. Options Considered
*   **Standard pip + venv**:
    *   *Rejected because*: Slower dependency resolution. No built-in lock file mechanism (requires `pip-tools` or manual `pip freeze`). Managing multiple packages in a workspace is manual and error-prone.
*   **Poetry**:
    *   *Rejected because*: While robust, its dependency resolver can be slow. It has a non-standard configuration format in some areas compared to the emerging standards `uv` adopts. `uv` is seen as a more performant successor for many use cases.

## 4. Consequences
*   **Positive:**
    *   Drastically reduced CI/CD build times due to faster installation and caching.
    *   Simplified developer workflow (one tool for everything).
    *   Strict locking via `uv.lock` ensures reproducible builds across environments.
*   **Negative:**
    *   `uv` is a relatively new tool, so edge cases might be less documented than `pip`.
    *   Requires a binary installation (though easily managed via `curl` or standalone installers).
