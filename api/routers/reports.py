"""Reports endpoints — list + read generated reports."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from api.config import config

router = APIRouter()


@router.get("/reports")
async def list_reports(
    type: str | None = Query(default=None, description="Filter by report type prefix (e.g. 'validation', 'strategy')"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List all reports, optionally filtered by type."""
    reports_dir = config.REPORTS_DIR
    if not reports_dir.exists():
        return {"reports": [], "total": 0}

    reports: list[dict] = []
    for entry in sorted(reports_dir.iterdir(), reverse=True):
        if not entry.is_file() or not entry.name.endswith(".md"):
            continue
        if type and not entry.name.startswith(type):
            continue

        # Extract type from filename
        # Format: <type>_<date>_<run_id>.md
        parts = entry.stem.split("_", 2)
        report_type = parts[0] if parts else "unknown"
        date_str = parts[1] if len(parts) >= 2 else ""

        # Get file stats
        stat = entry.stat()
        reports.append({
            "filename": entry.name,
            "type": report_type,
            "date": date_str,
            "size_bytes": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 1),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "url": f"/api/v1/reports/{entry.name}",
        })

        if len(reports) >= limit:
            break

    return {"reports": reports, "total": len(reports)}


@router.get("/reports/{filename}")
async def get_report(filename: str):
    """Get the full content of a report by filename."""
    # Security: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    report_path = config.REPORTS_DIR / filename
    if not report_path.exists() or not report_path.is_file():
        raise HTTPException(status_code=404, detail=f"Report '{filename}' not found")

    content = report_path.read_text(encoding="utf-8")
    return {
        "filename": filename,
        "content": content,
        "size_bytes": len(content.encode("utf-8")),
        "modified_at": datetime.fromtimestamp(report_path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


@router.get("/reports/types/summary")
async def get_report_types_summary():
    """Get a summary of report types + counts."""
    reports_dir = config.REPORTS_DIR
    if not reports_dir.exists():
        return {"types": []}

    type_counts: dict[str, dict] = {}
    for entry in reports_dir.iterdir():
        if not entry.is_file() or not entry.name.endswith(".md"):
            continue
        parts = entry.stem.split("_", 2)
        report_type = parts[0] if parts else "unknown"
        if report_type not in type_counts:
            type_counts[report_type] = {"type": report_type, "count": 0, "latest": ""}
        type_counts[report_type]["count"] += 1
        date_str = parts[1] if len(parts) >= 2 else ""
        if date_str > type_counts[report_type]["latest"]:
            type_counts[report_type]["latest"] = date_str

    return {"types": sorted(type_counts.values(), key=lambda x: -x["count"])}
