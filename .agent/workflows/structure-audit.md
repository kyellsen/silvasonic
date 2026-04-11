---
description: Perform a strict documentation structure audit for a specific scope or service against STRUCTURE.md.
---

1. Ensure the user has provided a target scope or service (e.g., `/structure-audit controller`, `/structure-audit processor`, or `/structure-audit root`). If not, ask them what scope they want to audit.
2. Read the architectural documentation boundaries defined in `docs/STRUCTURE.md`. Pay close attention to rules like "Service READMEs must NEVER paraphrase source code" and how to handle ADRs/Milestones.
3. Use your file tools to locate all `.md` files relevant to the provided target scope. 
   - If the target is a service (e.g., `controller`), check `services/controller/README.md` and `docs/services/controller.md`.
   - Read the templates if necessary (e.g., `services/_template_readme.md`) to verify structural compliance.
4. Read the contents of the discovered `.md` files.
5. **No Code/File Changes!** Your task is strictly an audit. Do not modify the markdown files.
6. Evaluate the documentation comprehensively against the `STRUCTURE.md` rules. Check for:
   - File location (Is the file where it belongs according to `STRUCTURE.md`?)
   - Content bounds (e.g., Does the service README list implementation details, database columns, or API routes? If yes, that's a violation.)
   - Template compliance (Does the document contain the mandatory headers defined in its respective `_template.md`?)
   - DRY violations (Is documentation duplicated instead of linked?)
7. Present your findings directly in your chat response using markdown, or create an artifact. **CRITICAL:** Do NOT write any physical `.md` files (like `structure_audit_report_<target>.md`) to the repository folder or its subdirectories! The audit report must live only in your temporary memory (as a standard chat response, an explicit UI artifact, or a file in `/tmp/`) so it does not clutter the git repository.
8. Ask the user if they'd like you to start refactoring the documentation based on the audit results.
