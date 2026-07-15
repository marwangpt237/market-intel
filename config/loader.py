"""
YAML configuration loader.

Loads config.yaml from the project root (or a custom path) and
provides typed access to configuration sections.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class Config:
    """Wraps a dict and provides typed access to sections."""

    def __init__(self, data: dict):
        self._data = data

    def get(self, *keys: str, default: Any = None) -> Any:
        """Nested key access: config.get('collectors', 'reddit', 'enabled')."""
        current = self._data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key)
            if current is None:
                return default
        return current

    @property
    def general(self) -> dict:
        return self._data.get("general", {})

    @property
    def collectors(self) -> dict:
        return self._data.get("collectors", {})

    @property
    def processors(self) -> dict:
        return self._data.get("processors", {})

    @property
    def storage(self) -> dict:
        return self._data.get("storage", {})

    @property
    def reports(self) -> dict:
        return self._data.get("reports", {})

    @property
    def retry(self) -> dict:
        return self._data.get("retry", {})

    def to_dict(self) -> dict:
        return self._data


def load_config(path: str = "config.yaml") -> Config:
    """Load configuration from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(data or {})
