# AGENTS.md

> **AUTHORITY:** This file defines the **binding rules** for AI agents working on this repository. It is the single and only AGENTS.md in the project. All scope, responsibilities, and constraints must be derived from this document and the linked normative documentation (`docs/`).

👤 **Are you a Human?**
Please read **[README.md](README.md)** for project context, installation guides, and high-level architecture.

## 1. Language & Domain Policy
* **Repository Content** (Code, Docs, Comments, Commits, Configs): **ENGLISH ONLY**.
* **Chat Output / Explanations** (Interaction with User): **GERMAN ONLY**.
* **Localization Strategy (i18n):**
    * The Backend **MUST** deliver localized content (e.g. species names) as `JSONB` dictionaries: `{"en": "Blackbird", "de": "Amsel"}`.
    * The Frontend resolves these at runtime based on user preference. Hardcoding single-language strings for UI-facing content is **FORBIDDEN**.
* **Domain Language:** See the **Glossary** in `docs/index.md`. Agents must strictly adhere to these definitions.

## 2. Naming Conventions (Concise)
Full details in **[ADR 0010](docs/adr/0010-naming-conventions.md)**.
*   **PyPI Package:** `silvasonic-<service>` (e.g. `silvasonic-recorder`)
*   **Python Import:** `silvasonic.<service>` (Namespace package)
*   **Podman Service:** `<service>` (short name in compose file)
*   **Container Name:** `silvasonic-<service>` (explicit name for host visibility)

## 3. Core Directive: Data Capture Integrity
Silvasonic is a robust, autonomous bioacoustic monitoring device (Raspberry Pi 5 + NVMe) designed for continuous, multi-year deployment.
* **Primary Directive:** Silvasonic is a recording station, not just an analytics cluster. **Data Capture Integrity** is paramount.
* **CRITICAL RULE:** Any operation that risks the continuity of Sound Recording is **FORBIDDEN**.
* **Rootless Mandate:** The system **ALWAYS** runs as a non-root user (User: `pi`). See **[ADR 0007](docs/adr/0007-rootless-os-compliance.md)**.


## 4. Filesystem Constraints
* **Persistence:** The system uses a strict directory structure on the NVMe drive (`/mnt/data`).
    *   **Normative Rules:** See **[docs/index.md](docs/index.md)** -> "Filesystem Governance" for strict ownership, SELinux, and folder structure rules.
    *   **SELinux:** Bind mounts in `podman-compose.yml` **MUST** use the `:Z` suffix (e.g., `./config:/etc/config:Z`) to allow container access.
* **Temporary Artifacts:** Any temporary scripts, investigative logs, test artifacts, or debugging outputs **MUST** be placed in `.tmp/`.
    * The `.tmp/` directory is git-ignored and automatically cleaned by `make clean`.
    * Do NOT clutter root or source directories.
* **Documentation:**
    * **Index:** Start at **[docs/index.md](docs/index.md)** for a structured overview of the system.
    * **Search Policy:** Agents **MUST** search recursively in the `docs/` directory to find relevant specifications before asking questions.
    * System-wide documentation resides in `docs/`.
    * Service-specific documentation resides in `services/<service_name>/README.md`.

## 5. Technical Stack (Mandatory)
* **Python:** `>= 3.11, < 3.12`
* **Dependency Manager:** `uv` (Required).
* **Build System:** `hatchling`.
* **Containerization:** Follow **[Docker Standards](docs/development/docker_standards.md)** (Multi-stage, `uv.lock`, optimized caching).
* **Environment:** Native DevContainer (Cross-compile for Prod).
* **Linter/Formatter:** `ruff` (Google Style docstrings), `beautysh`, `djlint`, `yamlfix`.
* **Type Checker:** `mypy` (Strict mode).
* **Models:** `Pydantic v2`.
* **Database Interaction:** Use **SQLAlchemy** (Core or ORM) instead of raw SQL strings whenever best practice allows. Raw SQL is reserved for complex TimescaleDB-specific optimizations.
* **Frontend Stack:**
    * **Core:** FastAPI + Jinja2 (SSR) + HTMX + Alpine.js.
    * **Styling:** Tailwind CSS + DaisyUI (Theme: Dark/Scientific).
    * **Visualization:** Wavesurfer.js (Audio/Spectrograms), Plotly.js (Stats).
    * **Layout Concept:** IDE-inspired "Workspace" layout. Dashboard as "Bento-Box" grid. Mobile & Desktop optimized.

## 6. Preferred Libraries & Packages
Agents should prioritize the following libraries for their respective domains to maintain codebase consistency:

* **Core/Config:** `pydantic`, `pyYAML`
* **Logging:** `structlog`
* **Database:** `sqlalchemy`, `asyncpg`, `alembic`
* **API/Web:** `fastapi`
* **Data Processing:** `numpy`, `pandas`, `polars`
* **System/Audio:** `psutil`, `soundfile`
* **Testing:** `pytest`, `playwright`
* **Tooling:** `pre-commit`, `ruff`, `mypy`

## 7. Workflow & Scripts
Agents must use the provided `make` commands to ensure environmental consistency. Do not run the underlying shell scripts directly unless debugging the scripts themselves.

* **Initialization:** `make setup` (calls `scripts/init.sh`)
* **Development:** `make run` (calls `scripts/run.sh`)
* **Refactoring:** `make fix` (calls `scripts/fix.sh`)
* **Validation:** `make check` (calls `scripts/check.sh`)
* **Cleanup:** `make clean` (calls `scripts/clean.sh`)

## 8. Architecture Constraints & Data Governance
Agents must strictly adhere to the following data ownership rules to prevent race conditions:

* **Database Ownership:**
    * `recordings` table: Only writable by **processor** (Insert/Delete).
    * `uploaded` column: Only updatable by **uploader**.
    * `analysis_state` column: Updatable by **analysis workers** (e.g., birdnet).
* **State Management:**
    * **MUST** use Redis for live status/heartbeats.
    * **BAN:** Do NOT use local JSON/SQLite files for state.
* **File Handling:**
    * **Recorder:** Creates dual streams (Raw & Processed).
    * **Janitor:** Only the `processor` service is allowed to delete files from NVMe.
    * **Monitor:** Read-only surveillance and notification service.
    * **Status Board:** STRICTLY READ-ONLY. No actuation, configuration changes, or state mutation allowed. purely for visualization.

## 9. Definition of Done (Quality Gates)
Code is not "done" until it passes:
1.  `make fix` (Apply auto-formatting)
2.  `make check` (Must pass without error). This implies:
    * `uv run ruff check`
    * `uv run mypy .`
    * `uv run pytest`