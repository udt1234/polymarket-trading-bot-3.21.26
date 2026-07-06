"""Healthcheck. MUST stay unauthenticated (BUILD_SPEC I2): auth on this
endpoint makes Railway keep stale code 'Online' for days."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/healthz")
def healthz():
    return {"status": "ok", "running": True}
