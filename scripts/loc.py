import json
import os
import subprocess
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def get_git_files() -> list[str]:
    """Return a list of all files currently tracked by git."""
    try:
        result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return [f for f in result.stdout.splitlines() if f.strip() and os.path.isfile(f)]
    except subprocess.CalledProcessError:
        return []


def count_lines(filepath: str) -> int:
    """Count non-empty lines in a file."""
    try:
        with open(filepath, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())  # Count non-empty lines
    except Exception:
        return 0


def categorize(filepath: str) -> str:
    """Categorize file into docs, tests, code, or ignore based on path and extension."""
    f_lower = filepath.lower()

    # Exclusions
    if "node_modules" in f_lower or ".venv" in f_lower or ".tmp" in f_lower:
        return "ignore"
    if filepath.endswith(
        (
            ".min.css",
            ".min.js",
            ".wav",
            ".mp3",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".woff2",
            ".woff",
            ".ttf",
            ".eot",
            ".ico",
            ".lock",
            "package-lock.json",
            "pnpm-lock.yaml",
            "poetry.lock",
            "uv.lock",
        )
    ):
        return "ignore"

    # Docs
    if filepath.startswith("docs/") or filepath.endswith(".md"):
        return "docs"

    # Tests
    if filepath.endswith(".py") and (
        "/tests/" in filepath
        or filepath.startswith("tests/")
        or "test_" in f_lower
        or "_test" in f_lower
        or "conftest" in f_lower
    ):
        return "tests"
    if filepath.endswith(".yml") and ("/tests/" in filepath or filepath.startswith("tests/")):
        return "tests"

    # Code
    code_exts = (
        ".py",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".sh",
        ".yml",
        ".yaml",
        ".toml",
        ".json",
        "Containerfile",
        "justfile",
        ".sql",
        "Caddyfile",
    )
    if (
        filepath.endswith(code_exts)
        or "Containerfile" in filepath
        or filepath == "justfile"
        or filepath == "Caddyfile"
    ):
        return "code"

    return "ignore"


def get_service_name(filepath: str) -> str:
    """Return the module/service name for the breakdown table.

    Classifies into svc:name, pkg:name, or sys:name to cover 100% of the repo.
    """
    parts = Path(filepath).parts
    if not parts:
        return "sys:root"

    top_dir = parts[0]

    if top_dir == "services" and len(parts) >= 2:
        return f"svc:{parts[1]}"
    elif top_dir == "packages" and len(parts) >= 2:
        return f"pkg:{parts[1]}"
    elif top_dir in ("scripts", "docs"):
        return f"sys:{top_dir}"
    elif len(parts) == 1:
        return "sys:root"
    else:
        # fallback for anything else (e.g. .github)
        return f"sys:{top_dir}"


def main() -> None:
    """Gather LOC stats and print a breakdown table to the terminal."""
    console = Console()

    # Ensure we are in project root
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)

    files = get_git_files()

    # Global Stats
    global_stats = {
        "docs": {"files": 0, "lines": 0},
        "tests": {"files": 0, "lines": 0},
        "code": {"files": 0, "lines": 0},
    }

    # Per-Service Stats
    service_stats = {}

    raw_files_data = []

    for f in files:
        cat = categorize(f)
        if cat == "ignore":
            continue

        lines = count_lines(f)
        svc = get_service_name(f)

        raw_files_data.append({"filepath": f, "category": cat, "lines": lines, "service": svc})

        # update global
        global_stats[cat]["files"] += 1
        global_stats[cat]["lines"] += lines

        # update service specific
        svc = get_service_name(f)
        if svc:
            if svc not in service_stats:
                service_stats[svc] = {
                    "docs": {"files": 0, "lines": 0},
                    "tests": {"files": 0, "lines": 0},
                    "code": {"files": 0, "lines": 0},
                }
            service_stats[svc][cat]["files"] += 1
            service_stats[svc][cat]["lines"] += lines

    #
    # ---- RENDER TERMINAL OUTPUT ----
    #

    # 1. Global Summary Table
    table_global = Table(
        title="[bold cyan]Silvasonic - Overall Repository Codebase[/bold cyan]", box=box.ROUNDED
    )
    table_global.add_column("Category", style="cyan", no_wrap=True)
    table_global.add_column("Files", justify="right", style="magenta")
    table_global.add_column("Lines of Code", justify="right", style="green")

    table_global.add_row(
        "Production Code", str(global_stats["code"]["files"]), str(global_stats["code"]["lines"])
    )
    table_global.add_row(
        "Test Code", str(global_stats["tests"]["files"]), str(global_stats["tests"]["lines"])
    )
    table_global.add_row(
        "Docs & Specs", str(global_stats["docs"]["files"]), str(global_stats["docs"]["lines"])
    )

    total_files = sum(s["files"] for s in global_stats.values())
    total_lines = sum(s["lines"] for s in global_stats.values())
    table_global.add_section()
    table_global.add_row(
        "[bold]TOTAL[/bold]", f"[bold]{total_files}[/bold]", f"[bold]{total_lines}[/bold]"
    )

    console.print()
    console.print(table_global)

    # 2. Service-specific Breakdown
    if service_stats:
        table_services = Table(
            title="[bold yellow]Breakdown per Module (100% Coverage)[/bold yellow]", box=box.ROUNDED
        )
        table_services.add_column("Module", style="yellow")
        table_services.add_column("Production LOC", justify="right", style="green")
        table_services.add_column("Test LOC", justify="right", style="blue")
        table_services.add_column("Docs LOC", justify="right", style="white")
        table_services.add_column("Total LOC", justify="right", style="bold magenta")

        # sort services alphabetically
        sorted_services = sorted(service_stats.items())

        for svc, s_stats in sorted_services:
            code_loc = s_stats["code"]["lines"]
            test_loc = s_stats["tests"]["lines"]
            docs_loc = s_stats["docs"]["lines"]
            total = code_loc + test_loc + docs_loc

            table_services.add_row(
                svc,
                str(code_loc) if code_loc > 0 else "-",
                str(test_loc) if test_loc > 0 else "-",
                str(docs_loc) if docs_loc > 0 else "-",
                str(total),
            )

        console.print()
        console.print(table_services)

    # Analysis Panel
    code = global_stats["code"]["lines"]
    tests = global_stats["tests"]["lines"]
    docs = global_stats["docs"]["lines"]

    test_ratio = (tests / code) * 100 if code > 0 else 0
    docs_ratio = (docs / code) * 100 if code > 0 else 0

    analysis_text = (
        f"[bold]Insights:[/bold]\n"
        f"• Ratio Test-Code : Prod-Code = [bold green]{test_ratio:.1f}%[/bold green]\n"
        f"• Ratio Docs : Prod-Code = [bold green]{docs_ratio:.1f}%[/bold green]\n"
    )

    console.print()
    console.print(
        Panel(
            analysis_text,
            title="[bold]Codebase Analysis[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Export to JSON
    tmp_dir = project_root / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    export_path = tmp_dir / "loc.json"

    export_data = {
        "global_stats": global_stats,
        "service_stats": service_stats,
        "raw_files": raw_files_data,
    }

    with open(export_path, "w", encoding="utf-8") as out_f:
        json.dump(export_data, out_f, indent=2)

    console.print(f"[dim]Analysis data exported to: {export_path.relative_to(project_root)}[/dim]")
    console.print()


if __name__ == "__main__":
    main()
