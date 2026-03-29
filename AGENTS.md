# AGENTS.md

> **CRITICAL BUG WORKAROUND (VS Code Shell Integration):**
> You suffer from a known VS Code shell integration bug where reading stdout directly from the terminal hangs indefinitely.
>
> **RULE:** Whenever you run a terminal command, you **MUST** pipe the output to a unique named file in `/tmp` (including a datetime stamp) and then read that file to get the results.
>
> **Example:** `ls -la > /tmp/out_20241025_120000.txt` (then read `/tmp/out_20241025_120000.txt`)

> **AUTHORITY:** This document is the **single source of truth** for all AI agents working on this repository. `CLAUDE.md`, `.gemini/`, `.cursorrules` etc. are supplementary redirects that point here — never the reverse.

👤 **Human?** Read **[README.md](README.md)** for overview, **[VISION.md](VISION.md)** for vision/architecture, and **[ROADMAP.md](ROADMAP.md)** for the milestone roadmap.

## 1. Core Directive: Data Capture Integrity
Silvasonic is a robust, autonomous bioacoustic monitoring device (Raspberry Pi 5 + NVMe).
*   **Primary Directive:** Silvasonic is a recording station, not just an analytics cluster. **Data Capture Integrity** is paramount.
*   **CRITICAL RULE:** Any operation that risks the continuity of Sound Recording is **FORBIDDEN**.
*   **Resource Limits & QoS:** You **MUST** specify memory, CPU limits, and `oom_score_adj` for every Tier 2 container. The Recorder is the most protected service, while analysis workers are expendable. See **[ADR-0020](docs/adr/0020-resource-limits-qos.md)**.
*   **Container Runtime:** Containers run as root inside (no `USER` directive). Podman rootless maps container-root to the host user automatically. See **[ADR-0004](docs/adr/0004-use-podman.md)** and **[ADR-0007](docs/adr/0007-rootless-os-compliance.md)**.
*   **Services Architecture:** **Tier 1 (Infrastructure)** and **Tier 2 (Application)**. All Tier 2 containers are **IMMUTABLE**, configured dynamically by the Controller. The Recorder has **NO database access**. See **[ADR-0013](docs/adr/0013-tier2-container-management.md)** and **[VISION.md](VISION.md)**.

## 2. Language & Domain Policy
*   **Repository Content:** **ENGLISH ONLY** (Code, Docs, Commits, Configs).
*   **Chat Output:** **GERMAN ONLY** (Interaction with User).
*   **Localization (i18n):** Backend delivers `JSONB` dictionaries (e.g. `{"en": "Blackbird", "de": "Amsel"}`). Frontend resolves at runtime. Hardcoding UI strings is **FORBIDDEN**.
*   **Domain Language:** Strict adherence to **[Glossary](docs/glossary.md)**.

## 3. Naming Conventions
Full details: **[ADR-0010](docs/adr/0010-naming-conventions.md)**.
*   **PyPI Package:** `silvasonic-<service>` · **Python Import:** `silvasonic.<service>`
*   **Compose Service:** `<service>` · **Container Name:** `silvasonic-<service>`

## 4. Documentation & Filesystem

| Document                   | Role                              | Location          |
| -------------------------- | --------------------------------- | ----------------- |
| `README.md`                | AS-IS state + quickstart          | Root              |
| `VISION.md`                | TO-BE vision + architecture       | Root              |
| `ROADMAP.md`               | Milestone roadmap                 | Root              |
| `AGENTS.md`                | Agent rules (this file, SoT)      | Root              |
| `services/<svc>/README.md` | Implemented/partial service (SoT) | `services/<svc>/` |
| `docs/services/<svc>.md`   | Planned service spec              | `docs/services/`  |
| `docs/adr/`                | Architecture Decision Records     | `docs/adr/`       |
| `docs/arch/`               | Architecture Patterns & Specs     | `docs/arch/`      |
| `docs/index.md`            | Entry point for all docs          | `docs/`           |

**Rules:**
- Every doc must label sections **AS-IS** or **TO-BE**. Service docs need a `Status:` line (`implemented` | `partial` | `planned`).
- No content duplication — link instead of copying.
- When a service moves to implementation: create `services/<svc>/README.md`, convert `docs/services/<svc>.md` to link-stub.
- Bind Mounts with `:z`. Named Volumes **ONLY** for `database`.
- Temporary artifacts → `.tmp/` (git-ignored).
- ⚠️ New root files/dirs → register in `.keep` or `just clear` deletes them.

## 5. Libraries

| Domain   | Use                                                                       |
| -------- | ------------------------------------------------------------------------- |
| Config   | `pydantic` V2, `pyYAML` (`safe_load` only)                                |
| Logging  | `structlog` (JSON) / `rich` (dev)                                         |
| DB       | `sqlalchemy` 2.0+ async, `asyncpg`                                        |
| Redis    | `redis-py` async (ADR-0019)                                               |
| System   | `psutil` (process + host resource monitoring, ADR-0019)                   |
| Web      | `fastapi`, `jinja2`, `htmx`, `alpine.js` (ADR-0003)                       |
| Frontend | `tailwindcss`, `daisyui` (v5), `echarts`, `wavesurfer.js` (v7) (ADR-0021) |
| Data     | `numpy`, `polars` (**no** `pandas`)                                       |
| Audio    | `ffmpeg` (capture & resample — ADR-0024), `soundfile` (analysis services only)    |
| Test     | `pytest`, `pytest-xdist`, `playwright`, `testcontainers`, `polyfactory`    |
| Tools    | `uv`, `hatchling`, `ruff`, `mypy`, `pre-commit`                           |

## 6. Testing Rules
1. **Explicit Markers:** Every test MUST have `@pytest.mark.unit`, `.integration`, `.system`, `.system_hw`, `.e2e`, or `.smoke`.
2. **Directory Structure:** Tests in `tests/unit/`, `tests/integration/`, etc. matching their marker.
3. **Location:** Service-specific tests inside the service package. Only cross-cutting tests in root `tests/`.
4. **Hardware Tests:** `@pytest.mark.system_hw` tests require real USB microphone hardware and are **never** run in CI or `just check-all`. Run manually via `just test-hw`.

## 7. Environment Variable Naming
*   **Prefix Rule:** Every project variable **MUST** use `SILVASONIC_` prefix (e.g. `SILVASONIC_DB_PORT`).
*   **Exceptions:** Third-party standards keep their names: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DOCKER_HOST`.

---

## See Also

- **[README.md](README.md)** — Project overview, quick start
- **[VISION.md](VISION.md)** — Vision, architecture, design principles
- **[ROADMAP.md](ROADMAP.md)** — Milestone roadmap
- **[docs/index.md](docs/index.md)** — Full technical documentation
