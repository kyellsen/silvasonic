---
description: Perform a strict architectural audit of test code for a specific service against testing.md rules.
---

1. Ensure the user has provided a target component or service (e.g., `/test-audit controller`). If not, ask them which service they want to audit.
2. Read the testing constraints and anti-patterns defined in `docs/development/testing.md`. Pay special attention to **Section 5: Test Quality & Anti-Patterns** and the layer-specific rules.
3. Locate all test files for the given target service. Test directories are typically found under `services/<target>/tests/` or `packages/<target>/tests/`. Use search tools or `list_dir` to find the exact structure.
4. Read the Python test files in the discovered directories.
5. **No Code Changes!** Your task is strictly an audit. Do not use file editing tools.
6. Evaluate the test code comprehensively against the `testing.md` rules. Check for:
   - Presence of correct markers (`@pytest.mark.unit`, etc.)
   - Test Quality Anti-Patterns (e.g., Existence/Import Tests, Trivial Equality, Call-Chain Mirroring, Mock-Heavy Verification).
   - "Delete vs. Refactor" recommendations.
   - Layer-specific rule violations (e.g., I/O in unit tests, or mocking the DB in integration tests).
7. Create an artifact (e.g., `audit_report_<target>.md`) summarizing your findings in German. List concrete examples from the code and map them exactly to the rules in `testing.md` they violate or adhere to.
8. Ask the user if they'd like you to start refactoring based on the audit results.
