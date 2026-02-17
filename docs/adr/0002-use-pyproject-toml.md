# ADR-0002: Use pyproject.toml for Configuration and Dependencies

> **Status:** Accepted • **Date:** 2026-01-31

## 1. Context & Problem
We need a consistent and modern way to manage project metadata, dependencies, and development tool configurations. Historically, Python projects have used `requirements.txt` for dependencies, `setup.py` for packaging, and various individual configuration files (e.g., `.flake8`, `mypy.ini`, `pytest.ini`) for tools. This fragmentation leads to:
*   Cluttered project root directories.
*   Dispersed configuration resulting in maintenance overhead.
*   Lack of a standardized build system definition.

## 2. Decision
**We chose:** `pyproject.toml`

**Reasoning:**
*   **Standardization:** It is the official Python standard (PEP 518, PEP 621) for defining build requirements and project metadata.
*   **Centralization:** It allows us to consolidate:
    *   Project metadata (name, version, description).
    *   Dependencies (main and development/optional groups).
    *   Build system requirements (e.g., `hatchling` as used with `uv`).
    *   Tool configurations (e.g., `ruff`, `mypy`, `pytest`) in a single file.
*   **Integration:** It is natively supported by modern tooling, including our chosen package manager `uv`, which uses it as the source of truth for workspace and dependency management.

### 2.1. Workspace Root Exception
The **root** `pyproject.toml` intentionally has **no `[build-system]`** section. It serves as the `uv` workspace root (defining members, dev-dependencies, and shared tool configuration) but is not itself an installable Python package. Only the individual sub-packages (`packages/*`, `services/*`) declare `hatchling` as their build backend.

### 2.2. Dynamic Versioning
All sub-packages use **dynamic versioning** (`dynamic = ["version"]`) with `hatchling` reading the version from each package's `__init__.py` (`__version__ = "x.y.z"`). This ensures a single source of truth for each package version.

## 3. Options Considered
*   **requirements.txt**:
    *   *Rejected because*: It is limited to listing dependencies. It cannot handle project metadata or tool configuration. Using it would still require other files for those needs, preventing consolidation.
*   **setup.py / setup.cfg**:
    *   *Rejected because*: `setup.py` involves running arbitrary code for builds, which is a security risk and is considered legacy. `setup.cfg` is static but `pyproject.toml` is the intended modern replacement.
*   **Pipfile / Pipfile.lock**:
    *   *Rejected because*: These are specific to `Pipenv` and do not serve as a universal standard for other tools or build backends.

## 4. Consequences
*   **Positive:**
    *   **Single Source of Truth:** One file controls the environment, build, and code quality tools.
    *   **Cleaner Project Structure:** Fewer config files in the root directory.
    *   **Forward Compatibility:** Aligns with the direction of the Python ecosystem.
*   **Negative:**
    *   Requires a build backend (like `hatchling`) instead of simple text parsing, though tools like `uv` handle this abstractly.
