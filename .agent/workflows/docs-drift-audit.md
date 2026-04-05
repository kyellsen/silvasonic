---
description: Perform a documentation drift audit for a specific scope (defaults to root), detecting contradictions between .md files and the source code (Source of Truth) based on STRUCTURE.md.
---

1. Check if the user has provided a target scope or service (e.g., `/docs-drift-audit controller`). If no scope is provided, default to the entire repository (`root`).
2. Read the architectural documentation boundaries defined in `docs/STRUCTURE.md` and the core directives in `AGENTS.md`. Pay close attention to the "Docs-as-Code" rules and exactly which document is the Single Source of Truth for what.
3. Use file tools to locate all `.md` files relevant to the target scope.
   - **CRITICAL**: Exclude all unversioned, cache, or temporary directories. You **MUST NOT** read `.md` files from: `.tmp/`, `.venv*/`, `.git/`, or `__pycache__/`. 
   - *Tip: Using `git ls-files "*.md"` ensures you only scan version-controlled files.*
4. **Locate the Source of Truth:** Identify and read the corresponding source code files (Python, `justfile`, `docker-compose.yml`, Pydantic schemas, etc.) that represent the actual implemented reality for the target scope.
5. **No Code/File Changes!** Your task is strictly an audit. Do not modify the markdown or code files.
6. Evaluate the documentation for **Drift**:
   - **Docs-to-Code Drift:** Does the documentation describe features, APIs, configurations, or flows that contradict the actual source code? 
   - **Inter-Docs Drift:** Do different markdown files assert conflicting facts about the same topic?
   - **DRY/Structure Violations:** Are technical details (like DB columns, API routes, or env vars) hardcoded into `.md` files instead of relying on the code, which violates `STRUCTURE.md`?
7. Create an artifact (e.g., `drift_audit_report_<target>.md`) summarizing your findings in **German**. 
   - List concrete examples of drift.
   - Reference the exact files and lines involved.
   - Categorize the severity (e.g., minor wording issue vs. critical architectural drift).
8. Ask the user if they'd like you to start resolving the identified drift based on your report.
