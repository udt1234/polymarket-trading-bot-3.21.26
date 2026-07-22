"""The risk gate (BUILD_SPEC G1). Every order passes through check().

ALL checks FAIL CLOSED: any DB error, missing price, or missing data
rejects the signal. Empty daily P&L history = "no constraint", never
"block all" (that distinction matters: no-data-about-losses is fine,
no-data-about-the-market is not).
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


@dataclass
class Signal:
    module_id: str
    market_id: str          # condition id
    bracket: str
    side: str               # BUY | SELL
    price: float            # our limit price
    size: float             # shares
    token_id: str
    fair_value: float | None = None
    edge: float | None = None
    auction_slug: str = ""
    spread: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    is_exit: bool = False   # exits bypass entry gates (G1), respect breaker
    metadata: dict = field(default_factory=dict)

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass
class RiskVerdict:
    approved: bool
    reason: str = ""


def _meta_float(signal: "Signal", key: str, default: float) -> float:
    """Read a numeric per-strategy gate override from signal.metadata; fall back
    to the global default when absent or malformed (fail safe = the stricter
    global value).

    Overrides may only LOOSEN toward 0 (income/copy strategies opt out of the
    directional-edge floor), never negative and never tighter than the global.
    Clamped to [0, default] so a careless/hostile module cannot set a negative
    floor or an absurd tolerance to bypass the intended gate."""
    try:
        v = (signal.metadata or {}).get(key)
        if v is None:
            return default
        return max(0.0, min(float(v), default))
    except (TypeError, ValueError):
        return default


def _open_exposure(sb, module_id: str | None = None) -> tuple[float, dict[str, float]]:
    """(total notional, per-market notional) across open positions PLUS
    resting/unconfirmed BUY orders - a submitted order commits collateral
    before any fill confirms (E6: count unconfirmed exposure). Raises on
    DB error - caller treats that as fail-closed."""
    per_market: dict[str, float] = {}
    total = 0.0
    rows = (sb.table("positions").select("market_id,size,avg_price")
            .in_("status", ["open", "closing"]).execute().data) or []
    for r in rows:
        n = float(r.get("size") or 0) * float(r.get("avg_price") or 0)
        total += n
        per_market[r.get("market_id") or ""] = per_market.get(r.get("market_id") or "", 0) + n
    orders = (sb.table("orders").select("market_id,size,price")
              .eq("side", "BUY")
              .in_("status", ["submitted", "open", "partially_filled"])
              .execute().data) or []
    for o in orders:
        n = float(o.get("size") or 0) * float(o.get("price") or 0)
        total += n
        per_market[o.get("market_id") or ""] = per_market.get(o.get("market_id") or "", 0) + n
    return total, per_market


def _correlated_exposure(sb, corr_key: str) -> float:
    """Open + resting-BUY notional in one correlated bucket. The bucket key is the
    auction slug when a signal carries one, else the market_id/condition_id. Since
    every bracket of one auction shares that condition_id, matching on market_id ==
    corr_key captures the whole correlated set for tweet markets; slug-tagged rows
    (metadata.auction_slug) are also matched so cross-market correlated groups work.
    Raises on DB error -> caller fails closed."""
    if not corr_key:
        return 0.0
    total = 0.0
    pos = (sb.table("positions").select("market_id,size,avg_price,metadata")
           .in_("status", ["open", "closing"]).execute().data) or []
    for r in pos:
        if r.get("market_id") == corr_key or (r.get("metadata") or {}).get("auction_slug") == corr_key:
            total += float(r.get("size") or 0) * float(r.get("avg_price") or 0)
    orders = (sb.table("orders").select("market_id,size,price,metadata")
              .eq("side", "BUY")
              .in_("status", ["submitted", "open", "partially_filled"]).execute().data) or []
    for o in orders:
        if o.get("market_id") == corr_key or (o.get("metadata") or {}).get("auction_slug") == corr_key:
            total += float(o.get("size") or 0) * float(o.get("price") or 0)
    return total


def _realized_pnl_since(sb, since: datetime) -> float | None:
    rows = (sb.table("positions").select("realized_pnl,closed_at")
            .eq("status", "closed").gte("closed_at", since.isoformat())
            .execute().data) or []
    return sum(float(r.get("realized_pnl") or 0) for r in rows)


def check(signal: Signal, breaker_tripped: bool = False) -> RiskVerdict:
    s = get_settings()

    if signal.price <= 0 or signal.price >= 1:
        return RiskVerdict(False, f"bad_price:{signal.price}")
    if signal.size <= 0:
        return RiskVerdict(False, "bad_size")
    if not signal.token_id:
        return RiskVerdict(False, "missing_token_id")

    # Exits FIRST, before the breaker (E8/G4): the breaker pauses new
    # ENTRIES; exits keep firing during a cooldown. SELLs bypass entry
    # gates and are sized as 100% of THIS position by the exit path.
    if signal.side == "SELL" or signal.is_exit:
        return RiskVerdict(True, "exit")

    if breaker_tripped:
        return RiskVerdict(False, "circuit_breaker")

    # Per-strategy gate overrides (G1): maker/income strategies do not earn a
    # directional EDGE (LP rewards = rebates; mirror = copying a whale), so the
    # 2% directional-edge floor is the wrong test for them. A module opts in by
    # setting metadata["min_edge"] / metadata["spread_tol"]; everything else uses
    # the global defaults. Overrides may only LOOSEN toward 0 for these income
    # strategies, never tighten silently - they are explicit per-module knobs.
    min_edge = _meta_float(signal, "min_edge", s.min_edge_threshold)
    spread_tol = _meta_float(signal, "spread_tol", s.slippage_tolerance)

    # Spread check: reject when spread > tolerance OR no data (fail closed).
    if signal.spread is None or signal.best_ask is None:
        return RiskVerdict(False, "no_spread_data")
    if signal.spread > spread_tol:
        return RiskVerdict(False, f"spread_{signal.spread:.3f}>tol_{spread_tol}")

    # Edge floor.
    if signal.edge is None or signal.edge < min_edge:
        return RiskVerdict(False, f"edge_{signal.edge}<min_{min_edge}")

    # Kelly stake floor: skip dust bids (D4, ~0.1% of bankroll).
    if signal.notional < 0.001 * s.bankroll:
        return RiskVerdict(False, "stake_below_floor")

    try:
        sb = get_supabase()

        # Duplicate-signal guard: never stack a second resting BUY on the
        # same (module, market, bracket).
        dup = (sb.table("orders").select("id", count="exact")
               .eq("module_id", signal.module_id).eq("market_id", signal.market_id)
               .eq("bracket", signal.bracket).eq("side", "BUY")
               .in_("status", ["submitted", "open", "partially_filled"])
               .execute().count) or 0
        if dup:
            return RiskVerdict(False, "duplicate_resting_order")

        total, per_market = _open_exposure(sb)
        if signal.notional + per_market.get(signal.market_id, 0.0) > s.max_single_market_exposure * s.bankroll:
            return RiskVerdict(False, "single_market_cap")
        # Correlated-bucket cap (stated non-negotiable, was declared but unenforced,
        # risk-audit 2026-07-22). All brackets of ONE auction are perfectly
        # correlated - exactly one wins - so exposure to a single auction (keyed by
        # slug, falling back to market_id/condition_id) is bounded separately and
        # tighter than the whole portfolio. For a tweet market this equals the
        # single-market cap; it additionally bounds any strategy that could stack
        # correlated brackets across the same underlying event.
        corr_key = signal.auction_slug or signal.market_id
        corr_now = _correlated_exposure(sb, corr_key)
        if signal.notional + corr_now > s.max_correlated_exposure * s.bankroll:
            return RiskVerdict(False, "correlated_cap")
        if signal.notional + total > s.max_portfolio_exposure * s.bankroll:
            return RiskVerdict(False, "portfolio_cap")

        now = datetime.now(timezone.utc)
        daily = _realized_pnl_since(sb, now - timedelta(days=1))
        if daily is not None and daily < -s.daily_loss_limit * s.bankroll:
            return RiskVerdict(False, "daily_loss_limit")
        weekly = _realized_pnl_since(sb, now - timedelta(days=7))
        if weekly is not None and weekly < -s.weekly_loss_limit * s.bankroll:
            return RiskVerdict(False, "weekly_loss_limit")
        if _drawdown_exceeded(sb, s):
            return RiskVerdict(False, "max_drawdown")
    except Exception as e:
        log.error("risk gate DB failure - failing CLOSED: %s", e)
        return RiskVerdict(False, f"db_error:{type(e).__name__}")

    # Depth check LAST (one live book fetch): reject when our order is
    # more than 30% of the visible book, or the book is unreadable/empty
    # (refuse to trade empty books - fail closed).
    depth = _book_depth_shares(signal.token_id)
    if depth is None or depth <= 0:
        return RiskVerdict(False, "no_depth_data")
    if signal.size > s.max_book_depth_fraction * depth:
        return RiskVerdict(False, f"depth_{signal.size:.0f}>{s.max_book_depth_fraction:.0%}_of_{depth:.0f}")

    return RiskVerdict(True, "ok")


def _drawdown_exceeded(sb, s) -> bool:
    """Equity = bankroll + all-time realized P&L. Track the peak in the
    settings table; block entries once equity falls max_drawdown below it."""
    rows = (sb.table("positions").select("realized_pnl").eq("status", "closed")
            .execute().data) or []
    equity = s.bankroll + sum(float(r.get("realized_pnl") or 0) for r in rows)
    res = sb.table("settings").select("value").eq("key", "equity_peak").limit(1).execute()
    peak = float((res.data[0]["value"] or {}).get("peak", 0)) if res.data else 0.0
    if equity > peak:
        sb.table("settings").upsert({"key": "equity_peak",
                                     "value": {"peak": equity}}).execute()
        return False
    return equity < peak * (1 - s.max_drawdown)


def _book_depth_shares(token_id: str) -> float | None:
    """Total visible resting size (both sides) from the CLOB book. None on
    any failure (caller fails closed)."""
    import httpx
    from api.services.polymarket_proxy import clob_base, proxy_headers
    try:
        r = httpx.get(f"{clob_base()}/book", params={"token_id": token_id},
                      headers=proxy_headers(), timeout=10)
        r.raise_for_status()
        book = r.json() or {}
        return (sum(float(x.get("size") or 0) for x in book.get("bids") or [])
                + sum(float(x.get("size") or 0) for x in book.get("asks") or []))
    except Exception:
        log.exception("book depth fetch failed for %s", token_id[:16])
        return None


def aggregate_price_ceiling_ok(existing_avg_prices: list[float], new_price: float,
                               ceiling: float | None = None) -> bool:
    """Sum of avg prices across all brackets held in one auction must stay
    under the ceiling (default 0.65): exactly one bracket wins, so sum < 1
    guarantees a winner, < 0.65 locks in edge (D4)."""
    s = get_settings()
    limit = ceiling if ceiling is not None else s.auction_aggregate_price_ceiling_floor
    return (sum(existing_avg_prices) + new_price) <= limit
