import logging
import os
import tomllib
import uuid
from pathlib import Path

import polars as pl
import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from silvasonic.core.database import get_db
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Configure minimal logging
logger = logging.getLogger("silvasonic.db_viewer")

# Locate pyproject.toml for dynamic versioning
try:
    # 1. Try env var or container root
    _pyproject_path = Path(os.environ.get("SILVASONIC_REPO_PATH", "/app")) / "pyproject.toml"
    if not _pyproject_path.exists():
        # 2. Try traversing upwards from __file__
        _curr = Path(__file__).resolve()
        while _curr.parent != _curr:
            if (_curr / "pyproject.toml").exists() and (_curr / "ROADMAP.md").exists():
                _pyproject_path = _curr / "pyproject.toml"
                break
            _curr = _curr.parent

    with open(_pyproject_path, "rb") as f:
        _app_version = tomllib.load(f)["project"]["version"]
except Exception as e:
    logger.warning(f"Could not load version from pyproject.toml: {e}")
    _app_version = "unknown"

# Initialize FastAPI App
root_path = os.getenv("SILVASONIC_API_ROOT_PATH", "")
app = FastAPI(
    title="Silvasonic DB Viewer",
    description="Read-only diagnostic view for the Silvasonic Database",
    version=_app_version,
    root_path=root_path,
)


# Paths
_HERE = Path(__file__).parent
_TEMPLATES_DIR = _HERE / "templates"
_STATIC_DIR = _HERE / "static"

# Static files for CSS and vendored JS
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Jinja2 Templates setup
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@app.get("/healthy", tags=["ops"])
async def healthy() -> dict[str, str]:
    """Standard health check endpoint."""
    return {"status": "ok", "service": "db-viewer"}


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    active_table: str | None = None,
    sort_by: str | None = None,
    sort_order: str = "desc",
    interval: int = 5,
    limit: int = 50,
) -> HTMLResponse:
    """Render the main shell layout with the sidebar."""
    # List of tables to inspect
    tables = [
        "recordings",
        "detections",
        "uploads",
        "devices",
        "system_config",
        "system_services",
        "microphone_profiles",
        "taxonomy",
        "weather",
        "users",
    ]

    # Default to first table if none selected or invalid
    if not active_table or active_table not in tables:
        active_table = tables[0]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_title": app.title,
            "app_version": app.version,
            "tables": tables,
            "active_table": active_table,
            "sort_by": sort_by or "",
            "sort_order": sort_order,
            "interval": interval,
            "limit": limit,
            "root_path": request.scope.get("root_path", ""),
        },
    )


@app.get("/snippets/table/{table_name}", response_class=HTMLResponse)
async def get_table_snippet(
    request: Request,
    table_name: str,
    sort_by: str | None = None,
    sort_order: str = "desc",
    interval: int = 5,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Fetch the latest 50 rows from the given table generically.

    Returns only the HTML snippet for HTMX.
    """
    # Prevent basic SQL injection by validating table name against allowlist
    allowlist = [
        "recordings",
        "detections",
        "uploads",
        "devices",
        "system_config",
        "system_services",
        "microphone_profiles",
        "taxonomy",
        "weather",
        "users",
    ]
    if table_name not in allowlist:
        return HTMLResponse(
            content="<div class='alert alert-error'>Invalid table</div>", status_code=400
        )

    try:
        # Build query dynamically
        query_str = f"SELECT * FROM {table_name}"

        # Only add ORDER BY if sort_by is provided and looks like a valid
        # identifier (basic protection)
        if sort_by and sort_by.isidentifier():
            order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"
            query_str += f" ORDER BY {sort_by} {order_dir}"

        # Ensure limit is a positive integer
        safe_limit = limit if isinstance(limit, int) and limit > 0 else 50
        query_str += f" LIMIT {safe_limit}"
        query = text(query_str)
        result = await db.execute(query)

        # Result is an iterable of SQLAlchemy rows
        rows = result.mappings().all()

        # Extract column names from the first row, or use keys() if no data
        columns = list(result.keys()) if result.keys() else []

        return templates.TemplateResponse(
            request=request,
            name="table_snippet.html",
            context={
                "table_name": table_name,
                "columns": columns,
                "rows": rows,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "interval": interval,
                "limit": limit,
                "root_path": request.scope.get("root_path", ""),
            },
        )
    except Exception as e:
        logger.error(f"Error fetching table {table_name}: {e}")
        return HTMLResponse(
            content=f"<div class='alert alert-error'>Error: {e!s}</div>", status_code=500
        )


@app.get("/export/{table_name}")
async def export_table(
    table_name: str, fmt: str = "csv", db: AsyncSession = Depends(get_db)
) -> Response:
    """Export the current table to CSV, JSON, or Parquet."""
    allowlist = [
        "recordings",
        "detections",
        "uploads",
        "devices",
        "system_config",
        "system_services",
        "microphone_profiles",
        "taxonomy",
        "weather",
        "users",
    ]
    if table_name not in allowlist:
        return Response(content="Invalid table", status_code=400)

    if fmt not in ["csv", "json", "parquet"]:
        return Response(content="Invalid format", status_code=400)

    try:
        # Fetch all data unconditionally for export
        query = text(f"SELECT * FROM {table_name}")
        result = await db.execute(query)
        rows = result.mappings().all()

        # Clean data for Polars (convert UUIDs, dicts, lists to strings)
        import json

        cleaned_rows = []
        for row in rows:
            c = {}
            for k, v in row.items():
                if isinstance(v, uuid.UUID):
                    c[k] = str(v)
                elif isinstance(v, (dict, list)):
                    c[k] = json.dumps(v)
                else:
                    c[k] = v
            cleaned_rows.append(c)

        # Create Polars DataFrame
        # Setting strict=False and catching potential errors just in case
        df = pl.DataFrame(cleaned_rows, strict=False)

        if fmt == "csv":
            data = df.write_csv().encode("utf-8")
            media_type = "text/csv"
        elif fmt == "json":
            data = df.write_json().encode("utf-8")
            media_type = "application/json"
        elif fmt == "parquet":
            from io import BytesIO

            buf = BytesIO()
            df.write_parquet(buf)
            data = buf.getvalue()
            media_type = "application/vnd.apache.parquet"

        headers = {"Content-Disposition": f"attachment; filename={table_name}.{fmt}"}
        return Response(content=data, media_type=media_type, headers=headers)

    except Exception as e:
        logger.error(f"Export error for {table_name}: {e}")
        return Response(content=f"Error exporting data: {e!s}", status_code=500)


if __name__ == "__main__":
    uvicorn.run(
        "silvasonic.db_viewer.__main__:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info",
        root_path=root_path,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
