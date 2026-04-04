# Milestone v0.7.1 — DB-Viewer (Interim Dev UI)

> **Target:** v0.7.1 — DB-Viewer
>
> **Status:** 🔨 In Progress 
>
> **References:** [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md)
>
> **User Stories:** `n/a`

---

## Exemption Notice

> [!WARNING]
> **Test Coverage Exemption:** As a pure developer tool, the DB-Viewer is explicitly exempted from the mandatory "Changed-Path Test Audit" and "Smoke Tests" defined in `release_checklist.md`. 

---

## Phase 1: Service Skeleton

**Goal:** Copy and adapt the web-mock skeleton for the new lightweight service.

### Tasks

- [ ] Clone `web-mock` to `db-viewer`
- [ ] Rename packages in `pyproject.toml`
- [ ] Implement `Containerfile` and expose Port 8002
- [ ] Add `silvasonic-db-viewer` to `compose.yaml` (Tier 1)

---

## Phase 2: Implementation

**Goal:** Serve dynamic database table HTML snippets for HTMX polling.

### Tasks

- [ ] Implement robust FastAPI Application
- [ ] Endpoint GET `/` - Shell Layout (DaisyUI)
- [ ] Endpoint GET `/snippets/table/{table_name}` - Dynamic SQLAlchemy fetching
- [ ] Jinja Templates using HTMX for 5s auto-refresh
