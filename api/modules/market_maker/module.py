"""Market maker (paper test, 2026-07-24). Two-sided quoting across Elon / White House
tweet brackets + weather reward markets. Rest a BID below mid; when we hold inventory,
rest an ASK above cost to capture the spread. Inventory-skewed to defend adverse
selection. See module_config.py for the thesis (thin on Elon, real on weather)."""
import logging

from api.modules.base import BaseModule
from api.modules.market_maker import data
from api.modules.market_maker.module_config import (get_module_config,
                                                    save_module_config)
from api.modules.shared import market_making
from api.modules.shared.config_store import module_bankroll
from api.services.clob import snap_price
from api.services.position_manager import open_positions
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)

C = 0.01  # cents -> price


class Module(BaseModule):
    name = "market_maker"

    def get_handle(self) -> str:
        return ""

    def get_platform(self) -> str:
        return "polymarket"

    def get_display_keywords(self) -> list[str]:
        return ["market maker", "market making", "mm"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        cfg = self.get_config(module_id)
        universe = data.get_universe(cfg)
        if not universe:
            return []
        bankroll = module_bankroll(module_id)
        # our current inventory per token (to skew + to know if we can offer)
        held = {p.get("token_id"): p for p in open_positions(module_id)}
        half = cfg["half_spread_cents"] * C
        skew = cfg["skew_cents"] * C
        max_inv = cfg["max_inventory_usd"]
        signals: list[Signal] = []

        min_width = cfg.get("min_book_spread_cents", 0.0) * C
        skipped_tight = 0
        for t in universe:
            mid, tick = t["mid"], t["tick"]
            if not (cfg["min_price"] <= mid <= cfg["max_price"]):
                continue
            # Width gate: no spread to capture => do not quote (see config).
            # Applies to the BID side only; an ASK that offers inventory we
            # already hold must still be allowed to work out of the position.
            bb, ba = t.get("best_bid"), t.get("best_ask")
            book_width = (ba - bb) if (bb is not None and ba is not None) else None
            too_tight = book_width is not None and book_width < min_width
            if too_tight:
                skipped_tight += 1
            pos = held.get(t["token"])
            held_notional = (float(pos["size"]) * float(pos["avg_price"])) if pos else 0.0
            inv_frac = held_notional / max_inv if max_inv > 0 else 1.0

            q = market_making.quote(mid, half, tick, inv_frac=inv_frac, skew=skew,
                                    best_bid=t["best_bid"], best_ask=t["best_ask"])

            # BID side (accumulate) - only if room + inside reward band (if any)
            if (not too_tight and q["bid"] is not None
                    and cfg["min_price"] <= q["bid"] <= cfg["max_price"]):
                if market_making.reward_band_ok(q["bid"], mid, t.get("rewards_max_spread")):
                    size = int(cfg["quote_size_usd"] / q["bid"]) if q["bid"] > 0 else 0
                    if size >= 5 and size * q["bid"] >= cfg["min_notional"]:
                        signals.append(self._mk(module_id, t, "BUY", q["bid"], size,
                                                mid, inv_frac, pos))

            # ASK side (offer inventory) - only if we HOLD some, above cost + markup
            if pos and float(pos["size"]) >= 5:
                cost = float(pos["avg_price"])
                floor = snap_price(cost + cfg["min_markup_cents"] * C, tick)
                ask = max(q["ask"], floor)
                if t["best_bid"] is not None and ask <= t["best_bid"]:
                    ask = snap_price(t["best_bid"] + tick, tick)
                if cfg["min_price"] <= ask <= cfg["max_price"]:
                    signals.append(self._mk(module_id, t, "SELL", ask,
                                            int(float(pos["size"])), mid, inv_frac, pos,
                                            is_exit=True, position_id=pos["id"]))
        log.info("market_maker: universe=%d (%d too tight to make) -> %d quote signal(s)",
                 len(universe), skipped_tight, len(signals))
        return signals

    def _mk(self, module_id, t, side, price, size, mid, inv_frac, pos,
            is_exit=False, position_id=None) -> Signal:
        meta = {"strategy": "market_maker", "family": t["family"], "mid": round(mid, 4),
                "inv_frac": round(inv_frac, 3), "quote_side": side,
                "min_edge": 0.0, "spread_tol": 0.40}
        if position_id:
            meta["position_id"] = position_id
        return Signal(
            module_id=module_id, market_id=t["condition_id"], bracket=t["label"],
            side=side, price=price, size=size, token_id=t["token"],
            fair_value=mid, edge=round(abs(mid - price), 4), auction_slug="",
            spread=round((t["best_ask"] - t["best_bid"]), 4)
            if (t["best_ask"] is not None and t["best_bid"] is not None) else None,
            best_bid=t["best_bid"], best_ask=t["best_ask"], is_exit=is_exit, metadata=meta)
