"""Copytrader data fetchers (BUILD_SPEC C6). data-api has no stream for a
third-party wallet - the slow path polls /trades."""
import logging
import time

import httpx

log = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"


def whale_trades(wallet: str, lookback_hours: float, limit: int = 200) -> list[dict]:
    r = httpx.get(f"{DATA_API}/trades", params={"user": wallet, "limit": limit},
                  timeout=30)
    r.raise_for_status()
    cutoff = time.time() - lookback_hours * 3600
    return [t for t in (r.json() or []) if float(t.get("timestamp") or 0) >= cutoff]


def whale_recent_roi(wallet: str, last_n: int = 10) -> float | None:
    """Whale-performance gate input: ROI across the most recent closed
    positions (realized pnl / cost). None when unavailable (gate then
    SKIPS the whale - fail closed, F3)."""
    try:
        r = httpx.get(f"{DATA_API}/positions",
                      params={"user": wallet, "limit": 100}, timeout=30)
        r.raise_for_status()
        closed = [p for p in (r.json() or []) if float(p.get("size") or 0) == 0
                  and p.get("realizedPnl") is not None]
        closed = closed[:last_n]
        if not closed:
            return None
        pnl = sum(float(p["realizedPnl"]) for p in closed)
        cost = sum(abs(float(p.get("totalBought") or 0) * float(p.get("avgPrice") or 0))
                   for p in closed)
        return pnl / cost if cost > 0 else None
    except Exception:
        log.exception("whale ROI fetch failed")
        return None
