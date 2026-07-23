"""Healthcheck + per-module health (BUILD_SPEC I2/I4). /api/healthz MUST
stay unauthenticated: auth on it makes Railway keep stale code 'Online'."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()


@router.get("/api/healthz")
def healthz():
    return {"status": "ok", "running": True}


@router.post("/api/engine/halt")
def engine_halt(halted: bool = True, reason: str = "manual",
                x_admin_token: str | None = Header(default=None)):
    """Manual kill switch (risk-audit F5): STOP new order placement + cancel all
    resting orders. Does NOT liquidate positions (they settle normally). Token-gated
    via ADMIN_TOKEN. POST {halted:true} to engage, {halted:false} to release."""
    from api.config import get_settings
    from api.services.halt import set_halt
    token = get_settings().admin_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=403, detail="invalid or missing X-Admin-Token")
    return set_halt(halted, reason)


@router.get("/api/engine/health")
def engine_health(request: Request, module_id: str | None = None):
    """Health from REAL runtime signals (I4): TRADING = a trade in 24h,
    CYCLING = cycles flowing with no errors, STUCK = errors or no cycles."""
    from api.dependencies import get_supabase
    engine = getattr(request.app.state, "engine", None)
    sb = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    q = sb.table("trades").select("id", count="exact").gte("executed_at", since)
    if module_id:
        q = q.eq("module_id", module_id)
    trades_24h = q.execute().count or 0
    cycles = engine.cycles if engine else 0
    state = "TRADING" if trades_24h > 0 else ("CYCLING" if cycles > 0 else "STUCK")
    return {"state": state, "trades_24h": trades_24h, "cycles": cycles,
            "last_cycle_at": engine.last_cycle_at if engine else None,
            "module_id": module_id}
