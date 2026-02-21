# AGENTS.md

> **CRITICAL BUG WORKAROUND (VS Code Shell Integration):**
> You suffer from a known VS Code shell integration bug where reading stdout directly from the terminal hangs indefinitely.
>
> **RULE:** Whenever you run a terminal command, you **MUST** pipe the output to a unique named file in `/tmp` (including a datetime stamp) and then read that file to get the results.
>
> **Example:** `ls -la > /tmp/out_20241025_120000.txt` (then read `/tmp/out_20241025_120000.txt`)

> **AUTHORITY:** This document defines the **binding rules** for AI agents working on this repository. It is the single and only AGENTS.md in the project. All scope, responsibilities, and constraints must be derived from this document and the linked normative documentation (`docs/`).

👤 **Are you a Human?**
Please read **[README.md](README.md)** for project overview and quick start, and **[VISION.md](VISION.md)** for the long-term vision and roadmap.

## 1. Core Directive: Data Capture Integrity
Silvasonic is a robust, autonomous bioacoustic monitoring device (Raspberry Pi 5 + NVMe).
*   **Primary Directive:** Silvasonic is a recording station, not just an analytics cluster. **Data Capture Integrity** is paramount.
*   **CRITICAL RULE:** Any operation that risks the continuity of Sound Recording is **FORBIDDEN**.
*   **Resource Limits:** Every Tier 2 container **MUST** specify memory and CPU limits. The Recorder **MUST** set `oom_score_adj=-999`. Agents creating new `Tier2ServiceSpec` entries **MUST** include resource limits (see [ADR-0020](docs/adr/0020-resource-limits-qos.md)).
*   **Container Runtime:** Containers run as root inside (no `USER` directive). Podman rootless maps container-root to the host user automatically (see ADR-0004, ADR-0007).
*   **Services Architecture:** The system is organized into **Tier 1** (Infrastructure, managed by Podman Compose) and **Tier 2** (Application, managed by Controller). The **recorder** is the highest-priority service but lives in Tier 2 because it is managed by the Controller. **All Tier 2 containers are IMMUTABLE** — they receive configuration via Profile Injection. **Database access for the Recorder is strictly FORBIDDEN** (see [ADR-0013](docs/adr/0013-tier2-container-management.md)); other Tier 2 services (BirdNET, Uploader, etc.) may access the database. See **[VISION.md](VISION.md)** for the full services architecture.

## 2. Language & Domain Policy
*   **Repository Content:** **ENGLISH ONLY** (Code, Docs, Commits, Configs).
*   **Chat Output:** **GERMAN ONLY** (Interaction with User).
*   **Localization (i18n):** Backend delivers `JSONB` dictionaries (e.g. `{"en": "Blackbird", "de": "Amsel"}`). Frontend resolves at runtime. Hardcoding UI strings is **FORBIDDEN**.
*   **Domain Language:** Strict adherence to **Glossary** in `docs/index.md`.

## 3. Naming Conventions (Concise)
Full details in **[ADR 0010](docs/adr/0010-naming-conventions.md)**.
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
    *   **Volumes:** Use Bind Mounts with `:z` (shared) suffix. Named Volumes **ONLY** for `database`.
    *   **Temporary Artifacts:** MUST use `.tmp/` (git-ignored, auto-cleaned). Do NOT clutter root.
*   **⚠️ Root-Level Files & `.keep`:** Every new file or directory added to the **project root** **MUST** also be registered in `.keep`. `just clear` deletes everything in the root that is **not** listed there. Forgetting an entry means **irreversible data loss**.


## 5. Preferred Libraries & Packages
Agents should prioritize the following libraries for their respective domains to maintain codebase consistency:

* **Core/Config:** `pydantic` (V2), `pyYAML` (strictly `safe_load`)
* **Logging:** `structlog` (Output JSON for container aggregation) / `logging` + `rich` (for human)
* **Database:** `sqlalchemy` (2.0+ async mode), `asyncpg`
* **Redis:** `redis-py` (async mode, for heartbeat publishing — see ADR-0019)
* **API/Web:** `fastapi` (for web-interface and status-board frontends, not for backend-only services like controller)
* **Data Processing:** `numpy` (Audio matrices), `polars` (Tabular data, strictly avoid `pandas` for memory efficiency)
* **System/Audio:** `psutil`, `soundfile`
* **Testing:** `pytest`, `playwright`
* **Tooling:** `uv`, `hatchling`, `ruff`, `mypy`, `pre-commit`

## 6. Testing Rules
1. **Explicit Markers:** Every test file, class, or function MUST have an explicit pytest marker (`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`, or `@pytest.mark.smoke`).
2. **Directory Structure:** Tests must be placed in the corresponding directory (`tests/unit/`, `tests/integration/`, etc.) matching their marker.
3. **Location Strategy:** Tests specific to a service or package MUST reside within that package. Only cross-cutting tests reside in the root `tests/` directory.

## 7. Environment Variable Naming
*   **Prefix Rule:** Every project-specific environment variable **MUST** carry the `SILVASONIC_` prefix (e.g. `SILVASONIC_DB_PORT`, `SILVASONIC_CONTROLLER_PORT`).
*   **Exceptions:** Variables whose names are **dictated by a third-party image or tooling standard** keep their original name. Currently allowed exceptions:
    *   `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` — required by the TimescaleDB / PostgreSQL image.
    *   `DOCKER_HOST` — required by the Testcontainers library (connects to the Podman socket, not Docker).
*   **Rationale:** A consistent prefix prevents collisions with system or third-party variables and makes Silvasonic configuration instantly identifiable in any environment.

---

## See Also

- **[README.md](README.md)** — Project overview, quick start, structure (human-facing)
- **[VISION.md](VISION.md)** — Long-term vision, design philosophy, services architecture, roadmap (normative for AI agents when designing new services)
- **[docs/index.md](docs/index.md)** — Full technical documentation
