#!/usr/bin/env python3
import os
import sys

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

    # Determine files to process
    # If args provided (e.g. from pre-commit), use those. Otherwise find all.
    explicit_files = sys.argv[1:] if len(sys.argv) > 1 else None

    # 1. Python (Ruff)
    # Filter if explicit files given, else use "."
    if explicit_files is not None:
        python_files = [f for f in explicit_files if f.endswith(".py")]
    else:
        python_files = ["."]  # "." tells ruff to search everything

    if python_files:
        print_step("Formatting Python (Ruff)...")
        # extend command with file list
        run_command(["uv", "run", "ruff", "format"] + python_files)
        run_command(["uv", "run", "ruff", "check", "--fix"] + python_files)

    # 2. Shell Scripts (Beautysh)
    if explicit_files is not None:
        sh_files = [f for f in explicit_files if f.endswith(".sh")]
    else:
        sh_files = find_files([".sh"])

    if sh_files:
        print_step("Formatting Shell Scripts (Beautysh)...")
        run_command(["uv", "run", "beautysh", "-i", "2"] + sh_files)

    # 3. YAML (yamlfix)
    if explicit_files is not None:
        yaml_files = [f for f in explicit_files if f.endswith(".yaml") or f.endswith(".yml")]
    else:
        yaml_files = find_files([".yaml", ".yml"])

    if yaml_files:
        print_step("Formatting YAML (yamlfix)...")
        run_command(["uv", "run", "yamlfix"] + yaml_files)

    # 4. HTML / Jinja (djLint)
    if explicit_files is not None:
        html_files = [f for f in explicit_files if f.endswith(".html")]
    else:
        html_files = find_files([".html"])

    if html_files:
        print_step("Formatting HTML/Jinja (djLint)...")
        run_command(["uv", "run", "djlint", "--reformat", "--indent", "2"] + html_files)

    print_success("Fix complete.")


if __name__ == "__main__":
    main()
