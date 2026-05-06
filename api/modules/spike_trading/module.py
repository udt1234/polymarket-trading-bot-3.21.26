"""Spike Trading module — buy lottery tickets cheap, sell on tier ladder,
liquidate on plummet trigger.

Strategy: see _ImportantConfigFiles/spike_trading_module_spec.md.

Cycle (every 5 min via engine scheduler):
  1. Discover active 2-day auctions matching the configured handle + bracket.
  2. For each auction:
     a. If no open position → emit BUY signals at the limit-buy ladder.
     b. If open position → fetch current state (cum_tweets, hours_to_close,
        latest price) and run the decision classifier.
        - SELL-NOW   → emit a market-sell signal at best_bid (force fill).
        - HOLD       → no-op (let limit ladder fill organically).
        - HOLD-LIGHT → no-op (same as HOLD; soft hold for now).
        - SELL       → no-op (default; ladder runs).
     c. Snapshot the (state, decision) into spike_state_snapshots for backtest.

The module emits standard Signal objects so the existing executor + risk
manager pipelines handle order placement. Spike-specific state lives in the
spike_positions table (migration 010).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from api.modules.base import BaseModule
from api.services.risk_manager import Signal
from api.dependencies import get_supabase
from api.modules.spike_trading.module_config import get_module_config
from api.modules.spike_trading.data import (
    fetch_active_short_window_trackings,
    fetch_market_for_tracking,
    fetch_cumulative_tweets,
    hours_to_close,
    _resolve_xtracker_id_for_window,
)
from api.modules.spike_trading.decision import (
    PositionState,
    classify_decision,
    classify_decision_v2,
    should_market_sell,
    should_cancel_aggressive_tiers,
    adaptive_buy_price,
    trailing_stop_price,
    slow_bleed_sell_price,
)
from api.modules.spike_trading.strategies import get_strategy, all_strategy_names
from api.modules.spike_trading.strategies.base import AuctionState

log = logging.getLogger(__name__)


class SpikeTradingModule(BaseModule):
    name = "spike_trading"
    enabled = True

    # ------------------------------------------------------------------
    # BaseModule contract
    # ------------------------------------------------------------------

    def evaluate(self) -> list[Signal]:
        """Sync entry point used by the engine cycle. Wraps the async impl."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Engine cycle is async-unfriendly — run in a worker thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(lambda: asyncio.run(self._evaluate_async())).result(timeout=60)
            return loop.run_until_complete(self._evaluate_async())
        except RuntimeError:
            return asyncio.run(self._evaluate_async())

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "status": "active" if self.enabled else "paused",
            "strategy": "spike_trading_v1",
        }

    def get_display_keywords(self) -> list[str]:
        # Match DB row name 'Spike Trading' (lowercase 'spike trading')
        return ["spike trading", "spike_trading", "spike"]

    def _first_enabled_auction(self) -> dict | None:
        """First enabled auction_type. Used by engine.* methods that expect
        a single handle/platform/window (post-count snapshot, dashboard
        default). Multi-auction iteration happens in _evaluate_async."""
        try:
            sb = get_supabase()
            row = sb.table("modules").select("id").eq("name", "Spike Trading").execute()
            if not row.data:
                return None
            cfg = get_module_config(row.data[0]["id"])
            for at in cfg.get("auction_types", []) or []:
                if at.get("enabled"):
                    return at
            # No enabled auction type — fall back to first regardless
            ats = cfg.get("auction_types", []) or []
            return ats[0] if ats else None
        except Exception:
            return None

    def get_handle(self) -> str:
        at = self._first_enabled_auction()
        return at.get("handle", "elonmusk") if at else "elonmusk"

    def get_platform(self) -> str:
        at = self._first_enabled_auction()
        return at.get("platform", "x") if at else "x"

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        from api.modules.spike_trading.module_config import save_module_config
        save_module_config(module_id, config)

    def get_config_schema(self) -> list[dict]:
        """Schema for the dashboard's dynamic config form.

        The new auction_types architecture means most config lives nested
        in `auction_types[].bracket_profiles[].params`. The dashboard renders
        that via a dedicated <AuctionTypesEditor /> component, NOT via the
        schema-driven form. Only module-wide knobs are exposed here.
        """
        return [
            {"key": "min_market_volume_24h", "label": "Min 24h Volume ($)", "type": "number", "section": "risk",
             "min": 0, "max": 1_000_000, "step": 100,
             "help": "Skip markets thinner than this. 0 = no filter."},
            {"key": "bracket_cap_pct_of_bankroll", "label": "Per-Cycle Bankroll Cap", "type": "number",
             "section": "risk", "min": 0.01, "max": 0.5, "step": 0.01,
             "help": "Max % of bankroll deployed per cycle (lottery sizing). Applies to each profile."},
            {"key": "max_open_positions", "label": "Max Open Positions", "type": "number", "section": "risk",
             "min": 1, "max": 20, "step": 1,
             "help": "Cap concurrent open positions across ALL enabled profiles."},
            {"key": "log_decisions_to_supabase", "label": "Log Decisions", "type": "boolean",
             "section": "advanced",
             "help": "Write spike_state_snapshots rows for backtest replay"},
        ]

    def get_strategy_metadata(self) -> list[dict]:
        """Surface strategy plugin info to the dashboard. Used by the
        AuctionTypesEditor to populate the strategy dropdown per profile.
        """
        out = []
        for name in all_strategy_names():
            cls = get_strategy(name)
            if cls is None:
                continue
            inst = cls()
            out.append({
                "name": name,
                "label": inst.display_label({}),
                "default_params": getattr(cls, "DEFAULT_PARAMS", {}),
            })
        return out

    def get_auction_window_days(self) -> float | None:
        """Window length of the FIRST enabled auction type. With multi-
        auction support, this is no longer monolithic — but the engine's
        post-count snapshot + auction-list endpoints expect a single value,
        so we return the primary enabled auction type's window. The actual
        evaluation cycle iterates over ALL enabled types."""
        at = self._first_enabled_auction()
        if at:
            try:
                return float(at.get("window_days", 2))
            except (ValueError, TypeError):
                pass
        return 2.0

    # ------------------------------------------------------------------
    # Main async logic
    # ------------------------------------------------------------------

    async def _evaluate_async(self) -> list[Signal]:
        sb = get_supabase()
        module_row = sb.table("modules").select("*").eq("name", "Spike Trading").execute()
        if not module_row.data:
            log.warning("Spike Trading module row not found in DB; create it before enabling.")
            return []
        module_db = module_row.data[0]
        module_id = module_db["id"]
        # DB status semantics:
        #   'active' or 'paper' -> evaluate normally; the engine's executor
        #     decides paper vs live based on env PAPER_MODE.
        #   'inactive' (or anything else) -> short-circuit, no signals.
        db_status = (module_db.get("status") or "").lower()
        if db_status not in ("active", "paper"):
            return []
        cfg = get_module_config(module_id)

        signals: list[Signal] = []
        auction_types = cfg.get("auction_types") or []
        if not auction_types:
            self._log(sb, module_id, "decision", "warning",
                      "No auction_types configured — module idle")
            return []

        for at in auction_types:
            if not at.get("enabled"):
                continue
            enabled_profiles = [p for p in (at.get("bracket_profiles") or []) if p.get("enabled")]
            if not enabled_profiles:
                continue
            try:
                trackings = await fetch_active_short_window_trackings(
                    handle=at.get("handle", "elonmusk"),
                    platform=at.get("platform", "x"),
                    target_window_days=at.get("window_days", 2),
                    series_slug=at.get("series_slug"),
                )
            except Exception as e:
                log.exception(f"discovery failed for {at.get('id')}: {e}")
                self._log(sb, module_id, "system", "error",
                          f"discovery failed for auction_type {at.get('id')}: {e}")
                continue
            if not trackings:
                self._log(sb, module_id, "decision", "info",
                          f"[{at.get('label', at.get('id'))}] no active {at.get('window_days')}d "
                          f"{at.get('handle')} tracking found")
                continue

            for tracking in trackings:
                tracking_id = tracking.get("id") or tracking.get("trackingId")
                if not tracking_id:
                    self._log(sb, module_id, "decision", "warning",
                              f"Skipping tracking with no id: {tracking.get('title','?')}")
                    continue
                tracking["__resolved_id"] = tracking_id

                for profile in enabled_profiles:
                    try:
                        sigs = await self._handle_auction_for_profile(
                            sb, module_id, at, profile, tracking, cfg,
                        )
                        signals.extend(sigs)
                    except Exception as e:
                        log.exception(f"profile {profile.get('label')} on {tracking.get('title')} failed: {e}")
                        self._log(sb, module_id, "system", "error",
                                  f"profile {profile.get('label')} failed: {e}")

        return signals

    # ------------------------------------------------------------------
    # Per-market state machine
    # ------------------------------------------------------------------

    async def _handle_auction_for_profile(
        self, sb, module_id: str, auction_type: dict, profile: dict,
        tracking: dict, cfg: dict,
    ) -> list[Signal]:
        """Run one (auction × bracket profile) combination through its strategy.

        Steps:
          1. Resolve the strategy plugin from profile.strategy_name.
          2. Merge profile.params over strategy.DEFAULT_PARAMS to get
             the effective param set for this profile.
          3. Fetch the bracket's market on Polymarket.
          4. Build AuctionState (tweets, hours, prices, etc.).
          5. If no open position: ask strategy.can_enter; if yes, emit buy ladder.
          6. If open position: ask strategy.classify; if SELL-NOW, emit market sell.
        """
        bracket = profile.get("bracket")
        label = profile.get("label", f"{auction_type.get('id')}/{bracket}")
        strategy_name = profile.get("strategy_name", "Cheap_Lottery_Pacing")
        strategy_cls = get_strategy(strategy_name)
        if strategy_cls is None:
            self._log(sb, module_id, "decision", "error",
                      f"[{label}] unknown strategy '{strategy_name}'. Available: {all_strategy_names()}")
            return []
        strategy = strategy_cls()
        # Defensive: future strategy plugins may forget DEFAULT_PARAMS
        defaults = getattr(strategy_cls, "DEFAULT_PARAMS", {}) or {}
        params = {**defaults, **(profile.get("params") or {})}

        # 3. Fetch market for THIS profile's bracket
        try:
            market = await fetch_market_for_tracking(tracking, bracket)
        except Exception as e:
            log.warning(f"[{label}] market fetch failed: {e}")
            return []
        if not market or not market.get("market_id"):
            self._log(sb, module_id, "decision", "info",
                      f"[{label}] no matching {bracket} market in tracking {tracking.get('id')}")
            return []
        if market.get("volume_24h", 0) < cfg.get("min_market_volume_24h", 0):
            self._log(sb, module_id, "decision", "info",
                      f"[{label}] skipping {market['market_id']}: volume below threshold")
            return []

        market_id = market["market_id"]
        end_iso = tracking.get("endDate", "")

        # Resolve cum_tweets via the source-aware path
        if tracking.get("source") == "gamma_series":
            xt_id = await _resolve_xtracker_id_for_window(
                auction_type.get("handle", "elonmusk"),
                auction_type.get("platform", "x"),
                tracking.get("startDate"), tracking.get("endDate"),
            )
            cum_tweets = await fetch_cumulative_tweets(auction_type.get("handle", "elonmusk"), xt_id) if xt_id else 0
        else:
            cum_tweets = await fetch_cumulative_tweets(
                auction_type.get("handle", "elonmusk"),
                tracking.get("__resolved_id") or tracking.get("id"),
            )

        h_to_close = hours_to_close(end_iso)
        total_hours = float(auction_type.get("window_days", 2)) * 24.0
        elapsed_hours = max(total_hours - h_to_close, 0.0)
        bid_v = float(market.get("best_bid") or 0.0)
        ask_v = float(market.get("best_ask") or 0.0)
        # Guard against fully empty book — happens on freshly-listed markets
        # before any liquidity arrives. Skip the cycle rather than build a
        # bogus AuctionState with current_price=0 (which downstream would
        # produce nonsensical pnl/pacing math).
        if bid_v <= 0 and ask_v <= 0:
            self._log(sb, module_id, "decision", "info",
                      f"[{label}] {market_id}: empty order book — skipping cycle")
            return []
        current_price = (bid_v + ask_v) / 2.0 if (bid_v > 0 and ask_v > 0) else max(bid_v, ask_v)

        state = AuctionState(
            market_id=market_id,
            bracket=bracket,
            best_bid=float(market.get("best_bid") or 0.0),
            best_ask=float(market.get("best_ask") or 1.0),
            cum_tweets=cum_tweets,
            hours_to_close=h_to_close,
            elapsed_hours=elapsed_hours,
            total_hours=total_hours,
            bracket_max_count=int(profile.get("bracket_max_count", 40)),
        )

        position = self._get_open_position(sb, module_id, market_id, bracket)

        # ---- No position: maybe enter ----
        if not position:
            max_open = int(cfg.get("max_open_positions", 3))
            try:
                open_count = sb.table("spike_positions").select("id", count="exact").eq(
                    "module_id", module_id,
                ).in_("state", ["WAITING", "MONITORING"]).execute()
                if (open_count.count or 0) >= max_open:
                    self._log(sb, module_id, "decision", "info",
                              f"[{label}] at max_open_positions={max_open}")
                    return []
            except Exception as e:
                log.warning(f"max_open_positions check failed: {e}")

            can_enter, reason = strategy.can_enter(state, params)
            if not can_enter:
                self._log(sb, module_id, "decision", "info",
                          f"[{label}] entry blocked: {reason}")
                return []

            if self._has_pending_spike_buys(sb, module_id, market_id, bracket):
                self._log(sb, module_id, "decision", "info",
                          f"[{label}] pending BUY orders already in flight")
                return []

            self._open_position(sb, module_id, market, bracket, current_price)
            return self._build_buy_ladder_for_profile(
                module_id, market, profile, params, strategy, state, cfg,
            )

        # ---- Position exists: classify ----
        entry = float(position.get("entry_price") or current_price)
        pnl_pct = ((current_price - entry) / entry * 100.0) if entry > 0 else 0.0
        decision, ctx = strategy.classify(state, position, params)

        self._log(sb, module_id, "decision", "info",
                  f"[{label}] {market_id} state=({cum_tweets} tweets, "
                  f"{h_to_close:.1f}h left, price={current_price*100:.1f}¢, "
                  f"pnl={pnl_pct:+.1f}%) pacing={ctx.get('pacing_score','—')} "
                  f"→ {decision} ({ctx.get('trigger','')})")

        # Snapshot uses the legacy PositionState shape for the snapshots table
        ps = PositionState(
            cum_tweets=cum_tweets,
            hours_to_close=h_to_close,
            current_price=current_price,
            entry_price=entry,
            pnl_pct=pnl_pct,
        )
        self._snapshot(sb, position["id"], ps, decision)
        sb.table("spike_positions").update({
            "state": "MONITORING",
            "current_tweets": cum_tweets,
            "hours_to_close": round(h_to_close, 2),
            "last_decision": decision,
            "last_decision_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", position["id"]).execute()

        if decision == "SELL-NOW":
            return self._build_market_sell(sb, module_id, market, position, h_to_close)
        return []

    # ------------------------------------------------------------------
    # Signal builders
    # ------------------------------------------------------------------

    def _build_buy_ladder_for_profile(
        self, module_id: str, market: dict, profile: dict, params: dict,
        strategy, state, cfg: dict,
    ) -> list[Signal]:
        """Emit buy Signals using the strategy-supplied tier ladder.
        Strategy returns abstract tier dicts; this wraps them into Signals
        with adaptive_buy_price + module-wide bracket cap applied."""
        signals: list[Signal] = []
        bid = float(market.get("best_bid") or 0.0)
        ask = float(market.get("best_ask") or 1.0)
        bracket_cap = float(cfg.get("bracket_cap_pct_of_bankroll", 0.05))
        bracket = profile.get("bracket")

        for tier in strategy.build_buy_ladder(state, params):
            target = float(tier.get("price", 0))
            pct = float(tier.get("pct", 0))
            if target <= 0 or pct <= 0:
                continue
            limit_price = adaptive_buy_price(bid, ask, target)
            signals.append(Signal(
                module_id=module_id,
                market_id=market["market_id"],
                bracket=bracket,
                side="BUY",
                edge=0.0,
                model_prob=0.0,
                market_price=limit_price,
                kelly_pct=pct * bracket_cap,
                confidence=0.5,
                best_bid=bid,
                best_ask=ask,
                metadata={
                    "strategy": "spike_trading",
                    "strategy_name": strategy.name,
                    "profile_label": profile.get("label"),
                    "tier": tier.get("tier"),
                    "tier_label": tier.get("label"),
                    "tier_type": "buy",
                    "skip_edge_check": True,
                    "target_price": target,
                    "adaptive_price": limit_price,
                },
            ))
        return signals

    # Legacy single-bracket builder kept for backwards-compat with any code
    # that may still call it. New callers should use _build_buy_ladder_for_profile.
    def _build_buy_ladder(self, module_id: str, market: dict, cfg: dict) -> list[Signal]:
        signals = []
        bid = float(market.get("best_bid") or 0.0)
        ask = float(market.get("best_ask") or 1.0)
        ladder = cfg.get("buy_ladder")
        if isinstance(ladder, list) and ladder:
            tiers = [
                (i + 1, float(t.get("price", 0.0)), float(t.get("pct", 0.0)),
                 t.get("label", f"tier{i+1}"))
                for i, t in enumerate(ladder)
            ]
        else:
            tiers = [
                (1, float(cfg.get("buy_tier_1_price", 0.0)), float(cfg.get("buy_tier_1_pct", 0.0)), "tier1"),
                (2, float(cfg.get("buy_tier_2_price", 0.0)), float(cfg.get("buy_tier_2_pct", 0.0)), "tier2"),
            ]
        for tier_idx, target, pct, label in tiers:
            if target <= 0 or pct <= 0:
                continue
            limit_price = adaptive_buy_price(bid, ask, target)
            signals.append(Signal(
                module_id=module_id,
                market_id=market["market_id"],
                bracket=cfg.get("bracket_pattern", "<40"),
                side="BUY",
                edge=0.0, model_prob=0.0, market_price=limit_price,
                kelly_pct=pct * cfg.get("bracket_cap_pct_of_bankroll", 0.05),
                confidence=0.5,
                best_bid=bid, best_ask=ask,
                metadata={
                    "strategy": "spike_trading", "tier": tier_idx, "tier_label": label,
                    "tier_type": "buy", "skip_edge_check": True,
                    "target_price": target, "adaptive_price": limit_price,
                },
            ))
        return signals

    # Minimum acceptable bid for a SELL-NOW exit. Below this we don't dump
    # at the bid (would functionally be a market order at 0). Instead we
    # use a slow-bleed limit that walks DOWN over remaining hours — the
    # position auto-exits even with no manual intervention.
    SELLNOW_MIN_BID = 0.005   # 0.5¢

    def _build_market_sell(self, sb, module_id: str, market: dict, position: dict, h_to_close: float) -> list[Signal]:
        """Emit a SELL signal to exit the position on a dying bracket.

        Two paths:
          - Bid book is healthy (best_bid >= 0.5¢): cross the spread at
            the bid for an aggressive but predictable fill.
          - Bid book is too thin: place a slow-bleed limit a tick under
            the bid (or below 1¢ if no bid). Each cycle the price walks
            lower until we fill or close approaches. NO MANUAL EXIT NEEDED.
        """
        bid = float(market.get("best_bid") or 0.0)
        ask = float(market.get("best_ask") or 1.0)

        if bid < self.SELLNOW_MIN_BID:
            # Slow-bleed exit: keep walking the limit down each cycle.
            sell_px = slow_bleed_sell_price(h_to_close, bid, min_floor=0.001)
            self._log(sb, module_id, "risk", "warning",
                      f"SELL-NOW thin book for {market['market_id']}: "
                      f"best_bid={bid:.4f}. Posting slow-bleed limit at {sell_px:.4f}.")
            return [Signal(
                module_id=module_id,
                market_id=market["market_id"],
                bracket=position["bracket"],
                side="SELL",
                edge=0.0,
                model_prob=0.0,
                market_price=sell_px,
                kelly_pct=1.0,
                confidence=1.0,
                best_bid=bid,
                best_ask=ask,
                metadata={
                    "strategy": "spike_trading",
                    "tier_type": "slow_bleed",
                    "reason": "SELL-NOW thin book — auto slow-bleed",
                    "position_id": position["id"],
                    "skip_edge_check": True,
                },
            )]

        # Healthy bid: cross the spread at the bid.
        return [Signal(
            module_id=module_id,
            market_id=market["market_id"],
            bracket=position["bracket"],
            side="SELL",
            edge=0.0,
            model_prob=0.0,
            market_price=bid,
            kelly_pct=1.0,
            confidence=1.0,
            best_bid=bid,
            best_ask=ask,
            metadata={
                "strategy": "spike_trading",
                "tier_type": "market_sell",
                "reason": "SELL-NOW classifier triggered",
                "position_id": position["id"],
                "skip_edge_check": True,
            },
        )]

    # ------------------------------------------------------------------
    # State helpers (spike_positions table)
    # ------------------------------------------------------------------

    def _has_pending_spike_buys(self, sb, module_id: str, market_id: str, bracket: str) -> bool:
        """True if there are any active BUY orders for this market+bracket
        in `submitted` or `live` state. Used to debounce buy-ladder emission."""
        try:
            res = sb.table("orders").select("id").match({
                "module_id": module_id,
                "market_id": market_id,
                "bracket": bracket,
                "side": "BUY",
            }).in_("status", ["submitted", "live", "created"]).limit(1).execute()
            return bool(res.data)
        except Exception:
            return False

    def _get_open_position(self, sb, module_id: str, market_id: str, bracket: str) -> Optional[dict]:
        try:
            res = sb.table("spike_positions").select("*").match({
                "module_id": module_id,
                "market_id": market_id,
                "bracket": bracket,
            }).in_("state", ["WAITING", "MONITORING"]).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            log.warning(f"_get_open_position failed: {e}")
            return None

    def _open_position(self, sb, module_id: str, market: dict, bracket: str, current_price: float):
        # Re-check under the partial unique index — between _get_open_position
        # and here, another cycle could have raced us. If a row already exists
        # in WAITING/MONITORING, no-op rather than letting the DB raise.
        existing = self._get_open_position(sb, module_id, market["market_id"], bracket)
        if existing:
            return
        try:
            sb.table("spike_positions").insert({
                "module_id": module_id,
                "market_id": market["market_id"],
                "bracket": bracket,
                "state": "WAITING",
                "entry_price": current_price,
                "entry_size_shares": 0,         # filled when buy fills land
                "entry_size_usd": 0,
                "current_tweets": 0,
                "hours_to_close": 0,
            }).execute()
        except Exception as e:
            # Most common cause: partial unique index conflict from a parallel
            # cycle. Safe to swallow — the next cycle will find the row via
            # _get_open_position and proceed normally.
            log.warning(f"_open_position failed (likely race on unique index): {e}")

    def _snapshot(self, sb, position_id: str, state: PositionState, decision: str):
        try:
            sb.table("spike_state_snapshots").insert({
                "position_id": position_id,
                "cum_tweets": state.cum_tweets,
                "hours_to_close": round(state.hours_to_close, 2),
                "current_price": state.current_price,
                "decision": decision,
            }).execute()
        except Exception:
            # Snapshot failures are non-fatal — don't break the cycle
            pass

    def _log(self, sb, module_id: str, log_type: str, severity: str, message: str):
        try:
            sb.table("logs").insert({
                "log_type": log_type,
                "severity": severity,
                "module_id": module_id,
                "message": message,
            }).execute()
        except Exception:
            pass
