"""Sports garbage-time sweep module (BUILD_SPEC F1, backtest-validated 2026-07-10).

Rest deep-discount post-only bids on DECIDED sports favorites (bid >= 0.97) and
fill for $0 maker fee as retail dumps the lost side; hold winners to resolution,
stop-loss out of the ~1-3% collapse (comeback) games. Runs on the slow path
(5-min cycle) - this is a minutes-long endgame play, no speed race needed.
"""
import logging

from api.modules.base import BaseModule
from api.modules.sports_sweep import data, decision
from api.modules.sports_sweep.module_config import (DEFAULT_CONFIG,
                                                    get_module_config,
                                                    save_module_config)

log = logging.getLogger(__name__)


class SportsSweepModule(BaseModule):
    name = "sports_sweep"

    def get_handle(self) -> str:
        return ""  # no social handle - market-driven

    def get_platform(self) -> str:
        return "polymarket"

    def get_display_keywords(self) -> list[str]:
        return ["sports", "sweep"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    async def _evaluate_async(self, module_id: str) -> list:
        from api.dependencies import get_supabase
        from api.services.position_manager import open_positions

        cfg = self.get_config(module_id)
        games = data.live_games([int(s) for s in cfg["series_ids"]])
        if not games:
            return []

        game_by_token = {s["token"]: g for g in games for s in g["sides"]}
        held = open_positions(module_id)
        held_tokens = {p.get("token_id") for p in held}

        sb = get_supabase()
        resting = (sb.table("orders").select("token_id")
                   .eq("module_id", module_id).eq("side", "BUY")
                   .in_("status", ["submitted", "open"]).execute().data) or []
        resting_tokens = {r["token_id"] for r in resting}

        signals = []
        # exits FIRST (E8): stop-loss the fading games
        signals += decision.build_stop_exits(module_id, held, game_by_token, cfg)

        # entries: cap concurrent games
        active_games = len({p.get("market_id") for p in held} |
                           {game_by_token[t]["condition_id"] for t in resting_tokens
                            if t in game_by_token})
        for g in games:
            if active_games >= cfg["max_concurrent_games"]:
                break
            fav = data.decided_favorite(g, cfg["decided_bid_threshold"])
            if not fav or fav["best_ask"] is None:
                continue
            new = decision.build_entry_bids(module_id, g, fav, cfg,
                                            resting_tokens, held_tokens)
            if new:
                signals += new
                active_games += 1

        log.info("sports_sweep: %d live games, %d decided, %d signal(s)",
                 len(games),
                 sum(1 for g in games if data.decided_favorite(g, cfg["decided_bid_threshold"])),
                 len(signals))
        return signals
