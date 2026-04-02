# DRY Documentation Refactoring — Reduce Status Duplication

**Status:** `open`
**Priority:** 3 (low — quality-of-life improvement, not blocking any milestone)
**Labels:** `tech-debt`, `architecture`
**Service(s) Affected:** `docs` (cross-cutting, all services)

---

## 1. Description

Service implementation status is currently tracked redundantly across 5+ files. Changing a service's status (e.g., from "Planned" to "Implemented") requires synchronized edits in:

- `VISION.md` (Tier 1/2 tables: `✅ AS-IS` / `⏳ TO-BE`)
- `README.md` (Current Services table)
- `services/<svc>/README.md` (Status header + Implementation Status table)
- `docs/services/<svc>.md` (Status line)
- `docs/arch/port_allocation.md` (Status column)

This creates a maintenance burden and introduces drift risk when advancing milestones.

## 2. Context & Root Cause Analysis

* **Component:** Documentation architecture (AGENTS.md §4)
* **Mechanism:** AGENTS.md §4 mandates `AS-IS` / `TO-BE` labels on every section and `Status:` lines on every service doc. While this ensures clarity per-document, it implicitly requires multi-file edits for every status change.

The current Uploader→Processor refactoring (v0.5.x) highlighted this: archiving a single service required edits to 40+ documentation files across 4 atomic commits — a significant portion of which were pure status-label updates.

> **Root Cause:** No single designated "status registry" exists. Each document independently tracks its own status, violating the DRY principle.

## 3. Impact / Consequences

* **Data Capture Integrity:** None — documentation-only changes.
* **System Stability:** None.
* **Developer Productivity:** Moderate negative impact. Every milestone completion requires a documentation sweep across 5+ files. AI agents frequently miss status updates in peripheral documents. Future refactorings (BirdNET v0.8, Gateway v0.7) will face the same multi-file update burden.

## 4. Steps to Reproduce (If applicable)

1. Complete a milestone (e.g., v0.5.0 Processor).
2. Attempt to update all status references.
3. Observe that `VISION.md`, `README.md`, `services/processor/README.md`, `docs/services/processor.md`, and `docs/arch/port_allocation.md` all need synchronized edits.
4. Verify with `grep -rn "Planned\|TO-BE\|AS-IS\|implemented\|partial" --include="*.md"` — dozens of scattered status markers.

## 5. Expected Behavior

A status change (e.g., "BirdNET: planned → implemented") should require editing **at most 2 files**:

1. `ROADMAP.md` (milestone tracking — already the SoT for release timing)
2. The service's own README (`services/<svc>/README.md` Status header)

All other documents should derive status from — or simply link to — these two sources.

## 6. Proposed Solution

### Phase 1: AGENTS.md Rule Amendment (Prerequisites)

Create a new ADR (e.g., ADR-0027) documenting the decision to centralize status tracking. Then update AGENTS.md §4:

**Current rule:**
```
Every doc must label sections AS-IS or TO-BE.
Service docs need a Status: line (implemented | partial | planned).
```

**Proposed rule:**
```
Service READMEs (services/<svc>/README.md) MUST have a Status: header line.
ROADMAP.md is the SoT for milestone completion status.
Other docs MAY include status references but MUST link to the SoT rather than
maintaining independent status tracking.
```

### Phase 2: Simplify Status in Peripheral Documents

| Document | Current | Proposed |
|----------|---------|----------|
| `VISION.md` Tier tables | `Status` column with per-row badges | Keep column but simplify to `✅` / `⏳` without version numbers. Add footer: "See ROADMAP.md for version details." |
| `README.md` Current Services | `Status` column | Keep as-is — already clean (only shows implemented services) |
| `docs/services/<svc>.md` | Full `Status:` line | Keep — these are link-stubs anyway, one line is fine |
| `docs/arch/port_allocation.md` | `Status` column per port | Replace version numbers with `✅` / `📋` only |
| `services/<svc>/README.md` Implementation Status tables | Feature-by-feature status | Keep — these are the SoT for per-feature granularity |

### Phase 3: Evaluate (NOT in initial scope)

The following changes were proposed by an external review but are **explicitly deferred** after critical analysis:

| Proposed Change | Decision | Rationale |
|---|---|---|
| Remove technical details from Glossary | ❌ Rejected | Glossary serves as AI-agent context; tech details are intentional |
| Remove Milestone tags from User Stories | ❌ Rejected | Traceability loss (US → Release mapping) |
| Move technical Acceptance Criteria from US to Service README | ❌ Rejected | Breaks US → Test specification link |
| Make VISION.md "immutable" (no status) | ❌ Rejected | VISION.md is a living architecture doc, status provides orientation |

### Estimated Scope

- **ADR-0027:** ~1 file (new)
- **AGENTS.md:** ~5 lines changed
- **VISION.md:** ~10 lines (simplify version numbers in Status column)
- **port_allocation.md:** ~10 lines (simplify version numbers)
- **Total:** ~4 files, ~30 lines — small, focused change

### Timing

Execute **after** the Uploader→Processor refactoring is fully complete (Phase 1 + Phase 2), ideally as part of a v0.6.0-dev documentation cleanup sprint.

## 7. Relevant Documentation Links

- [AGENTS.md §4](https://github.com/kyellsen/silvasonic/blob/main/AGENTS.md) — Current documentation rules
- [VISION.md](https://github.com/kyellsen/silvasonic/blob/main/VISION.md) — Tier tables with status
- [ROADMAP.md](https://github.com/kyellsen/silvasonic/blob/main/ROADMAP.md) — Milestone SoT
- [DRY Review Analysis](/home/kyellsen/.gemini/antigravity/brain/00d4dca7-6463-4a14-9230-38fafc2cd1e2/dry_review.md) — Full critical review of the original proposal
