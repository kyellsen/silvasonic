---
description: Draft a highly rigorous, architecture-compliant milestone plan based on a deep repository scan.
---

1. **Understand Goal:** Ensure the user has provided a topic or version for the milestone (e.g., `/milestone-draft v0.9.0` or `/milestone-draft Web Interface`). If not, ask them.
2. **Phase 1: Context Aggregation (Deep Scan)**
   - **Business Scope:** Use `grep_search` or `view_file` to scan `docs/user_stories/` and map the target feature to exact `US-XXX` stories. Read `ROADMAP.md` and `VISION.md` to identify the correct target version (`vX.Y.Z`) and overall context.
   - **Architecture Constraints:** Scan `docs/adr/` for Architecture Decision Records related to the topic to ensure the plan does not violate established rules (e.g., Worker Pull, Resource Limits, File Mount structures).
   - **Existing Infrastructure:** This is critical! Use `grep_search` to look for existing Pydantic models in `packages/core/src/silvasonic/core/schemas/config_schemas.py` and ORM models in `packages/core/src/silvasonic/core/database/models/`. You must identify what already exists so you can explicitly state to "Extend" rather than "Rebuild". Look for existing test fixtures in `tests/fixtures/`.
   - **Compliance:** Scan `docs/development/testing.md` to enforce exact test markers (`unit`, `integration`, `system`, etc.) for each phase in the plan. Refer to `docs/development/release_checklist.md`.
3. **Phase 2: Strukturierung & Drafting**
   - Base your plan strictly on `docs/development/milestones/_template.md` (read it if you haven't).
   - Organize the plan into logical execution phases (e.g., Spike -> Foundation/Scaffold -> Domain Logic -> System Ecosystem/Config -> Audit -> Release).
   - Inject specific testing tasks into *every* phase using the correct `pytest` marker names from `testing.md`.
   - Include the "Existing Infrastructure (Reuse — Do NOT Rebuild)" table mapping existing components to their required extensions.
4. **Phase 3: Result Delivery**
   - **No Code/File Changes!** Do not write a physical `.md` file to `docs/development/milestones/` yet.
   - Generate an `implementation_plan.md` artifact (or just use markdown in the chat response if more appropriate) containing the complete draft.
   - Importantly, append an "Open Questions for Architect" section at the bottom. Detail any missing ADRs, potential rule violations you detected, or missing details needed before development can begin.
5. **Review:** Ask the user if they'd like to refine the plan, answer the open questions, or save it permanently as `milestone_X_Y_Z.md`.
