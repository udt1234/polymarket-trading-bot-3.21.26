"""Copy Trading decision layer — staleness gate, 4 risk caps, sizing.

Pure-ish functions, no DB writes. The module orchestrator passes in the
trade, wallet config, and runtime state; the functions return either a
sizing dict {"action": "mirrored", ...} or a skip dict
{"action": "skipped_*", "reason": ...}.

The 4 hard risk caps (all mandatory in Phase 1):
  1. Per-wallet exposure cap   — reject BUY when wallet exposure > cap
  2. Per-trade size cap        — clip BUY order size (don't reject)
  3. Daily-loss circuit        — pause whole module when daily P&L < cap
  4. Whale performance gate    — auto-disable wallet on poor recent ROI
"""
from __future__ import annotations

from datetime import datetime, timezone


SKIP_STALE = "skipped_stale"
SKIP_DRIFT = "skipped_drift"
SKIP_CAP = "skipped_cap"
SKIP_DEDUPE = "skipped_dedupe"
SKIP_CIRCUIT = "skipped_circuit"
SKIP_PERF_GATE = "skipped_perf_gate"
SKIP_NO_POSITION = "skipped_no_position"
SKIP_ZERO_SIZE = "skipped_zero_size"
MIRRORED = "mirrored"


def is_stale(trade_ts: datetime, max_age_sec: int, now: datetime | None = None) -> bool:
    """True if the trade is older than max_age_sec from `now` (default: utc now)."""
    now = now or datetime.now(timezone.utc)
    age_sec = (now - trade_ts).total_seconds()
    return age_sec > max_age_sec


def price_drift_pct(whale_price: float, current_price: float) -> float:
    """Absolute % drift between whale's fill price and the current market."""
    if whale_price <= 0:
        return 0.0
    return abs(current_price - whale_price) / whale_price * 100.0


def is_drifted(whale_price: float, current_price: float, max_drift_pct: float) -> bool:
    """True when |current - whale| / whale > max_drift_pct.

    If current_price is 0 / unknown, we cannot evaluate drift — treat as
    NOT drifted (the order would fail later in the risk pipeline anyway).
    """
    if current_price <= 0 or whale_price <= 0:
        return False
    return price_drift_pct(whale_price, current_price) > max_drift_pct


def whale_size_pct(whale_trade_notional: float, whale_portfolio_value: float) -> float:
    """Whale's trade size as a fraction of their portfolio. Used as the
    base for our mirrored sizing. Returns 0 when portfolio value is unknown
    so the caller can fall back to per_trade_cap_pct."""
    if whale_portfolio_value <= 0 or whale_trade_notional <= 0:
        return 0.0
    return whale_trade_notional / whale_portfolio_value


def compute_buy_size_usd(
    *,
    whale_price: float,
    whale_size_shares: float,
    whale_portfolio_value: float,
    our_bankroll: float,
    wallet_weight_pct: float,
    per_trade_cap_pct: float,
    per_wallet_cap_pct: float,
    our_existing_wallet_exposure_usd: float,
    our_existing_market_notional_usd: float,
) -> tuple[float, str | None]:
    """Compute the $ size for a mirrored BUY.

    Returns (size_usd, skip_reason). size_usd > 0 means proceed.
    skip_reason is one of:
      - SKIP_CAP: per-wallet exposure cap exceeded → reject
      - SKIP_ZERO_SIZE: top-up math zeros out → skip silently
      - None: proceed with size_usd
    """
    if our_bankroll <= 0:
        return 0.0, SKIP_ZERO_SIZE
    wallet_cap_usd = our_bankroll * (per_wallet_cap_pct / 100.0)
    if our_existing_wallet_exposure_usd >= wallet_cap_usd:
        return 0.0, SKIP_CAP

    whale_notional = whale_price * whale_size_shares
    size_pct_of_their_book = whale_size_pct(whale_notional, whale_portfolio_value)
    target_usd = our_bankroll * size_pct_of_their_book * max(wallet_weight_pct, 0.0)

    # Per-trade cap: clip (don't reject).
    per_trade_cap_usd = our_bankroll * (per_trade_cap_pct / 100.0)
    target_usd = min(target_usd, per_trade_cap_usd)

    # Don't push wallet over its exposure cap.
    headroom = wallet_cap_usd - our_existing_wallet_exposure_usd
    target_usd = min(target_usd, max(headroom, 0.0))

    # Top-up rule: subtract what we already hold on this market. Skip if
    # delta is essentially zero.
    delta_usd = target_usd - max(our_existing_market_notional_usd, 0.0)
    if delta_usd <= 1.0:
        return 0.0, SKIP_ZERO_SIZE
    return delta_usd, None


def compute_sell_proportion(
    *, whale_size_sold: float, whale_position_size_before: float,
) -> float:
    """Whale sold X of Y shares — return X/Y, clamped [0, 1].

    All-or-nothing edge case (whale fully exits → size_before == size_sold)
    naturally returns 1.0 via the math.
    """
    if whale_position_size_before <= 0:
        return 0.0
    pct = whale_size_sold / whale_position_size_before
    return max(0.0, min(1.0, pct))


def daily_loss_breached(daily_pnl_usd: float, bankroll: float, circuit_pct: float) -> bool:
    """True when the day's realized P&L from copy-trading has crossed the
    daily-loss circuit-breaker threshold. circuit_pct is negative (e.g. -2.0).
    """
    if bankroll <= 0:
        return False
    threshold_usd = bankroll * (circuit_pct / 100.0)
    return daily_pnl_usd <= threshold_usd


def whale_perf_gate_breached(
    recent_copy_count: int, recent_copy_roi_pct: float | None,
    window: int, min_roi_pct: float,
) -> bool:
    """True when this wallet's last `window` copies have a rolling ROI
    below `min_roi_pct`. recent_copy_roi_pct is in percent (negative for
    losing wallets, e.g. -35.0 means the last N copies returned -35%).
    """
    if recent_copy_count < window:
        return False
    if recent_copy_roi_pct is None:
        return False
    return recent_copy_roi_pct < min_roi_pct
