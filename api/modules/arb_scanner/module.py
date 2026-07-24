"""Complete-set + complement-pair arb scanner (fixed 2026-07-24).

Scans tag-972 events for two structural arbs: (A) complete-set taker (sum of YES asks
< $1) and (B) complement-pair maker (rest YES-bid + NO-bid summing < $1). Both are
locked-below-$1 structural edges, not directional bets - so they opt out of the 2%
edge floor via the metadata gate override (the reason this module never fired before).
See module_config.py for the thesis.
"""
import logging

from api.modules.arb_scanner import data
from api.modules.arb_scanner.module_config import (get_module_config,
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

    def _gate(self, cfg: dict) -> dict:
        return {"min_edge": cfg.get("gate_min_edge", 0.0),
                "spread_tol": cfg.get("gate_spread_tol", 0.30)}

    async def _evaluate_async(self, module_id: str) -> list:
        cfg = self.get_config(module_id)
        events = data.scan_tag_events(cfg["scan_tag"], cfg["scan_limit"])
        signals: list[Signal] = []
        gate = self._gate(cfg)
        set_found = pair_found = 0

        for ev in events:
            if len(signals) >= cfg["max_signals"]:
                break
            mkts = ev["markets"]
            slug = ev.get("slug") or ""

            # ---- A) complete-set taker: every leg's YES ask sums below $1 ----
            asks = [m for m in mkts if m["yes_ask"] is not None]
            if 2 <= len(asks) <= cfg["max_legs"] and len(asks) == len(mkts):
                ask_sum = sum(m["yes_ask"] for m in asks)
                if ask_sum < 1.0 - cfg["set_margin"]:
                    set_found += 1
                    profit = 1.0 - ask_sum
                    log.warning("COMPLETE-SET ARB %s ask_sum=%.4f profit=%.4f", slug, ask_sum, profit)
                    stake = cfg["per_arb_max_usd"]
                    for m in asks:
                        price = snap_price(m["yes_ask"], m["tick"])
                        size = int((stake / len(asks)) / price) if price > 0 else 0
                        if size < 5 or size * price < cfg["min_notional"]:
                            continue
                        signals.append(Signal(
                            module_id=module_id, market_id=m["condition_id"], bracket=m["label"],
                            side="BUY", price=price, size=size, token_id=m["yes_token"],
                            fair_value=1.0 / len(asks), edge=round(profit / len(asks), 4),
                            auction_slug=slug, spread=0.0, best_bid=m["yes_bid"], best_ask=m["yes_ask"],
                            metadata={"strategy": "arb_scanner", "arb_type": "complete_set_taker",
                                      "ask_sum": round(ask_sum, 4), "set_profit": round(profit, 4),
                                      "legs": len(asks), **gate}))

            # ---- B) complement-pair maker: wide YES spread => rest both bids < $1 ----
            for m in mkts:
                if len(signals) >= cfg["max_signals"]:
                    break
                yb, ya, tick = m["yes_bid"], m["yes_ask"], m["tick"]
                if yb is None or ya is None:
                    continue
                # our quotes: one tick better than each side's best. NO_bid mirrors YES.
                q_yes = snap_price(yb + tick, tick)          # bid YES
                q_no = snap_price((1.0 - ya) + tick, tick)   # bid NO = 1 - YES_ask + tick
                pair = q_yes + q_no
                locked = 1.0 - pair
                if locked < cfg["pair_margin"]:
                    continue
                if not (cfg["min_leg_price"] <= q_yes <= cfg["max_leg_price"] and
                        cfg["min_leg_price"] <= q_no <= cfg["max_leg_price"]):
                    continue
                pair_found += 1
                shares = int(cfg["per_arb_max_usd"] / pair) if pair > 0 else 0
                if shares < 5 or shares * q_yes < cfg["min_notional"] or shares * q_no < cfg["min_notional"]:
                    continue
                for tok, px, leg in ((m["yes_token"], q_yes, "YES"), (m["no_token"], q_no, "NO")):
                    signals.append(Signal(
                        module_id=module_id, market_id=m["condition_id"], bracket=m["label"],
                        side="BUY", price=px, size=shares, token_id=tok,
                        fair_value=None, edge=round(locked / 2, 4), auction_slug=slug,
                        spread=round(ya - yb, 4), best_bid=yb, best_ask=ya,
                        metadata={"strategy": "arb_scanner", "arb_type": "complement_pair_maker",
                                  "pair_leg": leg, "pair_sum": round(pair, 4),
                                  "locked_profit": round(locked, 4), **gate}))
        log.info("arb_scanner: %d events, %d complete-set, %d complement-pair -> %d signal(s)",
                 len(events), set_found, pair_found, len(signals))
        return signals
