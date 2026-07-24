"""Copytrader - OPTION B, maker-quoting (BUILD_SPEC F3, decided 2026-07-03).

A proven market-maker whale is used ONLY as a market/bracket SELECTOR +
confidence signal. We then quote our OWN post-only bids below OUR fair
value on those brackets. We never rest at the whale's fill price (that is
adversely selected: you catch its losers and miss its winners)."""
import logging

from api.modules.base import BaseModule
from api.modules.copytrader import data
from api.modules.copytrader.module_config import (DEFAULT_CONFIG,
                                                  get_module_config,
                                                  save_module_config)
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class CopytraderModule(BaseModule):
    name = "copytrader"

    def get_handle(self) -> str:
        return "elonmusk"

    def get_platform(self) -> str:
        return "x"

    def get_display_keywords(self) -> list[str]:
        return ["copy", "whale"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        from api.dependencies import get_supabase
        from api.modules.shared import discovery, fair_value, tweet_count, windows
        from api.modules.shared.config_store import module_bankroll
        from api.services.position_manager import open_positions

        from api.modules.shared import whale_registry

        cfg = self.get_config(module_id)

        # MULTIPLE whales now (2026-07-24): the configured whale PLUS every wallet the
        # registry tags 'tweet'. Each is perf-gated on its OWN recent ROI; a bracket is
        # "active" if ANY healthy whale is trading it. Widens the copytrader's coverage
        # from one wallet to the full tracked tweet-whale set as the registry grows.
        whales = list(dict.fromkeys(
            [cfg["whale_wallet"]] + whale_registry.by_archetype("tweet")))
        active_conditions: set = set()
        roi = None  # best ROI among healthy whales (for downstream sizing/metadata)
        for w in whales:
            r = data.whale_recent_roi(w)
            if r is None or r < cfg["whale_perf_gate_roi"]:
                continue
            roi = r if roi is None else max(roi, r)
            for t in data.whale_trades(w, cfg["lookback_hours"]):
                if t.get("conditionId"):
                    active_conditions.add(t["conditionId"])
        if roi is None:
            log.info("copytrader: %d whale(s), none healthy (perf-gated)", len(whales))
            return []
        if not active_conditions:
            log.info("copytrader: %d whale(s) healthy but no recent trades", len(whales))
            return []

        # Which LIVE Elon tweet brackets is the whale active in? (Option B is
        # tweet-scoped - the validated market. When this proven generalist MM
        # is trading sports/politics instead, there is no overlap and we
        # correctly stay idle rather than quoting markets we have no model for.)
        auctions = discovery.fetch_tweet_auctions(slug_contains="elon-musk-of-tweets")
        overlap = {c for a in auctions for b in a["brackets"]
                   if (c := b["condition_id"]) in active_conditions}
        if not overlap:
            log.info("copytrader: whale healthy (ROI=%.1f%%), active in %d markets, "
                     "but none are live Elon tweet brackets - idle by design",
                     roi * 100, len(active_conditions))
            return []
        signals: list[Signal] = []
        bankroll = module_bankroll(module_id)
        sb = get_supabase()
        resting = (sb.table("orders").select("bracket,market_id")
                   .eq("module_id", module_id).eq("side", "BUY")
                   .in_("status", ["submitted", "open"]).execute().data) or []
        resting_keys = {(r["market_id"], r["bracket"]) for r in resting}
        held_keys = {(p["market_id"], p["bracket"]) for p in open_positions(module_id)}

        held_prices_by_slug: dict[str, float] = {}
        for p in open_positions(module_id):
            held_prices_by_slug[p.get("market_id") or ""] = float(p["avg_price"])

        for auction in auctions:
            targets = [b for b in auction["brackets"]
                       if b["condition_id"] in active_conditions]
            if not targets or not auction["window_start"]:
                continue
            # Aggregate price ceiling per auction (D4), same rule as S2.
            basket_sum = sum(held_prices_by_slug.get(b["condition_id"], 0.0)
                             for b in auction["brackets"])
            tracking = tweet_count.fetch_tracking_for_slug(auction["slug"])
            count = tweet_count.current_count(tracking["id"]) if tracking else None
            if count is None:
                continue
            elapsed = windows.elapsed_fraction(auction["window_start"], auction["window_end"])
            from datetime import datetime
            remaining_h = max(0.0, (auction["window_end"]
                                    - datetime.now(windows.ET)).total_seconds() / 3600.0)
            prior_mean, prior_std = fair_value.VALIDATED_PRIORS.get(
                auction["duration_type"], fair_value.VALIDATED_PRIORS["2-day"])
            projection = fair_value.projection(
                count, elapsed, prior_mean, prior_std,
                duration_type=auction["duration_type"], remaining_hours=remaining_h)
            dist = fair_value.bracket_distribution(
                projection, count, [b["label"] for b in auction["brackets"]], remaining_h)
            for b in targets:
                if (b["condition_id"], b["label"]) in resting_keys | held_keys:
                    continue
                fair = dist.get(b["label"], 0.0)
                price = snap_price(fair - cfg["bid_margin_below_fair"], b["tick"])
                if price < b["tick"]:
                    continue
                if b["best_ask"] is not None and price >= b["best_ask"]:
                    price = snap_price(b["best_ask"] - b["tick"], b["tick"])
                edge = fair - price
                if edge < cfg["min_edge_threshold"]:
                    continue
                if basket_sum + price > min(cfg["aggregate_price_ceiling"], 0.65):
                    continue
                f_star = (fair - price) / (1 - price) if price < 1 else 0
                stake = min(cfg["kelly_fraction"] * f_star * bankroll,
                            cfg["max_bet_pct"] * bankroll)
                size = int(stake / price) if price > 0 else 0
                if size * price < 1.0 or size < 5:
                    continue
                basket_sum += price
                signals.append(Signal(
                    module_id=module_id, market_id=b["condition_id"],
                    bracket=b["label"], side="BUY", price=price, size=size,
                    token_id=b["yes_token"], fair_value=fair, edge=edge,
                    auction_slug=auction["slug"], spread=b["spread"],
                    best_bid=b["best_bid"], best_ask=b["best_ask"],
                    metadata={"whale": cfg["whale_wallet"][:10],
                              "whale_roi": round(roi, 4)}))
        log.info("copytrader: whale active in %d conditions -> %d signal(s)",
                 len(active_conditions), len(signals))
        return signals
