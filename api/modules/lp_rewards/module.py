"""LP-reward farming. Rest post-only bids INSIDE the reward band of mid on BOTH
outcomes of reward-eligible markets to earn Polymarket liquidity rewards. If both
legs fill we hold a near-complete set (~$1) - low directional risk. MAKER-ONLY:
every quote is a post-only bid strictly below the ask on its token."""
import logging

from api.modules.base import BaseModule
from api.modules.lp_rewards import data
from api.modules.lp_rewards.module_config import (DEFAULT_CONFIG,
                                                 get_module_config,
                                                 save_module_config)
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class LpRewardsModule(BaseModule):
    name = "lp_rewards"

    def get_handle(self) -> str:
        return ""

    def get_platform(self) -> str:
        return "polymarket"

    def get_display_keywords(self) -> list[str]:
        return ["lp", "reward", "liquidity"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        from api.dependencies import get_supabase
        from api.services.position_manager import open_positions

        cfg = self.get_config(module_id)
        markets = data.reward_markets(cfg)
        if not markets:
            return []

        sb = get_supabase()
        resting = (sb.table("orders").select("token_id").eq("module_id", module_id)
                   .eq("side", "BUY")
                   .in_("status", ["submitted", "open", "partially_filled"])
                   .execute().data) or []
        resting_tokens = {r["token_id"] for r in resting}
        held_tokens = {p.get("token_id") for p in open_positions(module_id)}

        signals: list[Signal] = []
        used = 0
        for m in markets:
            if used >= cfg["max_markets"]:
                break
            band = m["rewards_max_spread"] / 100.0          # cents -> price
            offset = cfg["quote_frac_of_band"] * band
            outs = m["outcomes"]
            legs = [
                (m["yes_token"], m["mid"], m["best_bid"], m["best_ask"],
                 outs[0] if outs else "YES"),
                (m["no_token"], round(1 - m["mid"], 4),   # NO book = inverted YES
                 round(1 - m["best_ask"], 4), round(1 - m["best_bid"], 4),
                 outs[1] if len(outs) > 1 else "NO"),
            ]
            emitted = False
            for token, mid, tbid, task, outcome in legs:
                if token in resting_tokens or token in held_tokens:
                    continue
                price = snap_price(mid - offset, m["tick"])
                if not (cfg["min_price"] <= price <= cfg["max_price"]):
                    continue
                if task is not None and price >= task:      # stay a maker
                    continue
                size = int(m["rewards_min_size"])           # must meet min_size to qualify
                if size < 5:
                    size = 5
                if size * price > cfg["max_per_token_usd"]:  # unaffordable slice
                    continue
                signals.append(Signal(
                    module_id=module_id, market_id=m["condition_id"], bracket=outcome,
                    side="BUY", price=price, size=size, token_id=token,
                    fair_value=mid, edge=round(mid - price, 4), auction_slug="",
                    spread=round(task - tbid, 4) if task is not None else None,
                    best_bid=tbid, best_ask=task,
                    metadata={"strategy": "lp_rewards", "daily_rate": round(m["daily_rate"], 2),
                              "reward_band_cents": m["rewards_max_spread"],
                              "min_size": m["rewards_min_size"]}))
                emitted = True
            if emitted:
                used += 1
        log.info("lp_rewards: %d reward markets, %d quotes on %d markets",
                 len(markets), len(signals), used)
        return signals
