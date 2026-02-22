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
*   **Resource Limits & QoS:** You **MUST** specify memory, CPU limits, and `oom_score_adj` for every Tier 2 container. The Recorder is the most protected service, while analysis workers are expendable. See **[ADR-0020](docs/adr/0020-resource-limits-qos.md)** for exact values and policies.
*   **Container Runtime:** Containers run as root inside (no `USER` directive). Podman rootless maps container-root to the host user automatically. See **[ADR-0004](docs/adr/0004-use-podman.md)** and **[ADR-0007](docs/adr/0007-rootless-os-compliance.md)**.
*   **Services Architecture:** The system is organized into **Tier 1 (Infrastructure)** and **Tier 2 (Application)**. All Tier 2 containers are **IMMUTABLE** and receive their configuration dynamically from the Controller via injected configuration. The Recorder has **NO database access**. See **[ADR-0013](docs/adr/0013-tier2-container-management.md)** and **[VISION.md](VISION.md)** for full architecture constraints.

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
*   **Service Documentation Constraint:**
    *   **Implemented Services** (fully or partially): Must have their authoritative `README.md` in their respective `services/<name>/` directory. The `docs/services/<name>.md` file must only be a stub linking to it.
    *   **Planned/Unimplemented Services**: Must be documented centrally in `docs/services/<name>.md`.
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


## 8. Repository Documentation Rules (Source of Truth)

### Document Roles
- `README.md` (root): describes the **current (as-is) state** and the **minimal quickstart**. Link out to deeper docs. No long-term vision or detailed service designs here.
- `VISION.md`: describes the **target (to-be) vision**: motivation, principles, high-level roadmap. No setup instructions.
- `AGENTS.md`: defines **contributor/agent behavior** and **repo conventions** (structure, editing rules, quality gates).
- `docs/adr/`: Architecture Decision Records. Each ADR must include context, decision, alternatives, consequences, and a status (`proposed` / `accepted` / `superseded`).
- `services/<svc>/README.md`: exists **only for implemented or partially implemented services** and is the single source of truth for running/config/API details of that service.
- `docs/services/<svc>.md`: exists **only for not-yet-implemented services** as a service specification (planned behavior, interfaces, dependencies).

### As-Is vs To-Be Labeling
- Every doc section must clearly indicate whether it is **AS-IS (implemented)** or **TO-BE (planned)**.
- Service docs must include a `Status:` line: `implemented` | `partial` | `planned`.

### Redundancy Rule
- Do not duplicate content across root `README.md`, `docs/`, and service READMEs.
- Root `README.md` links to service READMEs/specs instead of copying them.

### Location Rule
- Implemented/partial service details live in `services/<svc>/README.md`.
- Planned-only service descriptions live in `docs/services/<svc>.md`.

### Change Rule
- When a service moves from planned to implementation, introduce `services/<svc>/README.md` and update links. Keep any planned spec clearly marked as design, or migrate key decisions into ADRs.

---

## See Also

- **[README.md](README.md)** — Project overview, quick start, structure (human-facing)
- **[VISION.md](VISION.md)** — Long-term vision, design philosophy, services architecture, roadmap (normative for AI agents when designing new services)
- **[docs/index.md](docs/index.md)** — Full technical documentation
