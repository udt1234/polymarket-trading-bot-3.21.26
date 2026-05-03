import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
from api.config import get_settings
from api.dependencies import get_supabase
from api.middleware import require_auth
from api.routers import auth, dashboard, modules, portfolio, trades, analytics, logs, settings as settings_router, data_explorer
from api.routers.backtest import router as backtest_router
from api.services.engine import engine
from api.services.snapshots import start_snapshot_scheduler, stop_snapshot_scheduler
from api.ws.feeds import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
        engine.start(interval=settings.default_interval)
        start_snapshot_scheduler()
    except Exception as e:
        logging.error(f"Startup error (non-fatal): {e}")
    yield
    try:
        engine.stop()
        stop_snapshot_scheduler()
    except Exception:
        pass


app = FastAPI(title="PolyMarket Bot", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_auth)])
app.include_router(modules.router, prefix="/api/modules", tags=["modules"], dependencies=[Depends(require_auth)])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"], dependencies=[Depends(require_auth)])
app.include_router(trades.router, prefix="/api/trades", tags=["trades"], dependencies=[Depends(require_auth)])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(require_auth)])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"], dependencies=[Depends(require_auth)])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])
app.include_router(backtest_router, prefix="/api/backtest", tags=["backtest"], dependencies=[Depends(require_auth)])
app.include_router(data_explorer.router, prefix="/api/data-explorer", tags=["data-explorer"], dependencies=[Depends(require_auth)])
app.include_router(ws_router)


@app.get("/api/healthz")
async def healthz():
    """Unauthenticated liveness probe for Railway/load-balancer healthchecks.

    Returns 200 with minimal info as long as the FastAPI process is responding.
    Does NOT touch Supabase or any downstream service so transient outages
    don't cause Railway to bounce the container.

    KNOWN ISSUE that prompted this endpoint: PR #18 (2026-04-27) added
    `Depends(require_auth)` to /api/engine/status, which silently broke the
    Railway healthcheck path defined in railway.toml. Every deploy from then
    until 2026-05-02 failed the healthcheck with 401 and Railway kept the
    pre-PR-#18 container running — so 7 merged PRs (CNN archive, exit fixes,
    config validation, etc.) were not actually live. Lesson: healthcheck
    endpoints must remain unauthenticated AND there must be an integration
    test that hits the literal path Railway calls.
    """
    return {"status": "ok", "running": engine._running}


@app.get("/api/engine/status", dependencies=[Depends(require_auth)])
async def engine_status():
    return engine.status


@app.get("/api/engine/health", dependencies=[Depends(require_auth)])
async def engine_health():
    """Bot health snapshot for the dashboard banner.
    Returns one of: trading | watching | paused | killed
    """
    return engine.health


@app.post("/api/engine/stop", dependencies=[Depends(require_auth)])
async def engine_stop():
    sb = get_supabase()
    engine.stop()
    from datetime import datetime as _dt, timezone as _tz
    now_iso = _dt.now(_tz.utc).isoformat()
    open_positions = sb.table("positions").select("id,module_id,bracket,size,avg_price").eq("status", "open").execute()
    closed_count = 0
    for pos in (open_positions.data or []):
        sb.table("positions").update({
            "status": "closed",
            "exit_price": pos["avg_price"],
            "realized_pnl": 0,
            "closed_at": now_iso,
        }).eq("id", pos["id"]).execute()
        closed_count += 1
    sb.table("logs").insert({
        "log_type": "system",
        "severity": "critical",
        "message": f"GLOBAL KILL SWITCH: engine stopped, {closed_count} positions closed",
        "metadata": {"action": "global_kill", "positions_closed": closed_count},
    }).execute()
    try:
        from api.services.alerts import notify_bot_paused
        await notify_bot_paused(
            reason="Manual global kill switch",
            scope="engine",
            details={"positions_closed": closed_count},
        )
    except Exception:
        pass
    return {"ok": True, "engine_stopped": True, "positions_closed": closed_count}


@app.post("/api/engine/start", dependencies=[Depends(require_auth)])
async def engine_start():
    settings = get_settings()
    engine.start(interval=settings.default_interval)
    return {"ok": True, "status": engine.status}
