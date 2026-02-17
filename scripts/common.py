"""scripts/common.py

Shared utilities for Silvasonic developer scripts.
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
    print(f"\n{Colors.HEADER}{Colors.BOLD}🚀 {msg}{Colors.ENDC}")


def print_step(msg: str) -> None:
    print(f"\n{Colors.OKCYAN}👉 {msg}{Colors.ENDC}")


def print_success(msg: str) -> None:
    print(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")


def print_warning(msg: str) -> None:
    print(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")


def print_error(msg: str) -> None:
    print(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}", file=sys.stderr)


def run_command(
    command: list[str],
    cwd: Path | str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """
    Run a subprocess command safely.
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
    """
    Create directory securely using modern pathlib.
    Enforces permissions idempotently even if the folder already exists.
    """
    p = Path(path).resolve()
    if not p.exists():
        print_step(f"Creating directory: {p}")
        p.mkdir(parents=True, exist_ok=True)
    
    # Always enforce permissions (crucial for rootless Podman)
    p.chmod(mode)
    return p


def check_group_membership(group_name: str, user: str | None = None) -> tuple[bool, bool]:
    """
    Advanced Linux group check.
    Returns a tuple: (is_in_database, is_active_in_shell)
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