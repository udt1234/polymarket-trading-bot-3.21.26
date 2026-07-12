"""FastAPI entry point (BUILD_SPEC B3).

The Polymarket proxy patch MUST be installed before any SDK / httpx-using
module is imported, so every Polymarket-bound request is transparently
routed through the Cloudflare Worker when POLYMARKET_PROXY_URL is set.
"""
import logging

from api.services.polymarket_proxy import install_httpx_proxy_patch
from api.services.net_tuning import enable_tcp_nodelay

install_httpx_proxy_patch()
enable_tcp_nodelay()

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.modules import ModuleRegistry
from api.routers import health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("api.main")

registry = ModuleRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.discover()
    log.info(
        "Boot complete - %d module(s) registered: %s",
        len(registry.all_modules()),
        ", ".join(m.name for m in registry.all_modules()) or "(none)",
    )
    from api.services.engine import Engine
    engine = Engine(registry)
    app.state.engine = engine
    engine.start()
    yield
    engine.stop()


app = FastAPI(title="Polymarket Maker Bot", lifespan=lifespan)
app.include_router(health.router)
