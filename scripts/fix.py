"""Auto-fix code quality issues (formatting + lint fixes).

Usage:
    uv run python scripts/fix.py          # Fix entire repo
    uv run python scripts/fix.py file.py  # Fix specific files (pre-commit mode)
"""

import subprocess
import sys
from pathlib import Path

from common import print_error, print_header, print_step, print_success

# ── Project root = parent of scripts/ ─────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(label: str, cmd: list[str], *, must_pass: bool = True) -> bool:
    """Run a command, print a step header, and return True on success."""
    print_step(f"{label}: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    if result.returncode == 0:
        print_success(f"{label} done.")
        return True
    if must_pass:
        print_error(f"{label} failed.")
    return False


def main() -> None:
    """Run ruff format and ruff lint --fix."""
    print_header("Auto-fixing Code Quality Issues")

    # If pre-commit passes filenames, use them; otherwise fix the whole repo.
    targets: list[str] = sys.argv[1:] if len(sys.argv) > 1 else ["."]

    # 1. Auto-format (must succeed)
    if not _run("Ruff Format", ["uv", "run", "ruff", "format", *targets]):
        sys.exit(1)

    # 2. Lint auto-fix (best-effort — unfixable issues are reported by `make check`)
    _run(
        "Ruff Fix",
        ["uv", "run", "ruff", "check", "--fix", *targets],
        must_pass=False,
    )

    print_success("All auto-fixes applied.")


if __name__ == "__main__":
    main()
