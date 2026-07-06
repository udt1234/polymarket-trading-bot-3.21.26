"""Resolution tracker (BUILD_SPEC B6: every 30 min; Part N: per market_id).

Groups open positions by market_id (condition id) and settles each against
Gamma's resolved outcome: winning bracket YES -> 1.00, losers -> 0.00.
Resolution is per-MARKET, never per-module (rolling auctions have no
module-level resolution date - the old bot's realized P&L stayed $0)."""
import json
import logging

import httpx

from api.dependencies import get_supabase
from api.services import position_manager

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"


def _resolved_price(condition_id: str) -> float | None:
    """1.0 / 0.0 for a resolved market's YES side, None while unresolved."""
    try:
        r = httpx.get(f"{GAMMA}/markets", params={"condition_ids": condition_id},
                      timeout=20)
        r.raise_for_status()
        markets = r.json() or []
        if not markets:
            return None
        m = markets[0]
        if not m.get("closed"):
            return None
        if (m.get("umaResolutionStatus") or "").lower() not in ("resolved", ""):
            return None
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not prices:
            return None
        yes = float(prices[0])
        if yes >= 0.999:
            return 1.0
        if yes <= 0.001:
            return 0.0
        return None  # ambiguous - do not settle
    except Exception:
        log.exception("resolution check failed for %s", condition_id[:16])
        return None


def run_resolution_sweep() -> int:
    """Settle every open/closing position whose market has resolved.
    Returns positions settled."""
    sb = get_supabase()
    rows = (sb.table("positions").select("id,market_id,bracket")
            .in_("status", ["open", "closing"]).execute().data) or []
    by_market: dict[str, list[dict]] = {}
    for r in rows:
        by_market.setdefault(r.get("market_id") or "", []).append(r)
    settled = 0
    for market_id, positions in by_market.items():
        if not market_id:
            continue
        price = _resolved_price(market_id)
        if price is None:
            continue
        for p in positions:
            res = position_manager.resolve_at(p["id"], price)
            if res:
                settled += 1
                log.info("RESOLVED %s %s at %.2f -> realized %.4f",
                         p["bracket"], market_id[:12], price,
                         float(res.get("realized_pnl") or 0))
    return settled
