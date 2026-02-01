import grp
import os
import pwd
import subprocess
import sys


# Colors
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
    """Print a header message."""
    print(f"{Colors.HEADER}🚀 {msg}{Colors.ENDC}")


def print_step(msg: str) -> None:
    """Print a step message."""
    print(f"{Colors.OKCYAN}👉 {msg}{Colors.ENDC}")


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")


def print_warning(msg: str) -> None:
    """Print a warning message."""
    print(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")


def print_error(msg: str) -> None:
    """Print an error message."""
    print(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}")


def run_command(
    command: list[str] | str,
    cwd: str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command with nice printing."""
    cmd_str = " ".join(command) if isinstance(command, list) else command
    # print_step(f"Running: {cmd_str}")
    try:
        # If shell=True, command should be a string (or we rely on subprocess joining)
        # But we generally prefer shell=False with list.
        # If the user passed shell=True to this wrapper, we respect it.
        result = subprocess.run(command, cwd=cwd, check=check, env=env, shell=shell, text=True)
        return result
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {cmd_str}")
        if check:
            sys.exit(e.returncode)
        raise e


def ensure_dir(path: str, mode: int = 0o755) -> None:
    """Create directory if it doesn't exist."""
    if not os.path.exists(path):
        print_step(f"Creating directory: {path}")
        os.makedirs(path, exist_ok=True)
        os.chmod(path, mode)


def check_group_membership(group_name: str) -> bool:
    """Check if the current user is in the specified group."""
    try:
        user = os.environ.get("USER", pwd.getpwuid(os.getuid()).pw_name)
        groups = [g.gr_name for g in grp.getgrall() if user in g.gr_mem]
        gid = pwd.getpwnam(user).pw_gid
        groups.append(grp.getgrgid(gid).gr_name)
        return group_name in groups
    except KeyError:
        return False
