#!/usr/bin/env python3
import os

from common import print_header, print_step, print_success, run_command


def find_files(extensions: list[str], exclude_dirs: list[str] | None = None) -> list[str]:
    """Find files with given extensions, skipping excluded dirs."""
    if exclude_dirs is None:
        exclude_dirs = [
            ".venv",
            ".git",
            "site",
            "__pycache__",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "dist",
            "build",
        ]

    matches = []
    for root, dirs, files in os.walk("."):
        # Modify dirs in-place to skip exclusions
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for filename in files:
            for ext in extensions:
                if filename.endswith(ext):
                    matches.append(os.path.join(root, filename))
    return matches


def main() -> None:
    """Run auto-fixers for Python, Shell, YAML, and HTML."""
    print_header("Running Auto-Fixes...")

    # 1. Python (Ruff)
    print_step("Formatting Python (Ruff)...")
    run_command(["uv", "run", "ruff", "format", "."])
    run_command(["uv", "run", "ruff", "check", "--fix", "."])

    # 2. Shell Scripts (Beautysh)
    # Only if shell scripts exist (we are deleting them, but user might add some)
    sh_files = find_files([".sh"])
    if sh_files:
        print_step("Formatting Shell Scripts (Beautysh)...")
        run_command(["uv", "run", "beautysh", "-i", "2"] + sh_files)

    # 3. YAML (yamlfix)
    yaml_files = find_files([".yaml", ".yml"])
    if yaml_files:
        print_step("Formatting YAML (yamlfix)...")
        # Run in chunks if too many? For now all at once.
        run_command(["uv", "run", "yamlfix"] + yaml_files)

    # 4. HTML / Jinja (djLint)
    html_files = find_files([".html"])
    if html_files:
        print_step("Formatting HTML/Jinja (djLint)...")
        run_command(["uv", "run", "djlint", "--reformat", "--indent", "2"] + html_files)

    print_success("Fix complete.")


if __name__ == "__main__":
    main()
