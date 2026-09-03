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
    """Whale-performance gate input (F3): capital-weighted return across the
    whale's CURRENT book.

    Fix 2026-07-08: the old version filtered /positions for size==0 (closed
    trades), but that endpoint only ever returns OPEN holdings (size>0), so
    it found nothing and returned None every cycle -> the gate benched the
    whale forever. /positions carries per-position realizedPnl + currentValue
    + initialValue, so we score the whale's live book instead: total P&L
    (realized + unrealized) over deployed capital. None only when the whale
    genuinely holds nothing (gate then benches, fail-closed)."""
    try:
        r = httpx.get(f"{DATA_API}/positions",
                      params={"user": wallet, "limit": 100}, timeout=30)
        r.raise_for_status()
        positions = [p for p in (r.json() or [])
                     if float(p.get("initialValue") or 0) > 0]
        if not positions:
            return None
        cost = sum(float(p["initialValue"]) for p in positions)
        pnl = sum(
            float(p.get("realizedPnl") or 0)
            + float(p.get("currentValue") or 0)
            - float(p.get("initialValue") or 0)
            for p in positions
        )
        return pnl / cost if cost > 0 else None
    except Exception:
        log.exception("whale ROI fetch failed")
        return None
