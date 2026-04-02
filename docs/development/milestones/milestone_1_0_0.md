# Milestone v1.0.0 — MVP Production Deployment

> **Target:** v1.0.0 — Production-ready field deployment, stabilization
>
> **Status:** ⏳ Planned
>
> **References:** [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md), [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md), [AGENTS.md](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md)
>
> **User Stories:** `n/a` (cross-cutting stabilization)

---

## Overview

v1.0.0 is the **production-ready** milestone. The system must be deployable to
remote Raspberry Pi 5 stations and run autonomously for months without human
intervention. This milestone focuses on hardening, deployment automation, and
operational tooling — no new features.

### Prerequisites (must be completed first)

| Milestone  | Feature                                           |
| ---------- | ------------------------------------------------- |
| **v0.5.0** | Processor (Indexer + Janitor)                     |
| **v0.6.0** | Uploader (FLAC compression, remote sync)          |
| **v0.7.0** | Gateway (Caddy reverse proxy, HTTPS)              |
| **v0.9.0** | Web-Interface (dashboard, service control)        |

---

## Phase 1: Deployment Automation (Podman Quadlets + Ansible)

**Goal:** Replace Podman Compose with Quadlet unit files for production
deployment. Implement Ansible playbooks for zero-touch fleet provisioning.

### Tasks

- [ ] Convert `compose.yml` services to Podman Quadlet `.container` unit files
- [ ] Create Ansible playbook: `deploy-station.yml`
  - Target: fresh Debian/Fedora Raspberry Pi 5
  - Provisions: uv, Podman, quadlets, config, workspace dirs
- [ ] Create Ansible playbook: `update-station.yml`
  - Pulls new images, restarts services with zero-downtime
- [ ] Implement station bootstrap image (VISION.md "Zero-Touch Provisioning")
- [ ] Test full deployment lifecycle: bootstrap → configure → update → rollback

---

## Phase 2: Configuration Architecture Review (Historical / Deferred)

**Goal:** Re-evaluate filesystem layout, config ownership, and seeding strategy 
for multi-station fleet deployments. This topic has currently been deferred and is kept as a potential future option instead of a strict milestone 1.0.0 target.

### Decision: Config Directory Location (Historical Option)

> **Context (from v0.4.0-v0.5.0 discussion):**
> In v0.4.0 we discussed moving `services/controller/config/` to a repo-root
> `config/` directory. The proposal was rejected under KISS — the Controller is
> the sole consumer of `defaults.yml` and `profiles/*.yml`, so the current
> location correctly signals ownership.
>
> **Re-evaluate at v1.0.0** because the deployment model changes:

#### Arguments FOR moving to `config/` at repo root

1. **Ansible expects top-level config.** Playbooks typically copy a `config/`
   directory to the target host. Having it nested under
   `services/controller/config/` is an awkward path for Ansible templates.
2. **Fleet customization.** In fleet mode, each station gets its own
   `defaults.yml` overlay (different `station_name`, `latitude`, `longitude`).
   A top-level `config/` is the natural target for per-station overrides via
   Ansible `host_vars`.
3. **Quadlets don't use Compose volumes.** With Quadlet unit files, there is no
   `compose.yml` volume mount. Config files must be explicitly copied or
   bind-mounted. A predictable top-level location simplifies this.
4. **New services may seed config.** If the Uploader (v0.6.0) or Gateway (v0.7.0)
   introduce their own seed files, a shared `config/` root avoids scattering
   config across `services/*/config/`.

#### Arguments AGAINST (reasons it was deferred from v0.5.0)

1. **Controller is sole consumer.** No other service reads YAML files directly.
   All services get config from the database (seeded by Controller).
2. **Seeder path resolution works.** Current `_find_service_root()` reliably
   finds `pyproject.toml` and appends `config/`. Simple and proven since v0.3.0.
3. **Breaking change.** Any existing local clones, custom scripts, or docs
   referencing `services/controller/config/` would break.
