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


def _open_exposure(sb, module_id: str | None = None) -> tuple[float, dict[str, float]]:
    """(total open notional, per-market notional) across open positions.
    Raises on DB error - caller treats that as fail-closed."""
    q = sb.table("positions").select("market_id,size,avg_price").eq("status", "open")
    rows = (q.execute().data) or []
    per_market: dict[str, float] = {}
    total = 0.0
    for r in rows:
        n = float(r.get("size") or 0) * float(r.get("avg_price") or 0)
        total += n
        per_market[r.get("market_id") or ""] = per_market.get(r.get("market_id") or "", 0) + n
    return total, per_market


def _realized_pnl_since(sb, since: datetime) -> float | None:
    rows = (sb.table("positions").select("realized_pnl,closed_at")
            .eq("status", "closed").gte("closed_at", since.isoformat())
            .execute().data) or []
    return sum(float(r.get("realized_pnl") or 0) for r in rows)


def check(signal: Signal, breaker_tripped: bool = False) -> RiskVerdict:
    s = get_settings()

    if breaker_tripped:
        return RiskVerdict(False, "circuit_breaker")
    if signal.price <= 0 or signal.price >= 1:
        return RiskVerdict(False, f"bad_price:{signal.price}")
    if signal.size <= 0:
        return RiskVerdict(False, "bad_size")
    if not signal.token_id:
        return RiskVerdict(False, "missing_token_id")

    # SELLs bypass entry gates (edge/spread/exposure) but sized as 100% of
    # THIS position, which the exit path guarantees - not re-checked here.
    if signal.side == "SELL" or signal.is_exit:
        return RiskVerdict(True, "exit")

    # Spread check: reject when spread > tolerance OR no data (fail closed).
    if signal.spread is None or signal.best_ask is None:
        return RiskVerdict(False, "no_spread_data")
    if signal.spread > s.slippage_tolerance:
        return RiskVerdict(False, f"spread_{signal.spread:.3f}>tol_{s.slippage_tolerance}")

    # Edge floor.
    if signal.edge is None or signal.edge < s.min_edge_threshold:
        return RiskVerdict(False, f"edge_{signal.edge}<min_{s.min_edge_threshold}")

    # Kelly stake floor: skip dust bids (D4, ~0.1% of bankroll).
    if signal.notional < 0.001 * s.bankroll:
        return RiskVerdict(False, "stake_below_floor")

    try:
        sb = get_supabase()
        total, per_market = _open_exposure(sb)
        if signal.notional + per_market.get(signal.market_id, 0.0) > s.max_single_market_exposure * s.bankroll:
            return RiskVerdict(False, "single_market_cap")
        if signal.notional + total > s.max_portfolio_exposure * s.bankroll:
            return RiskVerdict(False, "portfolio_cap")

        now = datetime.now(timezone.utc)
        daily = _realized_pnl_since(sb, now - timedelta(days=1))
        if daily is not None and daily < -s.daily_loss_limit * s.bankroll:
            return RiskVerdict(False, "daily_loss_limit")
        weekly = _realized_pnl_since(sb, now - timedelta(days=7))
        if weekly is not None and weekly < -s.weekly_loss_limit * s.bankroll:
            return RiskVerdict(False, "weekly_loss_limit")
    except Exception as e:
        log.error("risk gate DB failure - failing CLOSED: %s", e)
        return RiskVerdict(False, f"db_error:{type(e).__name__}")

    return RiskVerdict(True, "ok")


def aggregate_price_ceiling_ok(existing_avg_prices: list[float], new_price: float,
                               ceiling: float | None = None) -> bool:
    """Sum of avg prices across all brackets held in one auction must stay
    under the ceiling (default 0.65): exactly one bracket wins, so sum < 1
    guarantees a winner, < 0.65 locks in edge (D4)."""
    s = get_settings()
    limit = ceiling if ceiling is not None else s.auction_aggregate_price_ceiling_floor
    return (sum(existing_avg_prices) + new_price) <= limit
