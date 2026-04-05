---
description: Perform a Data Contract Audit to enforce the single source of truth for Pydantic schemas (AGENTS.md Rule 8).
---

1. Ensure the user has provided a target component or service (e.g., `/schema-sync processor`). If not, ask them which scope they want to audit.
2. Read `AGENTS.md` (specifically **Rule 8: Data Contracts**) to understand the strict rule against duplicating Pydantic schemas in Tier-2 services.
3. Locate the source code for the given target service (typically `services/<target>/src/silvasonic/<target>/`). Use search tools (e.g. grep for `BaseModel`, `import pydantic`) to identify locally defined schemas, response objects, or event payloads.
4. Scan the central schema registry (`packages/core/src/silvasonic/core/schemas/` and `packages/core/src/silvasonic/core/config_schemas.py`) to cross-reference what already exists globally.
5. **No Code Changes!** Your task is strictly an audit. Do not use file editing tools to alter source code.
6. Evaluate the findings:
   - Identify which local Pydantic models represent shared domain knowledge or data contracts.
   - Flag models that are duplicated or should be elevated to the core package.
   - Note any local schemas that are purely internal/private to the service (which are acceptable).
7. Present your findings as an artifact or chat response. **CRITICAL:** Do NOT write physical `.md` report files to the repository! Generate a clear Refactoring-Vorschlag specifying exactly which classes should be moved to Core.
8. Ask the user if they'd like you to execute the proposed refactoring.
