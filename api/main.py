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
from api.middleware import require_auth
from api.routers import auth, dashboard, modules, portfolio, trades, analytics, logs, settings as settings_router
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
app.include_router(ws_router)


@app.get("/api/engine/status")
async def engine_status():
    return engine.status