4. **KISS.** Moving files for aesthetics adds complexity without functional gain.

#### Decision criteria for v1.0.0

- [ ] Does the Ansible playbook benefit from a top-level `config/`?
- [ ] Does Quadlet deployment require config at a different path?
- [ ] Have any new services (Uploader, Gateway) added their own config files?
- [ ] Is the seeder path resolution still correct with Quadlet deployment?

If **2+ criteria** are true → move `config/` to repo root.
If **0-1 criteria** are true → keep at `services/controller/config/`.

#### Implementation plan (if move is approved)

See the detailed plan archived from the v0.5.0 discussion:

1. Move `services/controller/config/` → `config/` (git tracks renames)
2. Update Quadlet unit files (bind-mount path)
3. Simplify `seeder.py`: use `/app/config` (container) or walk-up-to-repo-root
4. Update `.keep` registry
5. Update docs: ADR-0016, ADR-0023, microphone_profiles.md, Controller README
6. Update tests: system `conftest.py`, unit `test_seeder.py`

### Config Schema Evolution Strategy

- [ ] Define policy for schema versioning (new fields added to `config_schemas.py`)
- [ ] Document the "Schema = Schema Evolution Safety, YAML = Operator Interface"
  pattern in ADR-0023 (currently only in code comments)
- [ ] Consider adding a CI test that validates `defaults.yml` values match
  `config_schemas.py` Pydantic defaults (zero drift guarantee)

### Per-Station Configuration Overlay

- [ ] Design the overlay mechanism for fleet deployments:
  - Option A: Ansible `host_vars` → Jinja2 template → `defaults.yml` per station
  - Option B: Single `defaults.yml` + env-var overrides in Quadlet unit files
  - Option C: Separate `station.yml` with only station-specific values
    (`station_name`, `latitude`, `longitude`), merged at seeder level
- [ ] Decide whether `defaults.yml` should contain operational defaults (shared
  across fleet) while per-station identity lives in a separate file

---

## Phase 3: Hardening & Reliability

**Goal:** Ensure the system survives extended unattended operation.

### Tasks

- [ ] Implement watchdog for all Tier 1 services (not just Recorder)
- [ ] Add automatic log rotation via Podman `--log-opt max-size`
- [ ] NVMe health monitoring (SMART data via `smartctl`)
- [ ] Power-loss recovery validation (unclean shutdown → clean restart)
- [ ] Memory leak testing (72h soak test)
- [ ] Ensure all services restart cleanly after DB/Redis outages
- [ ] Implement dead-letter queue for failed uploads (Uploader)

---

## Phase 4: Security & Access Control

**Goal:** Production-grade security for field-deployed devices.

### Tasks

- [ ] Change default admin password on first boot (force password change)
- [ ] HTTPS termination via Gateway (Caddy auto-TLS or manual cert)
- [ ] Review all environment variables for secrets exposure
- [ ] Implement RBAC for Web-Interface (admin vs. viewer roles)
- [ ] Audit container images for known vulnerabilities (Trivy/Grype scan)

---

## Phase 5: Documentation & Release

**Goal:** Complete documentation for operators and contributors.

### Tasks

- [ ] Write operator guide: deployment, configuration, monitoring, troubleshooting
- [ ] Write contributor guide: development setup, testing, code style
- [ ] Update all service READMEs to `Status: implemented`
- [ ] Verify all ADRs reflect current implementation
- [ ] Tag v1.0.0 release
- [ ] Create GitHub release with changelog

---

## Out of Scope (Deferred)

| Item                                   | Target Version |
| -------------------------------------- | -------------- |
| Icecast live streaming                 | v1.1.0         |
| Weather service                        | v1.2.0         |
| BatDetect inference                    | v1.3.0         |
| Tailscale VPN                          | v1.5.0         |
| TimescaleDB continuous aggregates      | post-v1.0.0    |
| Multi-station central dashboard        | post-v1.0.0    |
