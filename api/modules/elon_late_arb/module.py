"""Elon last-6h arbitrage scanner (paper test, 2026-07-24).

Scans the live Elon tweet-count auction in its final window for two arbs:
  A) complete-set TAKER arb (sum of asks over all brackets < $1 - margin), the one
     allowed taker exception; and
  B) complement-pair MAKER arb (rest YES-bid + NO-bid on one bracket summing < $1).
See module_config.py for the full thesis. Both are structural (locked below $1), not
directional bets.
"""
import logging
from datetime import datetime

from api.modules.base import BaseModule
from api.modules.elon_late_arb import data
from api.modules.elon_late_arb.module_config import (get_module_config,
                                                     save_module_config)
from api.modules.shared import windows
from api.modules.shared.config_store import module_bankroll
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class Module(BaseModule):
    name = "elon_late_arb"

    def get_handle(self) -> str:
        return "elonmusk"

    def get_platform(self) -> str:
        return "x"

    def get_display_keywords(self) -> list[str]:
        return ["late arb", "elon arb", "arbitrage 6h"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        cfg = self.get_config(module_id)
        ev = data.live_elon_event()
        if not ev:
            return []
        slug = ev.get("slug") or ""
        win = windows.parse_slug_window(slug)
        if not win:
            return []
        start, end = win
        remaining_h = (end - datetime.now(windows.ET)).total_seconds() / 3600.0
        if not (0 < remaining_h <= cfg["window_hours"]):
            return []

        books = data.bracket_full_books(ev)
        if len(books) < 2:
            return []
        bankroll = module_bankroll(module_id)
        signals: list[Signal] = []

        # ---- A) complete-set TAKER arb: sum of every bracket's YES ask < 1 - margin ----
        asks = [(b, b["yes_ask"]) for b in books if b["yes_ask"] is not None]
        if len(asks) == len(books) and asks:
            ask_sum = sum(a for _, a in asks)
            if ask_sum < 1.0 - cfg["set_margin"]:
                profit = 1.0 - ask_sum
                log.warning("COMPLETE-SET ARB: %s ask_sum=%.4f profit=%.4f/$1",
                            slug, ask_sum, profit)
                stake = cfg["per_arb_max_usd"]
                for b, ask in asks:
                    price = snap_price(ask, b["tick"])
                    size = int((stake / len(asks)) / price) if price > 0 else 0
                    if size < 5 or size * price < cfg["min_notional"]:
                        continue
                    signals.append(Signal(
                        module_id=module_id, market_id=b["condition_id"],
                        bracket=b["label"], side="BUY", price=price, size=size,
                        token_id=b["yes_token"], fair_value=1.0 / len(asks),
                        edge=round(profit / len(asks), 4), auction_slug=slug,
                        spread=0.0, best_bid=b["yes_bid"], best_ask=ask,
                        metadata={"strategy": "elon_late_arb", "arb_type": "complete_set_taker",
                                  "ask_sum": round(ask_sum, 4), "set_profit": round(profit, 4),
                                  "legs": len(asks), "remaining_h": round(remaining_h, 2),
                                  "min_edge": cfg.get("gate_min_edge", 0.0),
                                  "spread_tol": cfg.get("gate_spread_tol", 0.20)}))

        # ---- B) complement-pair MAKER arb per bracket: rest YES-bid + NO-bid < 1 ----
        for b in books:
            if len(signals) >= cfg["max_concurrent"]:
                break
            if b["yes_bid"] is None or b["no_bid"] is None:
                continue
            # target: quote one tick above each side's current best bid, only if the
            # PAIR sum is safely below $1 (locked profit if both fill)
            yb = snap_price(b["yes_bid"] + b["tick"], b["tick"])
            nb = snap_price(b["no_bid"] + b["tick"], b["tick"])
            # never cross our own book (post-only would reject)
            if b["yes_ask"] is not None and yb >= b["yes_ask"]:
                yb = snap_price(b["yes_ask"] - b["tick"], b["tick"])
            if b["no_ask"] is not None and nb >= b["no_ask"]:
                nb = snap_price(b["no_ask"] - b["tick"], b["tick"])
            pair = yb + nb
            if pair >= 1.0 - cfg["pair_margin"]:
                continue
            if not (cfg["min_leg_price"] <= yb <= cfg["max_leg_price"] and
                    cfg["min_leg_price"] <= nb <= cfg["max_leg_price"]):
                continue
            locked = 1.0 - pair
            stake = cfg["per_arb_max_usd"]
            # equal SHARES on both legs (a matched pair pays exactly $1)
            shares = int((stake / pair)) if pair > 0 else 0
            if shares < 5 or shares * yb < cfg["min_notional"] or shares * nb < cfg["min_notional"]:
                continue
            for tok, px, leg in ((b["yes_token"], yb, "YES"), (b["no_token"], nb, "NO")):
                signals.append(Signal(
                    module_id=module_id, market_id=b["condition_id"], bracket=b["label"],
                    side="BUY", price=px, size=shares, token_id=tok,
                    fair_value=None, edge=round(locked / 2, 4), auction_slug=slug,
                    spread=None, best_bid=None, best_ask=None,
                    metadata={"strategy": "elon_late_arb", "arb_type": "complement_pair_maker",
                              "pair_leg": leg, "pair_sum": round(pair, 4),
                              "locked_profit": round(locked, 4), "remaining_h": round(remaining_h, 2),
                              "min_edge": cfg.get("gate_min_edge", 0.0),
                              "spread_tol": cfg.get("gate_spread_tol", 0.20)}))
        log.info("elon_late_arb: rem=%.1fh brackets=%d -> %d arb leg-signal(s)",
                 remaining_h, len(books), len(signals))
        return signals
