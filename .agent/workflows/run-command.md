---
description: How to run terminal commands safely (CRITICAL bug workaround)
---

# Running Terminal Commands

> [!CAUTION]
> **You MUST follow this workflow for EVERY terminal command.**

## Bug Context

There is a known VS Code shell integration bug where reading stdout directly from the terminal hangs indefinitely. This affects all AI agents in this workspace.

## Mandatory Steps

1. **NEVER** run a command and read its output directly from the terminal.
2. **ALWAYS** redirect both stdout and stderr to a unique file in `/tmp` with a datetime stamp in the filename.
3. **THEN** read the output file to get the results.

## Pattern

```bash
# ✅ CORRECT — always do this:
<command> > /tmp/<description>_$(date +%Y%m%d_%H%M%S).txt 2>&1

# Then read:
cat /tmp/<description>_<datetime>.txt

# ✅ CORRECT examples:
uv sync > /tmp/uv_sync_20260217_120000.txt 2>&1
pytest -v > /tmp/pytest_20260217_120100.txt 2>&1
make build > /tmp/make_build_20260217_120200.txt 2>&1

# ❌ WRONG — never do this:
uv sync
pytest -v
make build
```

## Why This Matters

Without this workaround, your terminal will hang and you will be unable to read any output, blocking all further work.
