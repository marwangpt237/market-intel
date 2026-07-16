"""Auth + admin endpoints — API key management + audit logs."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter()


class RegisterKeyRequest(BaseModel):
    """Request to register a new API key."""
    raw_key: str = Field(..., min_length=8, description="The actual API key (min 8 chars)")
    organization: str = Field(default="default")
    role: str = Field(default="viewer", description="admin, editor, or viewer")
    rate_limit_per_hour: int = Field(default=1000, ge=1, le=100000)


@router.get("/auth/status")
async def auth_status():
    """Check if authentication is enabled."""
    from api.auth import is_auth_enabled, list_api_keys
    return {
        "auth_enabled": is_auth_enabled(),
        "registered_keys": len(list_api_keys()),
    }


@router.post("/auth/keys")
async def register_key(req: RegisterKeyRequest):
    """Register a new API key (admin only — protect this endpoint in production)."""
    from api.auth import register_api_key, is_auth_enabled
    # In production, this endpoint should require admin auth
    # For now, it's open but only works when auth is enabled
    if not is_auth_enabled():
        raise HTTPException(status_code=400, detail="Auth not enabled. Set MARKET_INTEL_AUTH_ENABLED=true")
    api_key = register_api_key(
        raw_key=req.raw_key,
        organization=req.organization,
        role=req.role,
        rate_limit_per_hour=req.rate_limit_per_hour,
    )
    return {
        "key_id": api_key.key_id,
        "organization": api_key.organization,
        "role": api_key.role,
        "rate_limit_per_hour": api_key.rate_limit_per_hour,
        "message": "Key registered. Use it as: Authorization: Bearer <your-key>",
    }


@router.get("/auth/keys")
async def list_keys():
    """List all registered API keys (without the actual key values)."""
    from api.auth import list_api_keys
    return {"keys": list_api_keys(), "total": len(list_api_keys())}


@router.delete("/auth/keys/{key_id}")
async def revoke_key(key_id: str):
    """Revoke an API key."""
    from api.auth import revoke_api_key
    if not revoke_api_key(key_id):
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found")
    return {"status": "revoked", "key_id": key_id}


@router.get("/auth/audit-log")
async def get_audit_log(limit: int = Query(default=100, ge=1, le=1000)):
    """Get recent audit log entries."""
    from api.auth import get_audit_log
    entries = get_audit_log(limit=limit)
    return {"entries": entries, "total": len(entries)}


@router.get("/auth/validate")
async def validate_current_key():
    """Validate the current API key (for testing).

    If auth is disabled, returns anonymous.
    If auth is enabled, requires a valid Bearer token.
    """
    from api.auth import is_auth_enabled
    if not is_auth_enabled():
        return {"valid": True, "anonymous": True, "message": "Auth disabled"}
    # If we got here with auth enabled, the middleware already validated
    return {"valid": True, "anonymous": False}
