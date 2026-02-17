# AGENTS.md

> **AUTHORITY:** This document defines the **binding rules** for AI agents working on this repository. It is the single and only AGENTS.md in the project. All scope, responsibilities, and constraints must be derived from this document and the linked normative documentation (`docs/`).

👤 **Are you a Human?**
Please read **[README.md](README.md)** for project context, installation guides, and high-level architecture.

## 1. Core Directive: Data Capture Integrity
Silvasonic is a robust, autonomous bioacoustic monitoring device (Raspberry Pi 5 + NVMe).
*   **Primary Directive:** Silvasonic is a recording station, not just an analytics cluster. **Data Capture Integrity** is paramount.
*   **CRITICAL RULE:** Any operation that risks the continuity of Sound Recording is **FORBIDDEN**.
*   **Rootless Mandate:** The system **ALWAYS** runs as a non-root user (User: `pi`). See **[ADR 0007](requirements/adr/0007-rootless-os-compliance.md)**.

## 2. Language & Domain Policy
*   **Repository Content:** **ENGLISH ONLY** (Code, Docs, Commits, Configs).
*   **Chat Output:** **GERMAN ONLY** (Interaction with User).
*   **Localization (i18n):** Backend delivers `JSONB` dictionaries (e.g. `{"en": "Blackbird", "de": "Amsel"}`). Frontend resolves at runtime. Hardcoding UI strings is **FORBIDDEN**.
*   **Domain Language:** Strict adherence to **Glossary** in `docs/index.md`.

## 3. Naming Conventions (Concise)
Full details in **[ADR 0010](requirements/adr/0010-naming-conventions.md)**.
*   **PyPI Package:** `silvasonic-<service>` (e.g. `silvasonic-recorder`)
*   **Python Import:** `silvasonic.<service>` (Namespace package)
*   **Podman Service:** `<service>` (short name in compose file)
*   **Container Name:** `silvasonic-<service>` (explicit name for host visibility)

## 4. Project Structure & Filesystem
*   **Documentation Structure:**
    *   **`docs/`**: **Single Source of Truth** (Architecture, ADRs, Specs, Requirements). Agents **MUST** search here recursively.
    *   **Index:** Start at **[docs/index.md](docs/index.md)**.
*   **Filesystem Constraints (`/mnt/data`):**
    *   **Persistence:** Strict governance rules apply (see `docs/index.md`).
    *   **Volumes:** Use Bind Mounts with `:z` (shared) suffix. Named Volumes **ONLY** for `database` and `redis`.
    *   **Temporary Artifacts:** MUST use `.tmp/` (git-ignored, auto-cleaned). Do NOT clutter root.

## 5. Technical Constraints

> **CRITICAL BUG WORKAROUND (VS Code Shell Integration):**
> You suffer from a known VS Code shell integration bug where reading stdout directly from the terminal hangs indefinitely.
>
> **RULE:** Whenever you run a terminal command, you **MUST** pipe the output to a unique named file in `/tmp` (including a datetime stamp) and then read that file to get the results.
>
> **Example:** `ls -la > /tmp/out_20241025_120000.txt` (then read `/tmp/out_20241025_120000.txt`)

## 6. Preferred Libraries & Packages
Agents should prioritize the following libraries for their respective domains to maintain codebase consistency:

* **Core/Config:** `pydantic` (V2), `pyYAML` (strictly `safe_load`)
* **Logging:** `structlog` (Output JSON for container aggregation) / `logging` + `rich` (for human)
* **Database:** `sqlalchemy` (2.0+ async mode), `asyncpg`
* **API/Web:** `fastapi`
* **Data Processing:** `numpy` (Audio matrices), `polars` (Tabular data, strictly avoid `pandas` for memory efficiency)
* **System/Audio:** `psutil`, `soundfile`
* **Testing:** `pytest`, `playwright`
* **Tooling:** `uv`, `hatchling`, `ruff`, `mypy`, `pre-commit`

## 7. Testing Rules
1. **Explicit Markers:** Every test file, class, or function MUST have an explicit pytest marker (`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`, or `@pytest.mark.smoke`).
2. **Directory Structure:** Tests must be placed in the corresponding directory (`tests/unit/`, `tests/integration/`, etc.) matching their marker.
3. **Location Strategy:** Tests specific to a service or package MUST reside within that package. Only cross-cutting tests reside in the root `tests/` directory.
