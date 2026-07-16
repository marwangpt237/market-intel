"""
Authentication — API key-based auth for production.

Phase 7 of productization.

Features:
  - API key authentication (Bearer token)
  - Organization-scoped keys
  - Rate limiting per key
  - Audit logging of all authenticated requests
  - Optional auth (disabled in development, enabled in production)

Usage:
  # Development (auth disabled)
  MARKET_INTEL_AUTH_ENABLED=false python service.py

  # Production (auth enabled)
  MARKET_INTEL_AUTH_ENABLED=true
  MARKET_INTEL_API_KEYS=key1:org1,key2:org2
  python service.py

  # Or via API key file
  MARKET_INTEL_API_KEYS_FILE=/path/to/keys.json
"""
from __future__ import annotations

import os
import json
import time
import hashlib
import threading
from datetime import datetime, timezone
from typing import Any
from fastapi import Request, Response, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field


# ─── Models ────────────────────────────────────────────────────────────


class APIKey(BaseModel):
    """An API key with associated organization + role."""
    key_id: str = Field(..., description="Unique key identifier")
    key_hash: str = Field(..., description="SHA256 hash of the actual key (never store raw)")
    organization: str = Field(..., description="Organization this key belongs to")
    role: str = Field(default="viewer", description="Role: admin, editor, viewer")
    rate_limit_per_hour: int = Field(default=1000, description="Max requests per hour")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used: str | None = None
    is_active: bool = True


class AuditLogEntry(BaseModel):
    """A single audit log entry."""
    timestamp: str
    api_key_id: str | None
    organization: str | None
    method: str
    path: str
    status_code: int
    duration_ms: float
    ip_address: str | None = None
    user_agent: str | None = None


# ─── In-memory stores (Phase 7 minimal — Phase 8 would persist to DB) ──

_api_keys: dict[str, APIKey] = {}  # key_id → APIKey
_api_keys_by_hash: dict[str, str] = {}  # key_hash → key_id
_rate_limits: dict[str, list[float]] = {}  # key_id → list of request timestamps
_audit_log: list[dict] = []
_audit_lock = threading.Lock()
_rate_lock = threading.Lock()


def _hash_key(key: str) -> str:
    """Hash an API key with SHA256."""
    return hashlib.sha256(key.encode()).hexdigest()


def _generate_key_id() -> str:
    """Generate a unique key ID."""
    import uuid
    return f"key_{uuid.uuid4().hex[:12]}"


# ─── Public API ────────────────────────────────────────────────────────


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    return os.environ.get("MARKET_INTEL_AUTH_ENABLED", "false").lower() == "true"


def load_keys_from_env() -> None:
    """Load API keys from environment variables.

    Format 1: MARKET_INTEL_API_KEYS=key1:org1,key2:org2
    Format 2: MARKET_INTEL_API_KEYS_FILE=/path/to/keys.json

    JSON file format:
    [
      {"key": "actual-key-string", "organization": "acme", "role": "admin", "rate_limit_per_hour": 5000},
      ...
    ]
    """
    keys_file = os.environ.get("MARKET_INTEL_API_KEYS_FILE")
    if keys_file and os.path.exists(keys_file):
        with open(keys_file) as f:
            keys_data = json.load(f)
        for kd in keys_data:
            raw_key = kd.get("key", "")
            if raw_key:
                register_api_key(
                    raw_key=raw_key,
                    organization=kd.get("organization", "default"),
                    role=kd.get("role", "viewer"),
                    rate_limit_per_hour=kd.get("rate_limit_per_hour", 1000),
                )
        return

    keys_env = os.environ.get("MARKET_INTEL_API_KEYS", "")
    if keys_env:
        for pair in keys_env.split(","):
            if ":" in pair:
                key, org = pair.split(":", 1)
                register_api_key(raw_key=key.strip(), organization=org.strip())


def register_api_key(
    raw_key: str,
    organization: str = "default",
    role: str = "viewer",
    rate_limit_per_hour: int = 1000,
) -> APIKey:
    """Register a new API key. Returns the APIKey object (without raw key)."""
    key_id = _generate_key_id()
    key_hash = _hash_key(raw_key)
    api_key = APIKey(
        key_id=key_id,
        key_hash=key_hash,
        organization=organization,
        role=role,
        rate_limit_per_hour=rate_limit_per_hour,
    )
    _api_keys[key_id] = api_key
    _api_keys_by_hash[key_hash] = key_id
    return api_key


def revoke_api_key(key_id: str) -> bool:
    """Revoke an API key."""
    if key_id in _api_keys:
        api_key = _api_keys[key_id]
        api_key.is_active = False
        _api_keys_by_hash.pop(api_key.key_hash, None)
        return True
    return False


def validate_api_key(raw_key: str) -> APIKey | None:
    """Validate an API key. Returns the APIKey if valid, None otherwise."""
    if not raw_key:
        return None
    key_hash = _hash_key(raw_key)
    key_id = _api_keys_by_hash.get(key_hash)
    if key_id is None:
        return None
    api_key = _api_keys.get(key_id)
    if api_key is None or not api_key.is_active:
        return None
    # Update last_used
    api_key.last_used = datetime.now(timezone.utc).isoformat()
    return api_key


def check_rate_limit(api_key: APIKey) -> bool:
    """Check if an API key is within its rate limit. Returns True if allowed."""
    now = time.time()
    hour_ago = now - 3600

    with _rate_lock:
        if api_key.key_id not in _rate_limits:
            _rate_limits[api_key.key_id] = []
        # Remove timestamps older than 1 hour
        _rate_limits[api_key.key_id] = [
            ts for ts in _rate_limits[api_key.key_id] if ts > hour_ago
        ]
        # Check limit
        if len(_rate_limits[api_key.key_id]) >= api_key.rate_limit_per_hour:
            return False
        # Record this request
        _rate_limits[api_key.key_id].append(now)
        return True


def record_audit_log(
    api_key_id: str | None,
    organization: str | None,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Record an audit log entry."""
    entry = AuditLogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        api_key_id=api_key_id,
        organization=organization,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    with _audit_lock:
        _audit_log.append(entry.model_dump())
        # Cap at 10,000 entries (Phase 8 would persist to DB)
        if len(_audit_log) > 10000:
            _audit_log.pop(0)


def get_audit_log(limit: int = 100) -> list[dict]:
    """Get recent audit log entries."""
    with _audit_lock:
        return list(reversed(_audit_log[-limit:]))


def list_api_keys() -> list[dict]:
    """List all registered API keys (without hashes)."""
    return [
        {
            "key_id": k.key_id,
            "organization": k.organization,
            "role": k.role,
            "rate_limit_per_hour": k.rate_limit_per_hour,
            "created_at": k.created_at,
            "last_used": k.last_used,
            "is_active": k.is_active,
        }
        for k in _api_keys.values()
    ]


# ─── FastAPI dependency ────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


async def get_current_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> APIKey | None:
    """FastAPI dependency: validate API key from Bearer token.

    If auth is disabled, returns None (no key required).
    If auth is enabled but no/invalid key, raises 401.
    """
    if not is_auth_enabled():
        return None  # Auth disabled — open access

    if credentials is None:
        raise HTTPException(status_code=401, detail="API key required (Bearer token)")

    api_key = validate_api_key(credentials.credentials)
    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not check_rate_limit(api_key):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return api_key
