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

        # live game state (MLB) - fetched once per cycle, reused for exits + entries
        states = None
        game_state = None
        if cfg.get("use_game_state", True):
            try:
                from api.modules.shared import game_state
                states = game_state.mlb_live_states()
            except Exception:
                log.exception("game_state fetch failed")

        signals = []
        # exits FIRST (E8). Game-state exit: sell a held favorite whose live
        # win prob collapsed (cuts the fat-tail without price-noise whipsaw).
        if states and game_state and cfg.get("gamestate_exit_enabled", True):
            win_probs: dict[str, float] = {}
            for p in held:
                if not p.get("bracket"):
                    continue
                try:
                    wp = game_state.team_win_prob(p["bracket"], states)
                except Exception:
                    wp = None
                if wp is not None:
                    win_probs[p.get("token_id")] = wp
            signals += decision.build_gamestate_exits(module_id, held, win_probs,
                                                      game_by_token, cfg)
        # legacy price stop-loss (default OFF - backfires on price noise)
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
            # game-state gate: only sweep truly-decided, low-leverage spots, and
            # price the ladder off the live win probability (fair_override).
            fair_override = None
            if cfg.get("use_game_state", True) and g["slug"].startswith("mlb-"):
                from api.modules.shared import game_state
                ev = game_state.evaluate_game(g["slug"], fav["outcome"], states)
                if not ev["ok"]:
                    if ev["reason"] in ("no_state", "unmatched_team", "bad_slug", "date_mismatch") and not cfg.get("require_game_state", False):
                        pass  # fall back to price-only (flat decided_winrate)
                    else:
                        log.info("sports_sweep skip %s: %s", g["slug"], ev["reason"])
                        continue
                elif cfg.get("use_win_prob", True):
                    fair_override = ev["p_true"]
            new = decision.build_entry_bids(module_id, g, fav, cfg,
                                            resting_tokens, held_tokens,
                                            fair_override=fair_override)
            if new:
                signals += new
                active_games += 1

        log.info("sports_sweep: %d live games, %d decided, %d signal(s)",
                 len(games),
                 sum(1 for g in games if data.decided_favorite(g, cfg["decided_bid_threshold"])),
                 len(signals))
        return signals
