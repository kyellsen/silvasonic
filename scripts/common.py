"""Shared utilities for Silvasonic developer scripts.

Strictly relies on the Python Standard Library to ensure it can run
during initial bootstrapping (before virtual environments exist).
"""

import grp
import os
import pwd
import subprocess
import sys
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output."""

    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def print_header(msg: str) -> None:
    """Print a bold header message."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}🚀 {msg}{Colors.ENDC}")


def print_step(msg: str) -> None:
    """Print a step indicator message."""
    print(f"\n{Colors.OKCYAN}👉 {msg}{Colors.ENDC}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")


def print_warning(msg: str) -> None:
    """Print a warning message."""
    print(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")


def print_error(msg: str) -> None:
    """Print an error message to stderr."""
    print(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}", file=sys.stderr)


def run_command(
    command: list[str],
    cwd: Path | str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command safely.

    Strictly accepts lists (no shell=True) for security and predictability.
    """
    cmd_str = " ".join(command)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=check,
            env=env,
            text=True,
            capture_output=capture_output,
        )
        return result
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed with exit code {e.returncode}: {cmd_str}")
        if e.stderr:
            print_error(e.stderr.strip())
        if check:
            sys.exit(e.returncode)
        raise e
    except FileNotFoundError:
        print_error(f"Command not found in PATH: {command[0]}")
        if check:
            sys.exit(1)
        raise


def ensure_dir(path: Path | str, mode: int = 0o755) -> Path:
    """Create directory securely using modern pathlib.

    Enforces permissions idempotently even if the folder already exists.
    """
    p = Path(path).resolve()
    if not p.exists():
        print_step(f"Creating directory: {p}")
        p.mkdir(parents=True, exist_ok=True)

    # Always enforce permissions (crucial for rootless container engines)
    p.chmod(mode)
    return p


def check_group_membership(group_name: str, user: str | None = None) -> tuple[bool, bool]:
    """Advanced Linux group check.

    Returns a tuple: (is_in_database, is_active_in_shell).
    This is vital to warn users if they need to reboot/re-login.
    """
    if user is None:
        user = os.environ.get("USER", pwd.getpwuid(os.getuid()).pw_name)

    # 1. Check active session groups (what the current script is actually allowed to do)
    active_gids = os.getgroups()
    active_groups = [grp.getgrgid(gid).gr_name for gid in active_gids]
    is_active = group_name in active_groups

    # 2. Check database groups (/etc/group)
    try:
        db_groups = [g.gr_name for g in grp.getgrall() if user in g.gr_mem]
        # Always add the user's primary group too
        primary_gid = pwd.getpwnam(user).pw_gid
        db_groups.append(grp.getgrgid(primary_gid).gr_name)
        is_in_db = group_name in db_groups
    except KeyError:
        is_in_db = False

    return is_in_db, is_active


# -- .env helpers ----------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


def load_env_value(key: str) -> str | None:
    """Read a single key from .env (stdlib-only, no dotenv dependency).

    Returns None when the key is absent or the file does not exist.
    """
    if not _ENV_FILE.exists():
        return None
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            v = v.strip()
            # Strip surrounding quotes if present (e.g. KEY="value")
            if len(v) >= 2 and v[0] in ('"', "'") and v[-1] == v[0]:
                v = v[1:-1]
            return v
    return None


def get_workspace_path() -> Path:
    """Resolve SILVASONIC_WORKSPACE_PATH from environment or .env file.

    Priority: shell environment > .env file.
    Aborts with a clear error if the variable is not set anywhere.
    """
    workspace = os.environ.get("SILVASONIC_WORKSPACE_PATH") or load_env_value(
        "SILVASONIC_WORKSPACE_PATH"
    )

    if not workspace:
        print_error(
            "SILVASONIC_WORKSPACE_PATH is not set!\n"
            "   Please define it in .env (or export it in your shell).\n"
            "   Example:  SILVASONIC_WORKSPACE_PATH=/mnt/data/dev_workspaces/silvasonic/"
        )
        sys.exit(1)

    path = Path(workspace)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    return path.resolve()


def fmt_duration(seconds: float) -> str:
    """Format seconds into a human-readable string (e.g. '1.2s' or '2m 3.4s')."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.1f}s"


def print_banner() -> None:
    """Print the Silvasonic ASCII banner from scripts/banner.txt."""
    banner_file = Path(__file__).resolve().parent / "banner.txt"
    if banner_file.exists():
        text = banner_file.read_text().rstrip("\n")
        print(f"\n{Colors.OKCYAN}{Colors.BOLD}{text}{Colors.ENDC}\n")
