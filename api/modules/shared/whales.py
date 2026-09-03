"""Shared whale-tracking data (data-api). Used by mirror_trader; kept in shared/
so no strategy module imports another (module-architecture rule)."""
import logging
import time

import httpx

log = logging.getLogger(__name__)

DATA_API = "https://data-api.polymarket.com"


def whale_roi(wallet: str) -> float | None:
    """Capital-weighted return across the whale's CURRENT book (realized +
    unrealized) over deployed capital. None when the whale holds nothing.
    Same method the copytrader uses to gate on live-book health - a whale
    riding losers (negative live ROI) is benched even if lifetime-profitable."""
    try:
        r = httpx.get(f"{DATA_API}/positions",
                      params={"user": wallet, "limit": 200}, timeout=30)
        r.raise_for_status()
        positions = [p for p in (r.json() or [])
                     if float(p.get("initialValue") or 0) > 0]
        if not positions:
            return None
        cost = sum(float(p["initialValue"]) for p in positions)
        pnl = sum(float(p.get("realizedPnl") or 0)
                  + float(p.get("currentValue") or 0)
                  - float(p.get("initialValue") or 0) for p in positions)
        return pnl / cost if cost > 0 else None
    except Exception:
        log.exception("whale ROI fetch failed for %s", wallet[:10])
        return None


def whale_buys(wallet: str, lookback_hours: float, limit: int = 200) -> list[dict]:
    """The whale's recent BUY trades (conditionId, asset token, price, size).
    BUYS only - we mirror what they're accumulating, not their exits."""
    try:
        r = httpx.get(f"{DATA_API}/trades", params={"user": wallet, "limit": limit},
                      timeout=30)
        r.raise_for_status()
    except Exception:
        log.exception("whale trades fetch failed for %s", wallet[:10])
        return []
    cutoff = time.time() - lookback_hours * 3600
    out = []
    for t in (r.json() or []):
        if (t.get("side") or "").upper() != "BUY":
            continue
        if float(t.get("timestamp") or 0) < cutoff:
            continue
        out.append(t)
    return out
