"""Mirror-copytrader (Option A). Follow proven whales' BUYS as a resting maker,
sized down, across ANY market. Unlike the tweet-scoped `copytrader`, this mirrors
their directional picks directly. MAKER-ONLY: rests a post-only bid at/below the
whale's entry - we follow cheaper or not at all, so we are never adversely
selected by taking their exact fill. Multi-whale, gated on each whale's live-book
ROI (a whale riding losers is benched)."""
import logging

from api.modules.base import BaseModule
from api.modules.mirror_trader import data
from api.modules.mirror_trader.module_config import (DEFAULT_CONFIG,
                                                    get_module_config,
                                                    save_module_config)
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class MirrorTraderModule(BaseModule):
    name = "mirror_trader"

    def get_handle(self) -> str:
        return ""

    def get_platform(self) -> str:
        return "polymarket"

    def get_display_keywords(self) -> list[str]:
        return ["mirror", "copy", "whale"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        from api.dependencies import get_supabase
        from api.modules.shared import whales
        from api.modules.shared.config_store import module_bankroll
        from api.services.position_manager import open_positions

        cfg = self.get_config(module_id)

        # only mirror whales whose LIVE book is currently green
        active = []
        for w in cfg["whale_wallets"]:
            roi = whales.whale_roi(w)
            if roi is None or roi < cfg["whale_perf_gate_roi"]:
                log.info("mirror_trader: whale %s benched (roi=%s)", w[:10], roi)
                continue
            active.append((w, roi))
        if not active:
            return []

        # collect their recent BUYS; dedup by (market, token) keeping the CHEAPEST
        # whale entry seen (we want to rest at/below the best price they paid)
        picks: dict[tuple, dict] = {}
        for w, roi in active:
            for t in whales.whale_buys(w, cfg["lookback_hours"]):
                cid = t.get("conditionId")
                asset = t.get("asset")
                price = float(t.get("price") or 0)
                if not cid or not asset or price <= 0 or price > cfg["max_price"]:
                    continue
                key = (cid, asset)
                if key not in picks or price < picks[key]["price"]:
                    picks[key] = {"price": price, "whale": w, "roi": roi}

        sb = get_supabase()
        resting = (sb.table("orders").select("token_id").eq("module_id", module_id)
                   .eq("side", "BUY")
                   .in_("status", ["submitted", "open", "partially_filled"])
                   .execute().data) or []
        resting_tokens = {r["token_id"] for r in resting}
        held_tokens = {p.get("token_id") for p in open_positions(module_id)}
        bankroll = module_bankroll(module_id)

        signals: list[Signal] = []
        for (cid, asset), info in picks.items():
            if len(signals) >= cfg["max_markets"]:
                break
            if asset in resting_tokens or asset in held_tokens:
                continue
            book = data.token_book(cid, asset)
            if not book:
                continue
            # maker bid at/below the whale's entry, kept strictly below the ask
            price = snap_price(min(info["price"], book["best_bid"] + book["tick"]),
                               book["tick"])
            if book["best_ask"] is not None and price >= book["best_ask"]:
                price = snap_price(book["best_ask"] - book["tick"], book["tick"])
            if price < book["tick"] or price > cfg["max_price"]:
                continue
            size = int((cfg["size_pct"] * bankroll) / price) if price > 0 else 0
            if size < 5 or size * price < cfg["min_notional"]:
                continue
            signals.append(Signal(
                module_id=module_id, market_id=cid, bracket=book["outcome"],
                side="BUY", price=price, size=size, token_id=asset,
                fair_value=info["price"], edge=round(info["price"] - price, 4),
                auction_slug="", spread=round(book["best_ask"] - book["best_bid"], 4),
                best_bid=book["best_bid"], best_ask=book["best_ask"],
                metadata={"strategy": "mirror_trader", "whale": info["whale"][:10],
                          "whale_roi": round(info["roi"], 4),
                          "whale_price": info["price"],
                          # the "edge" here is following a proven-green whale, not
                          # a modeled mispricing, so the 2% directional-edge floor
                          # does not apply. The whale_perf_gate_roi is the real
                          # gate (enforced in the module). Allow a wider spread
                          # since we copy across arbitrary markets.
                          "min_edge": cfg.get("gate_min_edge", 0.0),
                          "spread_tol": cfg.get("gate_spread_tol", 0.15)}))
        log.info("mirror_trader: %d whale(s) green, %d fresh picks -> %d signal(s)",
                 len(active), len(picks), len(signals))
        return signals
