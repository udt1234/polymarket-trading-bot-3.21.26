"""Complete-set arb scanner (BUILD_SPEC F4 S4, the one riskless edge).

Scans multi-outcome events for a set of outcome asks summing below $1. When
found, exactly one leg pays $1, so buying the whole set is riskless profit. v1
is PAPER: detect + emit BUY signals for every leg + log the opportunity. Live
atomic execution (all legs or none) is gated separately - a partial fill leaves
directional risk.
"""
import logging

from api.modules.arb_scanner import data
from api.modules.arb_scanner.module_config import (DEFAULT_CONFIG,
                                                   get_module_config,
                                                   save_module_config)
from api.modules.base import BaseModule
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class ArbScannerModule(BaseModule):
    name = "arb_scanner"

    def get_handle(self) -> str:
        return ""

    def get_platform(self) -> str:
        return "polymarket"

    def get_display_keywords(self) -> list[str]:
        return ["arb", "scanner"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        cfg = self.get_config(module_id)
        events = data.scan_tag_events(cfg["scan_tag_id"] if "scan_tag_id" in cfg
                                      else cfg["scan_tweet_tag"])
        signals, found = [], 0
        for ev in events:
            legs = ev["legs"]
            if not (2 <= len(legs) <= cfg["max_legs"]):
                continue
            ask_sum = sum(l["ask"] for l in legs)
            if ask_sum > 1.0 - cfg["min_profit"]:
                continue
            found += 1
            profit = 1.0 - ask_sum
            log.warning("ARB: %s legs=%d ask_sum=%.4f profit=%.4f/$1 (%s)",
                        ev["slug"], len(legs), ask_sum, profit, ev["title"])
            # size the set: per_arb_max_usd across the legs, equal shares
            stake = cfg["per_arb_max_usd"]
            for l in legs:
                price = snap_price(l["ask"], l["tick"])
                size = int((stake / len(legs)) / price) if price > 0 else 0
                if size < 5 or size * price < 1.0:
                    continue
                signals.append(Signal(
                    module_id=module_id, market_id=l["condition_id"],
                    bracket=l["label"], side="BUY", price=price, size=size,
                    token_id=l["token"], fair_value=1.0 / len(legs),
                    edge=profit / len(legs), auction_slug=ev["slug"],
                    spread=0.0, best_bid=None, best_ask=l["ask"],
                    metadata={"strategy": "arb_scanner", "ask_sum": round(ask_sum, 4),
                              "set_profit": round(profit, 4), "legs": len(legs),
                              "taker_arb": True}))
        log.info("arb_scanner: scanned %d events, %d arbs, %d leg-signals",
                 len(events), found, len(signals))
        return signals
