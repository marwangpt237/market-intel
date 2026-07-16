"""Tests for Phase 6+7 — service mode + auth."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import app
    return TestClient(app)


# ─── Service mode (Phase 6) ────────────────────────────────────────────

def test_service_script_exists():
    """service.py should exist and be importable."""
    from pathlib import Path
    service_path = Path(__file__).parent.parent / "service.py"
    assert service_path.exists()


def test_service_script_has_main():
    """service.py should have a main() function."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("service", str(Path(__file__).parent.parent / "service.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "main")


# ─── Auth (Phase 7) ────────────────────────────────────────────────────

def test_auth_disabled_by_default():
    from api.auth import is_auth_enabled
    # Should be disabled by default (no env var set in test)
    old = os.environ.get("MARKET_INTEL_AUTH_ENABLED")
    os.environ.pop("MARKET_INTEL_AUTH_ENABLED", None)
    assert is_auth_enabled() is False
    if old:
        os.environ["MARKET_INTEL_AUTH_ENABLED"] = old


def test_auth_enabled_via_env():
    from api.auth import is_auth_enabled
    old = os.environ.get("MARKET_INTEL_AUTH_ENABLED")
    os.environ["MARKET_INTEL_AUTH_ENABLED"] = "true"
    assert is_auth_enabled() is True
    if old:
        os.environ["MARKET_INTEL_AUTH_ENABLED"] = old
    else:
        os.environ.pop("MARKET_INTEL_AUTH_ENABLED", None)


def test_register_and_validate_api_key():
    from api.auth import register_api_key, validate_api_key
    api_key = register_api_key(raw_key="test-key-12345", organization="test_org", role="admin")
    assert api_key.organization == "test_org"
    assert api_key.role == "admin"

    # Validate
    validated = validate_api_key("test-key-12345")
    assert validated is not None
    assert validated.key_id == api_key.key_id


def test_validate_invalid_key():
    from api.auth import validate_api_key
    assert validate_api_key("nonexistent-key") is None
    assert validate_api_key("") is None


def test_revoke_api_key():
    from api.auth import register_api_key, revoke_api_key, validate_api_key
    api_key = register_api_key(raw_key="revoke-me-67890")
    assert validate_api_key("revoke-me-67890") is not None

    revoked = revoke_api_key(api_key.key_id)
    assert revoked is True

    assert validate_api_key("revoke-me-67890") is None


def test_rate_limiting():
    from api.auth import register_api_key, check_rate_limit, APIKey
    api_key = register_api_key(raw_key="rate-test-key", rate_limit_per_hour=3)

    # First 3 should pass
    assert check_rate_limit(api_key) is True
    assert check_rate_limit(api_key) is True
    assert check_rate_limit(api_key) is True
    # 4th should fail
    assert check_rate_limit(api_key) is False


def test_list_api_keys():
    from api.auth import register_api_key, list_api_keys
    register_api_key(raw_key="list-test-1", organization="org1")
    keys = list_api_keys()
    assert len(keys) >= 1
    # Should not contain the raw key
    for k in keys:
        assert "raw_key" not in k
        assert "key_hash" not in k


def test_audit_log():
    from api.auth import record_audit_log, get_audit_log
    record_audit_log(
        api_key_id="test_key",
        organization="test_org",
        method="GET",
        path="/api/v1/test",
        status_code=200,
        duration_ms=42.5,
    )
    entries = get_audit_log(limit=10)
    assert len(entries) >= 1
    assert entries[0]["method"] == "GET"
    assert entries[0]["status_code"] == 200


# ─── Auth API endpoints ────────────────────────────────────────────────

def test_auth_status_endpoint(client):
    response = client.get("/api/v1/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert "auth_enabled" in data
    assert "registered_keys" in data


def test_auth_register_key_when_disabled(client):
    """Should fail when auth is disabled."""
    response = client.post("/api/v1/auth/keys", json={
        "raw_key": "test-key-for-api",
        "organization": "test",
    })
    assert response.status_code == 400


def test_auth_list_keys(client):
    response = client.get("/api/v1/auth/keys")
    assert response.status_code == 200
    data = response.json()
    assert "keys" in data


def test_auth_audit_log(client):
    response = client.get("/api/v1/auth/audit-log")
    assert response.status_code == 200
    data = response.json()
    assert "entries" in data


def test_auth_validate(client):
    response = client.get("/api/v1/auth/validate")
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True


def test_revoke_nonexistent_key(client):
    response = client.delete("/api/v1/auth/keys/nonexistent")
    assert response.status_code == 404
