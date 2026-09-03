"""Elon last-6h mean-reversion (paper test, 2026-07-24).

Fades LATE up-spikes on brackets the LOCKED pace model classifies as NON-winners,
as a MAKER (buy the NO token). Quant core = Ornstein-Uhlenbeck: only fade a bracket
whose price series is genuinely mean-reverting (theta>0, half-life in band) AND whose
current price is z-sigma above its OU mean. The pace gate is the safety valve - never
fade a bracket the model thinks can win (a real winner runs to $1 against the fade).
See module_config.py for the full thesis + why blind reversion is dead.
"""
import logging
from datetime import datetime

from api.modules.base import BaseModule
from api.modules.elon_reversion import data
from api.modules.elon_reversion.module_config import (get_module_config,
                                                      save_module_config)
from api.modules.shared import fair_value, ou, windows
from api.modules.shared.config_store import module_bankroll
from api.modules.shared.tweet_count import current_count, fetch_tracking_for_slug
from api.services.clob import snap_price
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class Module(BaseModule):
    name = "elon_reversion"

    def get_handle(self) -> str:
        return "elonmusk"

    def get_platform(self) -> str:
        return "x"

    def get_display_keywords(self) -> list[str]:
        return ["reversion", "mean revert", "elon reversion"]

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
        now = datetime.now(windows.ET)
        remaining_h = (end - now).total_seconds() / 3600.0
        # GATE 1: only act inside the final N hours of the auction
        if not (0 < remaining_h <= cfg["window_hours"]):
            return []
        elapsed_frac = windows.elapsed_fraction(start, end, now)
        dtype = windows.duration_type(start, end)

        # locked pace projection + per-bracket win probability (the safety gate)
        tracking = fetch_tracking_for_slug(slug)
        count = current_count(tracking["id"]) if tracking else None
        if count is None:
            return []  # no count -> cannot pace-gate -> do not trade (fail closed)
        pm, ps = fair_value.VALIDATED_PRIORS.get(dtype, fair_value.VALIDATED_PRIORS["2-day"])
        proj = fair_value.projection(count, elapsed_frac, pm, ps,
                                     duration_type=dtype, remaining_hours=remaining_h)
        books = data.bracket_books(ev)
        labels = [b["label"] for b in books]
        win_prob = fair_value.bracket_distribution(proj, count, labels, remaining_h)

        bankroll = module_bankroll(module_id)
        signals = []
        for b in books:
            wp = win_prob.get(b["label"], 1.0)
            # GATE 2 (pace): only fade brackets the model says are NON-winners
            if wp > cfg["max_pace_prob"]:
                continue
            yes_price = b["best_bid"] if b["best_bid"] is not None else b["best_ask"]
            if yes_price is None:
                continue
            # GATE 3 (OU): the series must be mean-reverting and CURRENTLY spiked up
            series = data.price_series(b["token"])
            if len(series) < cfg["min_obs"]:
                continue
            fit = ou.fit_ou(series, dt_minutes=1.0)
            if not fit:
                continue  # theta<=0 -> trending, not reverting -> skip
            hl = fit["halflife_min"]
            if not (cfg["min_halflife_min"] <= hl <= cfg["max_halflife_min"]):
                continue
            if fit["theta"] < cfg["min_theta"]:
                continue
            z = ou.zscore(yes_price, fit)
            if z is None or z < cfg["z_entry"]:
                continue  # not spiked far enough above its own mean

            # FADE = buy the NO token as a resting post-only maker bid, one tick
            # inside the NO book. NO fair value ~= 1 - OU_mean(yes).
            nb = data.no_token_book(b["condition_id"], b["no_token"])
            if not nb or nb.get("best_ask") is None:
                continue
            no_fair = max(0.0, min(1.0, 1.0 - fit["mu"]))
            price = snap_price(min(no_fair, (nb["best_bid"] or 0) + b["tick"]), b["tick"])
            if nb["best_ask"] is not None and price >= nb["best_ask"]:
                price = snap_price(nb["best_ask"] - b["tick"], b["tick"])
            if price < cfg["min_no_price"] or price > cfg["max_no_price"]:
                continue
            size = int((cfg["size_pct"] * bankroll) / price) if price > 0 else 0
            if size < 5 or size * price < cfg["min_notional"]:
                continue
            signals.append(Signal(
                module_id=module_id, market_id=b["condition_id"], bracket=b["label"],
                side="BUY", price=price, size=size, token_id=b["no_token"],
                fair_value=no_fair, edge=round(no_fair - price, 4), auction_slug=slug,
                spread=round((nb["best_ask"] - (nb["best_bid"] or nb["best_ask"])), 4),
                best_bid=nb.get("best_bid"), best_ask=nb.get("best_ask"),
                metadata={"strategy": "elon_reversion", "fade_of_bracket": b["label"],
                          "yes_price": round(yes_price, 4), "ou_mu": round(fit["mu"], 4),
                          "z": round(z, 2), "halflife_min": round(hl, 1),
                          "pace_win_prob": round(wp, 4), "remaining_h": round(remaining_h, 2),
                          "min_edge": cfg.get("gate_min_edge", 0.0),
                          "spread_tol": cfg.get("gate_spread_tol", 0.15)}))
            if len(signals) >= cfg["max_concurrent"]:
                break
        log.info("elon_reversion: rem=%.1fh brackets=%d -> %d fade signal(s)",
                 remaining_h, len(books), len(signals))
        return signals
