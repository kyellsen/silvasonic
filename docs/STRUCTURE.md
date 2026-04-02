# Documentation Structure & DRY Rules

This document dictates the architectural boundaries of all `.md` files in the Silvasonic repository.
To prevent documentation drift and maintain the DRY (Don't Repeat Yourself) principle, you **MUST** adhere to these boundaries.

## 1. Central Abstractions (Root Level)

- **`README.md`**: Human entry point. Quickstart and "What is this?" Overview.
- **`AGENTS.md`**: AI entry point. Hard constraints, rules, and coding directives.
- **`ROADMAP.md`**: The **When**. The absolute Source of Truth for milestones, versioning, and feature timing.
- **`VISION.md`**: The **Why**. The "North Star", architecture ideals, and endgame goals. Does *not* track release versions.
- *(Note: `docs/glossary.md` holds the canonical domain language definitions. It lives in `docs/` to avoid cluttering the root, but functions as a central abstraction).*

## 2. MkDocs Integration Wrappers

We use MkDocs for our documentation site. Since MkDocs cannot natively render markdown files originating outside the `docs/` folder, we use Jinja **include wrappers** (e.g., `{% include "../ROADMAP.md" %}`). 
To preserve GitHub root visibility while supporting MkDocs, these specific duplicates in `docs/` are **explicitly allowed**:
- `docs/AGENTS.md` (Wraps `../AGENTS.md`)
- `docs/ROADMAP.md` (Wraps `../ROADMAP.md`)
- `docs/VISION.md` (Wraps `../VISION.md`)
- *(Note: The main `README.md` requires no wrapper, as it is included directly within `docs/index.md`).*

## 3. Templates (`_template.md`)

Each specific documentation group MUST provide a template to guarantee a consistent structure. These templates dictate the required sections.
- **`docs/services/_template.md`**: For drafting *planned* services.
- **`docs/user_stories/_template.md`**: For writing User Stories.
- **`docs/adr/_template.md`**: For Architecture Decision Records.
- **`docs/development/issues/_template.md`**: For tracking complex bugs or spikes.
- **`docs/development/milestones/_template.md`**: For sprint planning chunks.
- **`services/_template_readme.md`**: For the `README.md` of implemented services.

## 4. Docs-as-Code: Service READMEs

Implemented services are documented strictly in their own directory (`services/<svc>/README.md`).
**CRITICAL RULE:** A Service README must **NEVER** paraphrase source code. Do not list API endpoints, database columns, or Python classes. The code is the Source of Truth.

A Service README is explicitly limited to the structured headers defined in **`services/_template_readme.md`**. You MUST follow this boilerplate exactly.

*(Note: `docs/services/<svc>.md` only exists for planned services. Once a service is implemented, this file must become a 1-sentence link-stub pointing to the actual Service README).*

## 5. Domain Documentation (`docs/`)

- **`docs/arch/*.md`**: System-wide architecture patterns that span multiple services (e.g., filesystem governance, port allocation).
- **`docs/user_stories/*.md`**: The **Who** and **What**. Focus on clear functional descriptions. Technical specifications (e.g., database fields, Redis keys, system paths) may be included in Acceptance Criteria *only* if necessary for exactness, but always prefer expressing the core requirement without them if possible.
- **`docs/adr/*.md`**: ADRs are immutable historical records of Past Decisions. Never update an accepted ADR to match new code. If an architectural path changes, create a new ADR and update the old one *only* to change its status to `Superseded by ADR-XXX`.
- **`docs/hardware.md`**: Central configuration or technical context that cuts across multiple domains.
- **`docs/deployment/*.md`**: Deployment processes, rollout strategies, and infrastructure guides.

## 6. Working Documents & Development (`docs/development/`)

- **`docs/development/*.md`**: Global development guidelines (e.g., `testing.md`, `commit.md`, `service_blueprint.md`).
- **`docs/development/milestones/*.md`**: Granular sprint planning chunks tracking active work. **Rule:** Once a milestone is completed, it becomes an immutable historical snapshot (like an ADR). Never update old milestones to reflect new refactoring realities.
- **`docs/development/issues/*.md`**: Tracking specific bugs or temporary architectural investigations.
- Scrap ideas or obsolete refactoring notes **MUST** go to the git-ignored `.tmp/` directory or be deleted. Do not bloat the repository with dead notes.

## 7. AI & Automation Tooling

- **`.agent/**/*.md`**: Internal workflow definitions and commands exclusively meant for execution by autonomous AI agents.
- **`prompts/*.md`**: A repository of reusable, human-authored prompts. Used by developers to copy-paste (and optionally modify) instructions to AI agents.
