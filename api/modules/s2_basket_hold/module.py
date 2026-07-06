"""S2 Basket-Hold (BUILD_SPEC F2) - BUILD FIRST strategy.

Rests patient post-only maker bids a margin below fair value on the 2-3
brackets around the projected count, holds to resolution, salvage-exits
dead brackets. Never takes."""
import logging

from api.modules.base import BaseModule
from api.modules.s2_basket_hold import decision
from api.modules.s2_basket_hold.data import live_auction_snapshot
from api.modules.s2_basket_hold.module_config import (DEFAULT_CONFIG,
                                                      get_module_config,
                                                      save_module_config)

log = logging.getLogger(__name__)


class S2BasketHoldModule(BaseModule):
    name = "s2_basket_hold"

    def get_handle(self) -> str:
        return "elonmusk"

    def get_platform(self) -> str:
        return "x"

    def get_display_keywords(self) -> list[str]:
        return ["s2", "basket"]

    def get_auction_window_days(self) -> float | None:
        return 2.0

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "auction_duration", "label": "Auction", "type": "select",
             "options": ["2-day", "7-day", "monthly"], "section": "general"},
            {"key": "num_brackets", "label": "Brackets quoted", "type": "number",
             "min": 1, "max": 5, "step": 1, "section": "buy"},
            {"key": "bid_margin_below_fair", "label": "Bid margin below fair ($)",
             "type": "number", "min": 0.01, "max": 0.10, "step": 0.01, "section": "buy"},
            {"key": "kelly_fraction", "label": "Kelly fraction", "type": "number",
             "min": 0.05, "max": 0.5, "step": 0.05, "section": "risk"},
            {"key": "max_bet_pct", "label": "Max bet (% bankroll)", "type": "number",
             "min": 0.01, "max": 0.25, "step": 0.01, "section": "risk"},
            {"key": "aggregate_price_ceiling", "label": "Basket price ceiling",
             "type": "number", "min": 0.3, "max": 0.65, "step": 0.05, "section": "risk"},
            {"key": "salvage_exit_threshold", "label": "Salvage exit below fair",
             "type": "number", "min": 0.0, "max": 0.10, "step": 0.01, "section": "sell"},
        ]

    async def _evaluate_async(self, module_id: str) -> list:
        from api.dependencies import get_supabase
        from api.modules.shared.config_store import module_bankroll
        from api.services.position_manager import open_positions

        cfg = self.get_config(module_id)
        auction = live_auction_snapshot(cfg["auction_duration"])
        if not auction:
            log.info("s2: no live %s auction with a count - skipping",
                     cfg["auction_duration"])
            return []
        held = [p for p in open_positions(module_id)
                if p.get("market_id") in {b["condition_id"] for b in auction["brackets"]}]
        resting = (get_supabase().table("orders").select("bracket")
                   .eq("module_id", module_id).eq("side", "BUY")
                   .in_("status", ["submitted", "open"]).execute().data) or []
        resting_brackets = {r["bracket"] for r in resting}
        bankroll = module_bankroll(module_id)
        signals = decision.build_entry_signals(module_id, auction, cfg, bankroll,
                                               held, resting_brackets)
        signals += decision.build_salvage_exits(module_id, auction, cfg, held)
        log.info("s2: %s count=%s -> %d signal(s)", auction["slug"],
                 auction["count"], len(signals))
        return signals
