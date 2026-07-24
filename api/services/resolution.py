"""Resolution tracker (BUILD_SPEC B6: every 30 min; Part N: per market_id).

Settles every open/closing position against Gamma's resolved outcome. Two
lookups, because resolved SPORTS game-markets get dropped from Gamma's
`condition_ids` index within hours of resolving (tweet markets stay):
  1. /markets?condition_ids=<cid>   - works for tweet-bracket markets.
  2. closed /events by series        - recovers churned sports game-markets.
Settlement is PER TOKEN: the position's own token_id is matched to the market's
outcome index, so a favorite that is outcome[1] settles correctly (the old code
always read outcome[0] and would mis-settle the away side)."""
import json
import logging

import httpx

from api.dependencies import get_supabase
from api.services import position_manager

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
SPORTS_SERIES = [1, 2, 3, 4]  # NFL/NBA/MLB/NHL - churn out of the condition index


def _is_resolved(m: dict) -> bool:
    if not m or not m.get("closed"):
        return False
    if (m.get("umaResolutionStatus") or "").lower() not in ("resolved", ""):
        return False
    return bool(m.get("outcomePrices"))


def _token_outcome(m: dict, token_id: str | None) -> float | None:
    """Our token's settled price: 1.0 won / 0.0 lost / None if unclear. Falls
    back to outcome[0] only when the token can't be located (legacy YES rows)."""
    try:
        toks = m.get("clobTokenIds")
        if isinstance(toks, str):
            toks = json.loads(toks)
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
    except (TypeError, ValueError):
        return None
    if not prices:
        return None
    idx = 0
    if token_id and toks and token_id in toks and len(toks) == len(prices):
        idx = toks.index(token_id)
    try:
        p = float(prices[idx])
    except (TypeError, ValueError, IndexError):
        return None
    if p >= 0.999:
        return 1.0
    if p <= 0.001:
        return 0.0
    return None  # ambiguous - do not settle


def _fetch_by_condition(condition_id: str) -> dict | None:
    try:
        r = httpx.get(f"{GAMMA}/markets", params={"condition_ids": condition_id},
                      timeout=20)
        r.raise_for_status()
        mk = r.json() or []
        if mk and _is_resolved(mk[0]):
            return mk[0]
    except Exception:
        log.exception("condition_ids lookup failed for %s", condition_id[:16])
    return None


def _clob_token_outcome(condition_id: str, token_id: str | None) -> float | None:
    """LAST-RESORT settlement lookup via the CLOB (2026-07-24).

    Gamma drops resolved TWEET-BRACKET markets out of /markets entirely - not just
    sports - so `condition_ids` AND `clob_token_ids` both return 0 rows and positions
    were stranded 'open' forever, meaning we booked every salvage LOSS but never
    collected a single winning $1.00 payout. The CLOB keeps them: /markets/<cid>
    returns tokens[] each with an explicit `winner` bool. Match OUR token."""
    try:
        r = httpx.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=20)
        r.raise_for_status()
        m = r.json() or {}
    except Exception:
        log.exception("clob resolution lookup failed for %s", condition_id[:16])
        return None
    if not m.get("closed"):
        return None
    toks = m.get("tokens") or []
    if not toks:
        return None
    if token_id:
        for t in toks:
            if str(t.get("token_id")) == str(token_id):
                w = t.get("winner")
                if w is True:
                    return 1.0
                if w is False:
                    return 0.0
                return None
        return None  # our token isn't in this market - do not guess
    # no token_id on the row (legacy): only settle if exactly one side won
    winners = [t for t in toks if t.get("winner") is True]
    return None if len(winners) != 1 else None


def _sports_resolved_map(series_ids: list[int]) -> dict[str, dict]:
    """conditionId -> resolved market, from recent CLOSED sports events (the
    lookup that survives a resolved game-market being dropped from the index)."""
    out: dict[str, dict] = {}
    for sid in series_ids:
        try:
            r = httpx.get(f"{GAMMA}/events", params={
                "series_id": str(sid), "closed": "true", "limit": 300,
                "order": "endDate", "ascending": "false"}, timeout=30)
            r.raise_for_status()
            for ev in (r.json() or []):
                for m in (ev.get("markets") or []):
                    cid = m.get("conditionId")
                    if cid and _is_resolved(m):
                        out[cid] = m
        except Exception:
            log.exception("sports resolved-map failed for series %s", sid)
    return out


def run_resolution_sweep() -> int:
    """Settle every open/closing position whose market has resolved. Returns
    positions settled."""
    sb = get_supabase()
    rows = (sb.table("positions").select("id,market_id,bracket,token_id")
            .in_("status", ["open", "closing"]).execute().data) or []
    settled = 0
    market_cache: dict[str, dict | None] = {}
    sports_map: dict[str, dict] | None = None
    for p in rows:
        mid = p.get("market_id") or ""
        if not mid:
            continue
        if mid not in market_cache:
            market_cache[mid] = _fetch_by_condition(mid)
        m = market_cache[mid]
        if m is None:  # churned sports market - use the closed-events map
            if sports_map is None:
                sports_map = _sports_resolved_map(SPORTS_SERIES)
            m = sports_map.get(mid)
        if m:
            price = _token_outcome(m, p.get("token_id"))
        else:
            # Gamma has dropped it entirely (tweet brackets churn too) - ask the CLOB.
            price = _clob_token_outcome(mid, p.get("token_id"))
        if price is None:
            continue
        res = position_manager.resolve_at(p["id"], price)
        if res:
            settled += 1
            log.info("RESOLVED %s %s at %.2f -> realized %.4f",
                     p.get("bracket"), mid[:12], price,
                     float(res.get("realized_pnl") or 0))
    return settled
