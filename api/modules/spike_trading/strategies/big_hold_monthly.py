"""Long-window high-probability hold strategy.

Calibrated for: monthly auctions where one bracket reliably wins ~50% of
the time and pays $1.00. Best validated on Elon Monthly 1400+ (50% YES
rate, 99¢ median peak per parquet recalibration). Designed for high
asymmetric expected value: half the time you make 50-100x, half the time
you eat a deep stop loss.

Key differences from short-window strategies:
  - Entry window is the FIRST {enter_window_days} of the month only.
    Once price has moved up, we've missed our edge — don't chase.
  - Hold to resolution (or take_profit at >50x). Stop loss is wide
    because the bracket can dip mid-month before recovering.
  - Pacing override only fires VERY late (>80% of window elapsed) since
    the monthly tail is unpredictable until the final week.
  - Sell ladder targets nearly the final $1.00 (these brackets win OR die).
"""
from __future__ import annotations
from .base import Strategy, AuctionState


class BigHoldMonthly(Strategy):
    name = "Big_Hold_Monthly"

    DEFAULT_PARAMS = {
        "buy_ladder": [
            {"price": 0.005, "pct": 0.30, "label": "deep"},
            {"price": 0.020, "pct": 0.30, "label": "value"},
            {"price": 0.050, "pct": 0.20, "label": "mid"},
            {"price": 0.100, "pct": 0.20, "label": "catchall"},
        ],
        "buy_cancel_after_hours": 168,         # only buy in first 7 days of month
        "enter_after_hours_elapsed": 0,        # buy from day 1
        "sell_targets": [
            {"price": 0.40, "pct": 0.20},      # partial lock-in on a big run
            {"price": 0.70, "pct": 0.20},      # mid-pull
            {"price": 0.95, "pct": 0.60},      # hold most of the position to resolution
        ],
        "take_profit_pct": 50.0,               # essentially no auto-take-profit; let it ride
        "stop_loss_pct": 0.95,                 # near-no stop loss; bracket dips are normal
        "trailing_stop_pct": 0.50,             # very loose trail
        "pacing_sell_score": 2.00,             # only fire on extreme overshoot
        "pacing_hold_score": 0.20,
        "pacing_eligible_after_pct": 0.80,     # pacing override only fires after 80% of window elapsed
    }

    def can_enter(self, state, params):
        enter_after = float(params.get("enter_after_hours_elapsed", 0))
        cancel_after = float(params.get("buy_cancel_after_hours", 168))
        if state.elapsed_hours < enter_after:
            return False, f"too early"
        if state.elapsed_hours > cancel_after:
            return False, f"past entry window (elapsed {state.elapsed_hours:.1f}h > {cancel_after}h = ~{cancel_after/24:.1f}d)"
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

        # Pacing SELL-NOW only fires very late in the window
        eligible_after = float(params.get("pacing_eligible_after_pct", 0.80))
        sell_thresh = float(params.get("pacing_sell_score", 2.00))
        if elapsed >= total * eligible_after and score >= sell_thresh:
            return "SELL-NOW", {**ctx, "trigger": f"late-stage pacing {score:.2f}>={sell_thresh}"}

        # Hold otherwise
        return "HOLD", {**ctx, "trigger": "long_hold_to_resolution"}

    def sell_targets(self, fill_price, params):
        targets = params.get("sell_targets", self.DEFAULT_PARAMS["sell_targets"])
        out = []
        for t in targets:
            p = float(t.get("price", 0))
            pct = float(t.get("pct", 0))
            if p <= 0 or pct <= 0 or p <= fill_price:
                continue
            out.append((min(p, 0.99), pct))
        return out

    def display_label(self, params):
        return "Big Hold Monthly (deep entry, hold to resolve)"

    def describe(self, params):
        ladder = self.build_buy_ladder(None, params) if params else self.DEFAULT_PARAMS["buy_ladder"]  # type: ignore
        targets = params.get("sell_targets", self.DEFAULT_PARAMS["sell_targets"])
        cancel_h = params.get("buy_cancel_after_hours", 168)
        lines = [
            "Strategy: Big Hold Monthly",
            "Best for: monthly brackets with ~50% YES rate that pay $1.00 (e.g. Elon Monthly 1400+).",
            f"Entry window: first {cancel_h:.0f}h ({cancel_h/24:.0f} days) of the month only — don't chase.",
            f"Buy ladder: {len(ladder)} cheap-tier limit orders.",
        ]
        for t in ladder:
            lines.append(f"  • '{t.get('label')}': {t.get('price')*100:.1f}¢ for {t.get('pct')*100:.0f}% of bracket cap")
        lines.append("Sell ladder (mostly hold to resolution):")
        for t in targets:
            lines.append(f"  • Sell {t.get('pct')*100:.0f}% at {t.get('price')*100:.0f}¢")
        lines += [
            f"Stop-loss: {params.get('stop_loss_pct', 0.95)*100:.0f}% (essentially none — bracket dips are normal mid-month).",
            f"Pacing SELL-NOW: only fires after {params.get('pacing_eligible_after_pct', 0.80)*100:.0f}% of window elapsed AND extrapolation overshoots by {params.get('pacing_sell_score', 2.0)}x.",
        ]
        return lines
