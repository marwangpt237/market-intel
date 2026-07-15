"""Versioned JSON file storage."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from core.logger import get_logger
from storage.base import BaseStorage


class JSONStorage(BaseStorage):
    name = "json"

    def __init__(self, config: dict):
        super().__init__(config)
        self._base_path = Path(config.get("path", "data/"))
        self._versioning: bool = config.get("versioning", True)
        self._retention_days: int = config.get("retention_days", 90)

    def save(self, items: list[dict], run_id: str) -> str:
        """Save items to a versioned JSON file. Returns the file path."""
        self._base_path.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        if self._versioning:
            filename = f"collection_{date_str}_{time_str}_{run_id[:8]}.json"
        else:
            filename = "collection_latest.json"

        filepath = self._base_path / filename

        output = {
            "run_id": run_id,
            "collected_at": now.isoformat(),
            "total_items": len(items),
            "items": items,
        }

        filepath.write_text(json.dumps(output, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

        # Also save/update the "latest" file
        latest_path = self._base_path / "collection_latest.json"
        latest_path.write_text(json.dumps(output, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

        self._logger.info(f"Saved {len(items)} items to {filepath}", extra={"file": str(filepath), "items": len(items)})

        # Clean up old files
        self._cleanup_old_files()

        return str(filepath)

    def load_recent(self, days: int = 7) -> list[dict]:
        """Load items from the last N days."""
        all_items: list[dict] = []
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)

        for filepath in sorted(self._base_path.glob("collection_*.json")):
            if filepath.name == "collection_latest.json":
                continue
            try:
                stat = filepath.stat()
                if stat.st_mtime < cutoff:
                    continue
                data = json.loads(filepath.read_text(encoding="utf-8"))
                all_items.extend(data.get("items", []))
            except Exception as e:
                self._logger.warning(f"Failed to load {filepath}: {e}")

        self._logger.info(f"Loaded {len(all_items)} items from last {days} days")
        return all_items

    def _cleanup_old_files(self) -> None:
        """Delete files older than retention_days."""
        cutoff = datetime.now(timezone.utc).timestamp() - (self._retention_days * 86400)
        deleted = 0

        for filepath in self._base_path.glob("collection_*.json"):
            if filepath.name == "collection_latest.json":
                continue
            try:
                if filepath.stat().st_mtime < cutoff:
                    filepath.unlink()
                    deleted += 1
            except Exception:
                pass

        if deleted:
            self._logger.info(f"Cleaned up {deleted} old files", extra={"deleted": deleted})
