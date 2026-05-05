"""HOLD / SELL / SELL-NOW classifier for spike_trading.

This is the heatmap as code. Source: 51 historical Elon 2-day <40 auctions
(see _DataMetricPulls/elon_2day_analysis/hold_signal_grid.csv).

Inputs are the current state of an open position. Output is one of four
decisions, in priority order:

  SELL-NOW   — bracket is dying, dump immediately at market.
               Triggers from cfg["sellnow_grid"]. ≥70% of historicals in
               these states ended ≤1¢.
  HOLD       — clear winner trajectory; cancel any active sell limits so
               we don't accidentally exit too early.
               Single state cell: tweets ≤ hold_max AND hours ≥ hold_min
               (median end_price was 99¢ historically, 2.4× upside).
  HOLD-LIGHT — likely-winner, but not a sure thing. Keep ladder limits but
               don't bail on a paper loss.
  SELL       — default; let the limit-sell ladder do its thing organically.

Order matters: SELL-NOW always wins, then HOLD, then HOLD-LIGHT, else SELL.
"""
from dataclasses import dataclass


@dataclass
class PositionState:
    """Snapshot of where an open position sits in the heatmap."""
    cum_tweets: int
    hours_to_close: float
    current_price: float          # latest observed YES price
    entry_price: float            # cost basis
    pnl_pct: float                # (current - entry) / entry × 100


def classify_decision(state: PositionState, cfg: dict) -> str:
    """Return one of: SELL-NOW, HOLD, HOLD-LIGHT, SELL.

    Priority:
      1. SELL-NOW  (dying bracket — always wins)
      2. HOLD      (clear winner — overrides default sells)
      3. HOLD-LIGHT (likely winner — softens sells)
      4. SELL      (default — let ladder run)
    """
    tweets = state.cum_tweets
    hours = state.hours_to_close

    # 1) SELL-NOW grid — first match wins
    for entry in cfg.get("sellnow_grid", []):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        min_tweets, min_hours = entry
        if tweets >= min_tweets and hours >= min_hours:
            return "SELL-NOW"

    # 2) HOLD — single clean state from data: very few tweets, lots of time left
    if (
        tweets <= cfg.get("hold_max_tweets", 5)
        and hours >= cfg.get("hold_min_hours_remaining", 24)
    ):
        return "HOLD"

    # 3) HOLD-LIGHT — softer hold zone (data showed 6-10 tweets / 24-30h
    #    median end ≥ 30¢ in 30%+ of cases). Pulled the threshold loosely
    #    so we don't over-sell during normal early-auction noise.
    if tweets <= 10 and hours >= 18:
        return "HOLD-LIGHT"

    # 4) Default
    return "SELL"


def should_market_sell(decision: str) -> bool:
    """Only SELL-NOW triggers an immediate market exit."""
    return decision == "SELL-NOW"


def should_cancel_aggressive_tiers(decision: str) -> bool:
    """SELL state: pull T3+T4 limits because we've lost the moonshot setup."""
    return decision == "SELL"


# ----------------------------------------------------------------------
# Pacing-aware enhancements (added 2026-05-05)
#
# The simple grid above treats each (tweets, hours_left) cell independently.
# These helpers add CONTEXT — how fast tweets are arriving relative to the
# bracket boundary (40), and how that velocity should override or amplify
# the default decisions.
# ----------------------------------------------------------------------

def projected_final_tweets(
    cum_tweets: int, hours_elapsed: float, total_hours: float,
) -> float:
    """Linear extrapolation of where tweet count lands at auction close.

    Assumes constant pacing — naive but useful as a tripwire. If cum=12 at
    hour-24 of a 48h window, projection = 24 final. If cum=20 at hour-12,
    projection = 80 — clearly busting the <40 bracket.
    """
    if hours_elapsed <= 0.5:
        return float(cum_tweets)  # too early to extrapolate
    rate_per_hour = cum_tweets / hours_elapsed
    return rate_per_hour * total_hours


def pacing_score(
    cum_tweets: int, hours_elapsed: float, total_hours: float, bracket_max: int = 40,
) -> float:
    """Returns a 0-2+ scalar:
      0.0 = no tweets at all (stupid bullish for <40)
      0.5 = on pace for half the bracket cap (very bullish)
      1.0 = exactly on pace to hit bracket_max at close (coin flip)
      1.5 = on pace for 1.5x the cap (bracket is busting)
      2.0+ = blowout
    Used to convert linear projection into a normalized score the
    decision logic can branch on without hardcoded numbers.
    """
    proj = projected_final_tweets(cum_tweets, hours_elapsed, total_hours)
    if bracket_max <= 0:
        return 0.0
    return proj / bracket_max


