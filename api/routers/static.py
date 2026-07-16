"""Static file serving — dashboard UI."""
from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from api.config import config

router = APIRouter()

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<html><body><h1>Dashboard not built yet</h1></body></html>"


@router.get("/dashboard/{path:path}", response_class=HTMLResponse)
async def dashboard_assets(path: str):
    """Serve dashboard assets (CSS, JS)."""
    file_path = STATIC_DIR / path
    if file_path.exists() and file_path.is_file():
        return file_path.read_text(encoding="utf-8")
    # Fall back to index.html for SPA routing
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<html><body><h1>Not found</h1></body></html>", 404
