"""Deduplication processor — removes duplicate items by configured keys."""
from __future__ import annotations
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


class DedupProcessor(BaseProcessor):
    name = "dedup"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._keys: list[str] = (config or {}).get("keys", ["url", "title"])

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        seen: set[str] = set()
        result: list[ProcessedItem] = []

        for item in items:
            # Build a dedup key from configured fields
            parts = []
            for key in self._keys:
                val = getattr(item, key, "") or ""
                parts.append(str(val).lower().strip())
            dedup_key = "|".join(parts)

            if dedup_key in seen:
                self._logger.debug(f"Skipped duplicate: {item.title[:60]}", extra={"dedup_key": dedup_key})
                continue

            seen.add(dedup_key)
            item.dedup_key = dedup_key
            result.append(item)

        removed = len(items) - len(result)
        self._logger.info(f"Dedup: removed {removed} duplicates", extra={"input": len(items), "output": len(result), "removed": removed})
        return result
