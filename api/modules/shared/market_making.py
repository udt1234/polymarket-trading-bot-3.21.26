"""Two-sided market-making quote math (pure stdlib).

A maker-only, long-only bot market-makes a token by resting a BID below mid and,
when it HOLDS inventory, an ASK above its cost - capturing the spread on the round
trip and earning reward-pool income on the resting orders. Inventory is managed by
SKEWING: the more of a token we hold, the lower we push BOTH quotes (bid less
eagerly, offer more eagerly) so we mean-revert toward a flat book instead of piling
into one side (adverse-selection defence).

    mid          = (best_bid + best_ask) / 2
    inv_frac     = held_notional / max_inventory_notional   (0 = flat, 1 = full)
    bid = mid - half_spread - skew*inv_frac
    ask = mid + half_spread - skew*inv_frac                  (offer harder as we fill)

Shared so the module and any backtest use the identical quoting rule.
"""


def _clamp_snap(price: float, tick: float) -> float:
    price = max(tick, min(1.0 - tick, price))
    return round(round(price / tick) * tick, 6)


def quote(mid: float, half_spread: float, tick: float,
          inv_frac: float = 0.0, skew: float = 0.0,
          best_bid: float | None = None, best_ask: float | None = None) -> dict:
    """Return {bid, ask} post-only prices around mid, inventory-skewed, guaranteed
    NOT to cross the live book (post-only would be rejected). A side is None when it
    should not be quoted (bid suppressed when full; caller decides ask by inventory)."""
    inv_frac = max(0.0, inv_frac)
    raw_bid = mid - half_spread - skew * inv_frac
    raw_ask = mid + half_spread - skew * inv_frac
    bid = _clamp_snap(raw_bid, tick)
    ask = _clamp_snap(raw_ask, tick)
    # never cross the resting book: our bid must sit at/below best_ask-tick, our
    # ask at/above best_bid+tick, else post-only rejects.
    if best_ask is not None and bid >= best_ask:
        bid = _clamp_snap(best_ask - tick, tick)
    if best_bid is not None and ask <= best_bid:
        ask = _clamp_snap(best_bid + tick, tick)
    # keep a real spread between our own two quotes
    if ask <= bid:
        ask = _clamp_snap(bid + tick, tick)
    return {"bid": bid if inv_frac < 1.0 else None, "ask": ask}


def reward_band_ok(price: float, mid: float, rewards_max_spread_cents: float | None) -> bool:
    """For a reward-eligible market, an order only earns the pool if it rests within
    rewardsMaxSpread cents of mid. True when we have no reward constraint or we are
    inside the band."""
    if not rewards_max_spread_cents:
        return True
    return abs(price - mid) <= (rewards_max_spread_cents / 100.0) + 1e-9