def classify_decision_v2(
    state: PositionState, cfg: dict, total_hours: float,
) -> tuple[str, dict]:
    """Pacing-aware classifier. Returns (decision, context).

    Adds two new triggers on top of the v1 logic:
      - PACING_SELL: cum_tweets are extrapolating past the bracket cap
        with low remaining time. Even if v1 says HOLD, override.
      - PACING_HOLD: pacing is shockingly slow (e.g. ≤30% of bracket cap
        projected). Even if v1 says SELL, override to HOLD.

    The `context` dict surfaces the pacing math so downstream code (and
    logs) can show WHY a decision was made.
    """
    tweets = state.cum_tweets
    hours_left = state.hours_to_close
    elapsed = max(total_hours - hours_left, 0.0)
    bracket_max = int(cfg.get("bracket_max_count", 40))

    score = pacing_score(tweets, elapsed, total_hours, bracket_max)
    proj = projected_final_tweets(tweets, elapsed, total_hours)
    ctx = {
        "pacing_score": round(score, 2),
        "projected_final_tweets": round(proj, 1),
        "elapsed_hours": round(elapsed, 1),
        "bracket_max": bracket_max,
    }

    # Pacing override 1: bracket is clearly busting AND not too early to tell
    pacing_sell_thresh = float(cfg.get("pacing_sell_score", 1.2))
    if score >= pacing_sell_thresh and elapsed >= total_hours * 0.20:
        return "SELL-NOW", {**ctx, "trigger": f"pacing_score {score:.2f} >= {pacing_sell_thresh}"}

    # Pacing override 2: pacing is shockingly slow, hold even if v1 says sell
    pacing_hold_thresh = float(cfg.get("pacing_hold_score", 0.30))
    base = classify_decision(state, cfg)
    if score <= pacing_hold_thresh and hours_left >= 6 and base == "SELL":
        return "HOLD-LIGHT", {**ctx, "trigger": f"pacing_score {score:.2f} <= {pacing_hold_thresh}"}

    return base, {**ctx, "trigger": "v1_classifier"}


def trailing_stop_price(
    peak_price: float, current_price: float, entry_price: float,
    trail_pct: float = 0.30,
) -> float | None:
    """If price has run up well past entry, trail a stop at trail_pct below
    the peak. Returns the stop price, or None if not yet eligible.

    Eligibility: position is at least 1.5x entry (50% gain) AND peak/current
    drawdown < 50% (otherwise it's already crashed; SELL-NOW handles that).
    """
    if entry_price <= 0 or peak_price <= 0:
        return None
    if peak_price < entry_price * 1.5:
        return None  # not enough upside yet
    drawdown = (peak_price - current_price) / peak_price
    if drawdown >= 0.5:
        return None  # already past trail
    return peak_price * (1.0 - trail_pct)


def adaptive_buy_price(
    best_bid: float, best_ask: float, base_target: float,
    spread_jump_eps: float = 0.001,
) -> float:
    """Smarter buy price than a hardcoded 12c.

    Logic:
      - If best_ask < base_target → buy at best_ask - eps (jump the queue
        for ~equivalent cost). E.g. ask=10c, target=12c → buy at 9.9c.
      - If best_ask >= base_target → place at base_target (limit waits).
      - Always clamps to [0.001, 0.99].
    """
    if best_ask > 0 and best_ask < base_target:
        return max(round(best_ask - spread_jump_eps, 4), 0.001)
    return min(max(base_target, 0.001), 0.99)


def adaptive_sell_ladder(
    entry_price: float, multipliers: list[float],
) -> list[float]:
    """Convert entry price + multipliers (e.g. [1.5, 2.0, 4.0, 8.0]) into
    absolute sell limit prices. Multipliers are RELATIVE to entry, so a
    9c entry → [13.5c, 18c, 36c, 72c] instead of hardcoded ladder.
    """
    return [min(round(entry_price * m, 4), 0.99) for m in multipliers]


def slow_bleed_sell_price(
    hours_to_close: float, current_bid: float, min_floor: float = 0.005,
) -> float:
    """When SELL-NOW fires but bid book is too thin to cross, walk a
    sell limit DOWN toward the floor over remaining hours.

    Strategy: place limit at (current_bid - small_step) but never below
    min_floor. Each cycle the price walks down — if any bid appears we
    fill, if not we keep walking.

    Returns the suggested limit-sell price.
    """
    if current_bid <= 0:
        # Empty book — start at 1c and decay from there
        # (closer to close = lower target)
        decay_factor = max(min(hours_to_close / 24.0, 1.0), 0.05)
        return max(round(0.01 * decay_factor, 4), min_floor)
    # Bid exists but is below SELLNOW_MIN_BID floor — sit just below it
    return max(round(current_bid - 0.001, 4), min_floor)
