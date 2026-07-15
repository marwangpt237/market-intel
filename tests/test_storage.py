"""Unit tests for JSON storage."""
import sys
import os
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage.json_store import JSONStorage


def test_save_and_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = JSONStorage({"path": tmpdir, "versioning": True})
        items = [
            {"id": "1", "title": "Test 1", "source": "test"},
            {"id": "2", "title": "Test 2", "source": "test"},
        ]
        filepath = storage.save(items, "run_test_123")
        assert os.path.exists(filepath)

        # Load recent
        loaded = storage.load_recent(days=1)
        assert len(loaded) == 2
        assert loaded[0]["title"] == "Test 1"


def test_latest_file_updated():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = JSONStorage({"path": tmpdir, "versioning": True})
        storage.save([{"id": "1", "title": "First"}], "run_1")
        storage.save([{"id": "2", "title": "Second"}], "run_2")

        latest_path = os.path.join(tmpdir, "collection_latest.json")
        with open(latest_path) as f:
            data = json.load(f)
        assert data["items"][0]["title"] == "Second"
