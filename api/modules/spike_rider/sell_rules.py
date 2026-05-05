"""Pure-function sell rule evaluators for Spike Rider.

These match the rules tested in scripts/simulate_sell_rules.py so the live
bot exits using the same logic the simulator picked. Every function takes
the position state and returns one of:
  None                  — hold
  ("full", reason)      — sell entire remaining size
  ("fraction", f, r)    — sell f fraction (0<f<=1) of *original* size, with reason r
"""
from dataclasses import dataclass


@dataclass
class PositionState:
    avg_price: float          # entry price after slippage/fees
    current_price: float
    peak_price: float         # max observed since open
    original_size: float      # size at first fill (multi-stage references this)
    current_size: float       # size remaining now
    stages_done: tuple[bool, ...] = (False, False, False)


def evaluate_target_multiplier(
    state: PositionState, multiplier: float,
) -> tuple | None:
    if state.avg_price <= 0:
        return None
    if state.current_price >= state.avg_price * multiplier:
        return ("full", f"target_{multiplier:.1f}x_hit @ {state.current_price:.4f}")
    return None


def evaluate_trailing_stop(
    state: PositionState, trail_pct: float, min_gain_pct: float,
) -> tuple | None:
    if state.avg_price <= 0:
        return None
    armed = state.peak_price >= state.avg_price * (1.0 + min_gain_pct)
    if armed and state.current_price <= state.peak_price * (1.0 - trail_pct):
        return ("full", f"trailing_stop {trail_pct * 100:.0f}% off peak {state.peak_price:.4f}")
    return None


def evaluate_multi_stage(
    state: PositionState, targets: list[float],
) -> tuple | None:
    """Return next pending tranche, if any. Caller persists which stages done.

    Sells 1/N of *original* size each time a new multiplier target is hit, in
    order. The last target also triggers any earlier stages that haven't
    fired (e.g. price gaps from 1.5x straight to 5x).
    """
    if state.avg_price <= 0 or not targets:
        return None
    n = len(targets)
    fraction = 1.0 / n
    for i, mult in enumerate(targets):
        if i < len(state.stages_done) and state.stages_done[i]:
            continue
        if state.current_price >= state.avg_price * mult:
            return ("fraction", fraction, f"multi_stage_{mult:.1f}x_hit @ {state.current_price:.4f}", i)
    return None


def evaluate(
    state: PositionState, config: dict,
) -> tuple | None:
    """Top-level dispatcher. Reads `sell_rule_type` from config; falls back to
    trailing-stop as a safety net if the primary rule didn't trigger.
    """
    rule = config.get("sell_rule_type", "multi_stage")

    primary = None
    if rule == "multi_stage":
        primary = evaluate_multi_stage(state, list(config.get("sell_multi_stage_targets") or [2.0, 3.0, 5.0]))
    elif rule == "target_multiplier":
        primary = evaluate_target_multiplier(state, float(config.get("sell_target_multiplier") or 2.0))
    elif rule == "trailing_stop":
        primary = evaluate_trailing_stop(
            state,
            float(config.get("sell_trail_pct") or 0.30),
            float(config.get("sell_min_gain_pct") or 0.50),
        )
    if primary is not None:
        return primary

    # Safety-net trailing stop runs for every rule type. Locks in profit when a
    # spike reverses without first hitting the primary trigger.
    if rule != "trailing_stop":
        backup = evaluate_trailing_stop(
            state,
            float(config.get("sell_trail_pct") or 0.30),
            float(config.get("sell_min_gain_pct") or 0.50),
        )
        if backup is not None:
            return backup
    return None
