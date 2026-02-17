"""Auto-fix code quality issues (formatting + lint fixes).

Usage:
    uv run python scripts/fix.py          # Fix entire repo
    uv run python scripts/fix.py file.py  # Fix specific files (pre-commit mode)
"""

import subprocess
import sys
from pathlib import Path

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, must_pass: bool = True) -> bool:
    """Run a command and return True on success."""
    print(f"\n🔧 Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode == 0 or not must_pass


def main() -> None:
    """Run ruff format and ruff lint --fix."""
    # If pre-commit passes filenames, use them; otherwise fix the whole repo.
    targets: list[str] = sys.argv[1:] if len(sys.argv) > 1 else ["."]

    # 1. Auto-format (must succeed)
    if not _run(["uv", "run", "ruff", "format", *targets]):
        print("\n❌ Ruff format failed.", file=sys.stderr)
        sys.exit(1)

    # 2. Lint auto-fix (best-effort — unfixable issues are reported by `make check`)
    _run(["uv", "run", "ruff", "check", "--fix", *targets], must_pass=False)

    print("\n✅ All auto-fixes applied.")


if __name__ == "__main__":
    main()
