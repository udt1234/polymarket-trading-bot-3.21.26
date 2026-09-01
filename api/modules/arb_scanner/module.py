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

    def _orphan_exits(self, module_id: str, cfg: dict) -> list[Signal]:
        """Quote OUT of any leg we hold with no partner leg beside it.

        A complement pair is riskless only when both legs fill. A lone leg is a
        directional position that nothing else in this module ever closes, so it
        holds its notional against the module budget until the market resolves
        (four of them held $384 for 39 days). Exits are post-only makers one tick
        inside the ask - MAKER-ONLY is locked, so we never cross to get out."""
        from datetime import datetime, timedelta, timezone

        from api.services.position_manager import open_positions

        cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["orphan_unwind_hours"])
        positions = open_positions(module_id)
        by_market: dict[str, list[dict]] = {}
        for p in positions:
            by_market.setdefault(p.get("market_id") or "", []).append(p)

        exits: list[Signal] = []
        for p in positions:
            # both legs of the same market held => the pair is complete, hold it
            if len({q.get("token_id") for q in by_market[p.get("market_id") or ""]}) > 1:
                continue
            opened = p.get("opened_at") or p.get("created_at")
            if not opened:
                continue
            if datetime.fromisoformat(str(opened).replace("Z", "+00:00")) > cutoff:
                continue
            size = float(p.get("size") or 0)
            if size < 1:
                continue
            book = data.token_book(p.get("token_id") or "")
            bid, ask = book["best_bid"], book["best_ask"]
            if ask is None:
                continue
            tick = 0.01
            price = round(max(tick, ask - tick), 4)
            if bid is not None and price <= bid:
                price = round(bid + tick, 4)   # never cross: stay a maker
            if not (0 < price < 1):
                continue
            exits.append(Signal(
                module_id=module_id, market_id=p.get("market_id") or "",
                bracket=p.get("bracket") or "", side="SELL", price=price, size=size,
                token_id=p.get("token_id") or "", fair_value=None, edge=None,
                spread=round(ask - bid, 4) if bid is not None else None,
                best_bid=bid, best_ask=ask, is_exit=True,
                metadata={"strategy": "arb_scanner", "arb_type": "orphan_unwind",
                          "position_id": p.get("id"), "opened_at": str(opened),
                          "entry_price": p.get("avg_price")}))
        if exits:
            log.warning("arb_scanner: unwinding %d orphaned leg(s)", len(exits))
        return exits

    async def _evaluate_async(self, module_id: str) -> list:
        from api.services.position_manager import open_positions

        cfg = self.get_config(module_id)
        events = data.scan_tag_events(cfg["scan_tag"], cfg["scan_limit"])
        signals: list[Signal] = self._orphan_exits(module_id, cfg)
        gate = self._gate(cfg)
        set_found = pair_found = 0

        # Notional already held per leg. The duplicate-order guard only blocks a
        # RESTING order, so without this the same leg is re-bought every cycle and
        # compounds without limit (see max_held_usd_per_leg in module_config).
        held_usd: dict[tuple[str, str], float] = {}
        for p in open_positions(module_id):
            key = (p.get("market_id") or "", p.get("token_id") or "")
            held_usd[key] = held_usd.get(key, 0.0) + (
                float(p.get("size") or 0) * float(p.get("avg_price") or 0))
        cap = cfg["max_held_usd_per_leg"]

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
                        if held_usd.get((m["condition_id"], m["yes_token"]), 0.0) >= cap:
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
                    if held_usd.get((m["condition_id"], tok), 0.0) >= cap:
                        continue
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
