"""Mid-priced range-trading strategy with absolute (not multiplier) sell targets.

Calibrated for: brackets that historically swing through a wide tradeable
range mid-auction even when they don't resolve YES. Best validated on
2-day Elon 65-89 (76.5% arc reliability per parquet recalibration).

Key differences vs Cheap_Lottery_Pacing:
  - Wait at least N hours after auction start before entering (these
    brackets often start expensive and crash as Elon ramps; buying too
    early means catching a falling knife).
  - Buy at mid-prices (5-15¢) not lottery floors (most never reach <1¢).
  - Sell at absolute prices (30¢/50¢/median-peak), not multipliers of fill,
    because the upside ceiling is bounded by where the bracket actually peaks.
  - Tighter stop-loss because the YES-rate is higher and losing positions
    crash faster. Hold-to-resolution doesn't pay off as often.
"""
from __future__ import annotations
from .base import Strategy, AuctionState


class MidRangeSpike(Strategy):
    name = "Mid_Range_Spike"

    DEFAULT_PARAMS = {
        "buy_ladder": [
            {"price": 0.05, "pct": 0.40, "label": "early"},
            {"price": 0.10, "pct": 0.40, "label": "core"},
            {"price": 0.15, "pct": 0.20, "label": "late"},
        ],
        "buy_cancel_after_hours": 30,        # bigger window than lottery
        "enter_after_hours_elapsed": 6,      # WAIT for the initial peak to crash
        "sell_targets": [                    # absolute prices, not multipliers
            {"price": 0.30, "pct": 0.40},    # lock-in (hits ~70% of qualifying auctions)
            {"price": 0.50, "pct": 0.40},    # typical peak (~50%)
            {"price": 0.70, "pct": 0.20},    # moonshot (~20%)
        ],
        "take_profit_pct": 4.0,
        "stop_loss_pct": 0.50,               # tighter than lottery
        "trailing_stop_pct": 0.25,
        "hold_max_tweets": 8,
        "hold_min_hours_remaining": 18,
        "sellnow_grid": [],                  # range strategy doesn't use grid; pacing handles it
        "pacing_sell_score": 1.10,           # tighter pacing threshold
        "pacing_hold_score": 0.40,
    }

    def can_enter(self, state, params):
        enter_after = float(params.get("enter_after_hours_elapsed", 6))
        cancel_after = float(params.get("buy_cancel_after_hours", 30))
        if state.elapsed_hours < enter_after:
            return False, f"waiting for crash (elapsed {state.elapsed_hours:.1f}h < {enter_after}h)"
        if state.elapsed_hours > cancel_after:
            return False, f"past cutoff (elapsed {state.elapsed_hours:.1f}h > {cancel_after}h)"
        return True, "ok"

    def build_buy_ladder(self, state, params):
        ladder = params.get("buy_ladder", self.DEFAULT_PARAMS["buy_ladder"])
        out = []
        for i, t in enumerate(ladder, start=1):
            price = float(t.get("price", 0))
            pct = float(t.get("pct", 0))
            label = t.get("label", f"tier{i}")
            if price <= 0 or pct <= 0:
                continue
            out.append({"price": price, "pct": pct, "label": label, "tier": i})
        return out

    def classify(self, state, position, params):
        tweets = state.cum_tweets
        hours_left = state.hours_to_close
        elapsed = state.elapsed_hours
        total = state.total_hours
        bracket_max = state.bracket_max_count

        # Pacing score
        if elapsed > 0.5:
            rate = tweets / elapsed
            proj = rate * total
        else:
            proj = float(tweets)
        score = (proj / bracket_max) if bracket_max > 0 else 0.0
        ctx = {
            "pacing_score": round(score, 2),
            "projected_final_tweets": round(proj, 1),
            "elapsed_hours": round(elapsed, 1),
        }

        # SELL-NOW: pacing has clearly drifted out of bracket
        # (Range brackets win when projection lands INSIDE the bracket; if pacing
        # extrapolates past or below the bracket, position is dead.)
        sell_thresh = float(params.get("pacing_sell_score", 1.10))
        if score >= sell_thresh and elapsed >= total * 0.20:
            return "SELL-NOW", {**ctx, "trigger": f"pacing too high {score:.2f}>={sell_thresh}"}

        # Optional grid (usually empty for range strategy)
        for entry in params.get("sellnow_grid", []):
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            min_t, min_h = entry
            if tweets >= min_t and hours_left >= min_h:
                return "SELL-NOW", {**ctx, "trigger": f"grid ({min_t},{min_h})"}

        # HOLD when pacing very low AND lots of time (bracket clearly NOT busting)
        hold_thresh = float(params.get("pacing_hold_score", 0.40))
        if score <= hold_thresh and hours_left >= 6:
            return "HOLD-LIGHT", {**ctx, "trigger": f"pacing low {score:.2f}<={hold_thresh}"}

        return "SELL", {**ctx, "trigger": "default — let limit-sell ladder run"}

    def sell_targets(self, fill_price, params):
        targets = params.get("sell_targets", self.DEFAULT_PARAMS["sell_targets"])
        out = []
        for t in targets:
            p = float(t.get("price", 0))
            pct = float(t.get("pct", 0))
            if p <= 0 or pct <= 0:
                continue
            # If the absolute target is BELOW our fill, skip it (would sell at loss)
            if p <= fill_price:
                continue
            out.append((min(p, 0.99), pct))
        return out

    def display_label(self, params):
        return "Mid-Range Spike (absolute targets)"

    def describe(self, params):
        ladder = self.build_buy_ladder(None, params) if params else self.DEFAULT_PARAMS["buy_ladder"]  # type: ignore
        targets = params.get("sell_targets", self.DEFAULT_PARAMS["sell_targets"])
        lines = [
            "Strategy: Mid-Range Spike with Absolute Sell Targets",
            "Best for: brackets with high arc-reliability (always crashes <5¢ AND spikes >30¢ at some point).",
            f"Entry timing: WAIT {params.get('enter_after_hours_elapsed', 6)}h after start, "
            f"then up to hour {params.get('buy_cancel_after_hours', 30)}.",
            f"Buy ladder: {len(ladder)} limit orders at mid-prices.",
        ]
        for t in ladder:
            lines.append(f"  • '{t.get('label')}': {t.get('price')*100:.1f}¢ for {t.get('pct')*100:.0f}% of bracket cap")
        lines += [
            "Sell ladder (absolute prices, not multipliers):",
        ]
        for t in targets:
            lines.append(f"  • Sell {t.get('pct')*100:.0f}% at {t.get('price')*100:.0f}¢")
        lines += [
            f"Stop-loss: {params.get('stop_loss_pct', 0.50)*100:.0f}% drawdown — tighter than lottery.",
            f"Pacing SELL-NOW: score ≥ {params.get('pacing_sell_score', 1.10)}.",
        ]
        return lines
