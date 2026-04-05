# silvasonic-db-viewer

> **Status:** Implemented (since v0.7.1) · **Tier:** 1 · **Instances:** Single · **Port:** 8002
>
> 📋 **User Stories:** `n/a` (Developer Tool)

**AS-IS:** Developer UI for inspecting database tables and performing multi-format data exports (CSV, JSON, Parquet).
**Target:** Stable background utility; UI layout and export functions completed.

---

## 1. The Problem / The Gap

*   Developers need a way to quickly verify database state (e.g. injected events, processed audio metadata) without dropping into `psql` or setting up complex desktop DB tools.
*   Data scientists/analysts need to extract processed data chunks easily.

## 2. User Benefit

*   Visual, responsive verification of system data in real-time.
*   One-click download of table data into standard formats (CSV, JSON, Parquet) for external analysis tools.

## 3. Core Responsibilities

### Inputs
*   User interaction via browser.
*   Direct reads from the TimescaleDB.

### Processing
*   FastAPI backend rendering dynamic HTML chunks via Jinja2 & HTMX.
*   Conversion of table rows into structured data files using `polars`.

### Outputs
*   Responsive HTML payload & Tailwind CSS styling.
*   Data files (CSV, JSON, Parquet) served over HTTP.

## 4. Operational Constraints & Rules

| Aspect           | Value / Rule                                                   |
| ---------------- | -------------------------------------------------------------- |
| **Immutable**    | Yes                                                            |
| **DB Access**    | Read-Only                                                      |
| **Concurrency**  | Uvicorn Asyncio Event Loop                                     |
| **State**        | Stateless                                                      |
| **Privileges**   | Rootless                                                       |
| **Resources**    | Low                                                            |
| **QoS Priority** | `oom_score_adj=0`                                              |

## 5. Configuration & Environment

| Variable / Mount           | Description                                    | Default / Example  |
| -------------------------- | ---------------------------------------------- | ------------------ |
| `POSTGRES_HOST`            | Database hostname                              | `database`         |
| `POSTGRES_USER`            | Database user                                  | `silvasonic`       |
| `POSTGRES_PASSWORD`        | Database password                              | `silvasonic`       |
| `POSTGRES_DB`              | Target database name                           | `silvasonic`       |
| `SILVASONIC_API_ROOT_PATH` | Path prefix for reverse proxy routing (FastAPI)| `/db-viewer`       |

*(Controlled via `COMPOSE_PROFILES=db-viewer` in `.env`)*

## 6. Technology Stack

*   **Backend:** `fastapi`, `sqlalchemy` (async), `polars`
*   **Frontend:** `tailwindcss` v4, `daisyui` v5, `htmx`, `alpine.js`

## 7. Out of Scope

*   Write operations / Database mutation (Read-Only enforcement).
*   Production End-User Access (this is an internal development and administrative tool).

## 8. Implementation Details (Domain Specific)

*   Utilizes a push-style collapsible sidebar to maximize horizontal screen real-estate for large data tables.
*   Uses `polars` for memory-efficient and rapid generation of Parquet and CSV files for export.

## 9. References

*   [VISION.md](../../VISION.md) - Project Architecture
