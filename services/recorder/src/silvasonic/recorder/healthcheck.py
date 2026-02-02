import os
import sys


def is_ffmpeg_running() -> bool:
    """Check if ffmpeg is running by scanning /proc."""
    try:
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    # Read cmdline
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        # Cmdline is null-separated
                        content = f.read()
                        if not content:
                            continue
                        # Decode and check
                        # ffmpeg usually appears as 'ffmpeg' in the first argument
                        cmd_str = content.decode("utf-8", errors="ignore")
                        if "ffmpeg" in cmd_str:
                            return True
                except (PermissionError, FileNotFoundError, OSError):
                    continue
    except Exception:
        return False
    return False


if __name__ == "__main__":
    # We want to exit 0 if healthy (running), 1 if unwell
    if is_ffmpeg_running():
        sys.exit(0)
    else:
        sys.exit(1)
