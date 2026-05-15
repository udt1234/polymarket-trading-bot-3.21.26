"""Cheap-tier lottery strategy with pacing-aware exits.

Calibrated for: brackets where the bot expects mostly-NO outcomes but
the rare YES pays out 10-300x. Optimal for Elon 2-day '<40' (current
Spike target). Uses a descending limit-buy ladder that tries cheap first
and escalates only if the market never crashes that low.

Exits via:
  - Sell-multiplier ladder of fill price (capture upside spikes)
  - SELL-NOW pacing classifier (extrapolated tweet count >> bracket cap)
  - SELL-NOW grid (manually-tuned tweet+hours_left cells)
  - take_profit / stop_loss / trailing_stop (in exit_manager)
"""
from __future__ import annotations
from .base import Strategy, AuctionState


class CheapLotteryPacing(Strategy):
    name = "Cheap_Lottery_Pacing"

    # 2026-05-14 ladder rewrite:
    # Tiers now encode `notional_usd` (the dollar amount per tier) instead
    # of `pct` of bankroll. Each tier MUST clear all three Polymarket CLOB
    # minimums:
    #   - price >= 0.01 (1¢ min tick — strategies below 1¢ get rejected)
    #   - notional_usd >= 1.00 ($1 min order notional)
    #   - size >= 5 shares (5-share min_order_size)
    # The base default totals $25/auction across 5 tiers. The actual amount
    # is rescaled at runtime by `spike_total_commitment_usd` cfg key so the
    # user can dial the whole ladder up or down without rebalancing tiers.
    DEFAULT_PARAMS = {
        "buy_ladder": [
            {"price": 0.03, "notional_usd": 3.0, "label": "deep_discount"},
            {"price": 0.05, "notional_usd": 5.0, "label": "cheap_normal"},
            {"price": 0.07, "notional_usd": 7.0, "label": "at_ask"},
            {"price": 0.10, "notional_usd": 5.0, "label": "pay_up"},
            {"price": 0.15, "notional_usd": 5.0, "label": "insurance"},
        ],
        # When the prior 2-day auction resolved ABOVE the bracket (>40 won
        # in our case), structural pacing shifts higher. We replace the
        # `insurance` tier (15¢) with a wider `wider_insurance` tier (22¢)
        # to cast a broader net. Same notional, more shares-at-price.
        "buy_ladder_prior_lost": [
            {"price": 0.03, "notional_usd": 3.0, "label": "deep_discount"},
            {"price": 0.05, "notional_usd": 5.0, "label": "cheap_normal"},
            {"price": 0.07, "notional_usd": 7.0, "label": "at_ask"},
            {"price": 0.10, "notional_usd": 5.0, "label": "pay_up"},
            {"price": 0.22, "notional_usd": 5.0, "label": "wider_insurance"},
        ],
        "buy_cancel_after_hours": 24,
        "enter_after_hours_elapsed": 0,    # buy from auction start
        "sell_multipliers": [1.5, 2.0, 4.0, 8.0],
        "sell_multiplier_pcts": [0.30, 0.30, 0.20, 0.20],
        "take_profit_pct": 7.0,
        "stop_loss_pct": 0.85,
        "trailing_stop_pct": 0.30,
        "hold_max_tweets": 5,
        "hold_min_hours_remaining": 24,
        "sellnow_grid": [[16, 24], [20, 18], [30, 0]],
        "pacing_sell_score": 1.20,
        "pacing_hold_score": 0.30,
    }

    def can_enter(self, state, params):
        cancel_after = float(params.get("buy_cancel_after_hours", 24))
        enter_after = float(params.get("enter_after_hours_elapsed", 0))
        if state.elapsed_hours < enter_after:
            return False, f"too early (elapsed {state.elapsed_hours:.1f}h < threshold {enter_after}h)"
        if state.elapsed_hours > cancel_after:
            return False, f"past cutoff (elapsed {state.elapsed_hours:.1f}h > {cancel_after}h)"
        return True, "ok"

    def build_buy_ladder(self, state, params):
        """Emit the ladder. Selects the `buy_ladder_prior_lost` variant
        when `prior_above_bracket=True` is set in params (the engine sets
        this flag by querying auction_archive for the prior resolved
        auction). Otherwise uses the standard ladder."""
        prior_lost = bool((params or {}).get("prior_above_bracket"))
        if prior_lost:
            ladder = params.get(
                "buy_ladder_prior_lost",
                self.DEFAULT_PARAMS["buy_ladder_prior_lost"],
            )
        else:
            ladder = params.get(
                "buy_ladder", self.DEFAULT_PARAMS["buy_ladder"]
            )

        # Rescale total commitment to `spike_total_commitment_usd` if set.
        # The default ladder sums to ~$25; user can dial it up/down without
        # rebalancing individual tiers by hand.
        base_total = sum(float(t.get("notional_usd", 0)) for t in ladder) or 1.0
        target_total = float((params or {}).get("spike_total_commitment_usd", base_total))
        scale = target_total / base_total if base_total > 0 else 1.0

        out = []
        for i, t in enumerate(ladder, start=1):
            price = float(t.get("price", 0))
            notional = float(t.get("notional_usd", 0)) * scale
            label = t.get("label", f"tier{i}")
            if price <= 0 or notional <= 0:
                continue
            out.append({
                "price": price,
                "notional_usd": round(notional, 2),
                "label": label,
                "tier": i,
            })
        return out

    def classify(self, state, position, params):
        tweets = state.cum_tweets
        hours_left = state.hours_to_close
        elapsed = state.elapsed_hours
        total = state.total_hours
        bracket_max = state.bracket_max_count

        # Pacing score: extrapolated final / bracket boundary
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

        # 1) Pacing override: clearly busting → SELL-NOW
        sell_thresh = float(params.get("pacing_sell_score", 1.20))
        if score >= sell_thresh and elapsed >= total * 0.20:
            return "SELL-NOW", {**ctx, "trigger": f"pacing {score:.2f}>={sell_thresh}"}

        # 2) SELL-NOW grid (tweet, hours_left) cells
        for entry in params.get("sellnow_grid", []):
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            min_t, min_h = entry
            if tweets >= min_t and hours_left >= min_h:
                return "SELL-NOW", {**ctx, "trigger": f"grid cell ({min_t},{min_h})"}

        # 3) HOLD: clean lottery setup
        if tweets <= int(params.get("hold_max_tweets", 5)) and hours_left >= float(params.get("hold_min_hours_remaining", 24)):
            return "HOLD", {**ctx, "trigger": "clean_hold"}

        # 4) HOLD-LIGHT: pacing clearly NOT busting
        hold_thresh = float(params.get("pacing_hold_score", 0.30))
        if score <= hold_thresh and hours_left >= 6:
            return "HOLD-LIGHT", {**ctx, "trigger": f"pacing {score:.2f}<={hold_thresh}"}

        # 5) Default: let the limit-sell ladder run
        return "SELL", {**ctx, "trigger": "default"}

    def sell_targets(self, fill_price, params):
        mults = params.get("sell_multipliers", self.DEFAULT_PARAMS["sell_multipliers"])
        pcts = params.get("sell_multiplier_pcts", self.DEFAULT_PARAMS["sell_multiplier_pcts"])
        out = []
        for m, p in zip(mults, pcts):
            target = min(round(fill_price * float(m), 4), 0.99)
            out.append((target, float(p)))
        return out

    def display_label(self, params):
        return "Cheap Lottery (pacing-aware)"

    def describe(self, params):
        # `state` not used in build_buy_ladder, safe
        ladder = self.build_buy_ladder(None, params) if params else []
        total = sum(t.get("notional_usd", 0) for t in ladder)
        prior_lost = bool((params or {}).get("prior_above_bracket"))
        lines = [
            "Strategy: Cheap Lottery with Pacing-Aware Exits",
            "Best for: brackets with low YES rate (~2-15%) where the rare winner pays 10-300x.",
            f"Entry timing: any time in the first {params.get('buy_cancel_after_hours', 24)}h after auction start.",
            f"Buy ladder: {len(ladder)} simultaneous limit orders, ${total:.2f} total notional"
            + (" — wider mode (prior auction settled >40)" if prior_lost else ""),
            ".",
        ]
        for t in ladder:
            shares = (t.get("notional_usd", 0) / t.get("price", 1)) if t.get("price") else 0
            lines.append(
                f"  • Tier '{t.get('label')}': {t.get('price')*100:.1f}¢ "
                f"for ${t.get('notional_usd', 0):.2f} (~{shares:.0f} shares)"
            )
        lines += [
            "Exits (any one fires SELL-NOW):",
            f"  • Pacing score ≥ {params.get('pacing_sell_score', 1.20)} after first 20% of window (clear bracket-bust)",
            f"  • SELL-NOW grid: {params.get('sellnow_grid')} (tweets, hours-left)",
            f"  • Stop-loss at {params.get('stop_loss_pct', 0.85)*100:.0f}% drawdown",
            f"Sell ladder (multipliers of fill price): {params.get('sell_multipliers')}",
        ]
        return lines
