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

    def get_handle(self) -> str:
        # Read from the per-module config so it tracks whatever the user
        # configured (default: elonmusk on x platform).
        try:
            sb = get_supabase()
            row = sb.table("modules").select("id").eq("name", "Spike Trading").execute()
            if row.data:
                cfg = get_module_config(row.data[0]["id"])
                return cfg.get("handle", "elonmusk")
        except Exception:
            pass
        return "elonmusk"

    def get_platform(self) -> str:
        try:
            sb = get_supabase()
            row = sb.table("modules").select("id").eq("name", "Spike Trading").execute()
            if row.data:
                cfg = get_module_config(row.data[0]["id"])
                return cfg.get("platform", "x")
        except Exception:
            pass
        return "x"

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        from api.modules.spike_trading.module_config import save_module_config
        save_module_config(module_id, config)

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

        active_trackings = await fetch_active_short_window_trackings(
            handle=cfg["handle"],
            platform=cfg["platform"],
            target_window_days=cfg["window_days"],
            series_slug=cfg.get("series_slug"),
        )
        if not active_trackings:
            self._log(sb, module_id, "decision", "info",
                      f"No active {cfg['window_days']}-day {cfg['handle']} tracking found")
            return []

        for tracking in active_trackings:
            try:
                market = await fetch_market_for_tracking(tracking, cfg["bracket_pattern"])
                if not market or not market.get("market_id"):
                    self._log(sb, module_id, "decision", "info",
                              f"No matching {cfg['bracket_pattern']} market for tracking {tracking.get('id')}")
                    continue
                if market.get("volume_24h", 0) < cfg.get("min_market_volume_24h", 0):
                    self._log(sb, module_id, "decision", "info",
                              f"Skipping market {market['market_id']} — volume_24h ${market.get('volume_24h', 0):,.0f} below threshold")
                    continue

                # xTracker payloads sometimes use 'id' and sometimes 'trackingId'
                tracking_id = tracking.get("id") or tracking.get("trackingId")
                if not tracking_id:
                    self._log(sb, module_id, "decision", "warning",
                              f"Skipping tracking with no id: {tracking.get('title', '?')}")
                    continue
                tracking["__resolved_id"] = tracking_id
                signals.extend(await self._handle_market(
                    sb, module_id, cfg, market, tracking,
                ))
            except Exception as e:
                # Per-market failures shouldn't take down the whole cycle
                log.exception(f"spike_trading per-market error: {e}")
                self._log(sb, module_id, "system", "error",
                          f"market handling failed: {e}")

        return signals

    # ------------------------------------------------------------------
    # Per-market state machine
    # ------------------------------------------------------------------

    async def _handle_market(
        self, sb, module_id: str, cfg: dict, market: dict, tracking: dict,
    ) -> list[Signal]:
        market_id = market["market_id"]
        bracket = cfg["bracket_pattern"]
        end_iso = tracking.get("endDate", "")

        position = self._get_open_position(sb, module_id, market_id, bracket)
        # Discover the right tracking-id for tweet counts:
        #   - If source=xtracker, the tracking dict already has the right id.
        #   - If source=gamma_series, the 'id' is a Gamma event id — not
        #     usable on xTracker. Resolve by matching xTracker tracking
        #     start/end dates to this auction's window. Returns 0 if no
        #     xTracker tracking exists yet (pre-launch).
        if tracking.get("source") == "gamma_series":
            xt_id = await _resolve_xtracker_id_for_window(
                cfg["handle"], cfg["platform"], tracking.get("startDate"), tracking.get("endDate"),
            )
            cum_tweets = await fetch_cumulative_tweets(cfg["handle"], xt_id) if xt_id else 0
        else:
            cum_tweets = await fetch_cumulative_tweets(
                cfg["handle"], tracking.get("__resolved_id") or tracking.get("id"),
            )
        h_to_close = hours_to_close(end_iso)
        # Use mid as proxy for "current price" — robust to one-sided books
        current_price = (market["best_bid"] + market["best_ask"]) / 2.0 if market["best_ask"] > 0 else market["best_bid"]

        # ---- No position yet → maybe place buy ladder ----
        if not position:
            # Enforce max_open_positions across all open positions for this module
            max_open = int(cfg.get("max_open_positions", 3))
            try:
                open_count = sb.table("spike_positions").select("id", count="exact").eq(
                    "module_id", module_id,
                ).in_("state", ["WAITING", "MONITORING"]).execute()
                if (open_count.count or 0) >= max_open:
                    self._log(sb, module_id, "decision", "info",
                              f"Skipping {market_id}: at max_open_positions={max_open}")
                    return []
            except Exception as e:
                log.warning(f"max_open_positions check failed: {e}")
            if h_to_close <= (cfg["window_days"] * 24 - cfg["buy_cancel_after_hours"]):
                self._log(sb, module_id, "decision", "info",
                          f"Skipping {market_id}: past buy-eligibility cutoff "
                          f"(t-{h_to_close:.1f}h, cutoff={cfg['buy_cancel_after_hours']}h after open)")
                return []
            # Don't re-emit buy signals if we already have unfilled BUYs in flight.
            # Without this guard the 5-min cycle would spam the order book with
            # duplicate limits at the same prices on every iteration.
            if self._has_pending_spike_buys(sb, module_id, market_id, bracket):
                self._log(sb, module_id, "decision", "info",
                          f"{market_id} {bracket}: pending BUY orders already in flight, no re-emit")
                return []
            self._open_position(sb, module_id, market, bracket, current_price)
            return self._build_buy_ladder(module_id, market, cfg)

        # ---- Position exists → run HOLD/SELL classifier ----
        entry = float(position.get("entry_price") or current_price)
        pnl_pct = ((current_price - entry) / entry * 100.0) if entry > 0 else 0.0

        state = PositionState(
            cum_tweets=cum_tweets,
            hours_to_close=h_to_close,
            current_price=current_price,
            entry_price=entry,
            pnl_pct=pnl_pct,
        )
        # Pacing-aware classifier: knows projected final tweet count
        # based on current rate, can override v1 when pacing is extreme.
        total_hours = float(cfg.get("window_days", 2)) * 24.0
        decision, ctx = classify_decision_v2(state, cfg, total_hours)

        self._log(sb, module_id, "decision", "info",
                  f"{market_id} {bracket} state=({cum_tweets} tweets, "
                  f"{h_to_close:.1f}h left, price={current_price*100:.1f}¢, "
                  f"pnl={pnl_pct:+.1f}%) pacing={ctx['pacing_score']} "
                  f"proj_final={ctx['projected_final_tweets']} → {decision} "
                  f"({ctx.get('trigger','')})")

        self._snapshot(sb, position["id"], state, decision)
        sb.table("spike_positions").update({
            "state": "MONITORING",
            "current_tweets": cum_tweets,
            "hours_to_close": round(h_to_close, 2),
            "last_decision": decision,
            "last_decision_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", position["id"]).execute()

        if should_market_sell(decision):
            return self._build_market_sell(sb, module_id, market, position, h_to_close)

        # HOLD / HOLD-LIGHT / SELL — no immediate signal action.
        # (A future enhancement: cancel/adjust live limit-sell orders here.)
        return []

    # ------------------------------------------------------------------
    # Signal builders
    # ------------------------------------------------------------------

    def _build_buy_ladder(self, module_id: str, market: dict, cfg: dict) -> list[Signal]:
        """Emit buy Signals using adaptive pricing.

        Each tier is built from a TARGET price in cfg, but the actual limit
        sent uses adaptive_buy_price() to undercut the ask if the market is
        already at or below our target — saving cost without changing
        fill-probability.
        """
        signals = []
        bid = float(market.get("best_bid") or 0.0)
        ask = float(market.get("best_ask") or 1.0)
        for tier_idx, (price_key, pct_key) in enumerate([
            ("buy_tier_1_price", "buy_tier_1_pct"),
            ("buy_tier_2_price", "buy_tier_2_pct"),
        ], start=1):
            target = float(cfg.get(price_key, 0.0))
            pct = float(cfg.get(pct_key, 0.0))
            if target <= 0 or pct <= 0:
                continue
            # Adaptive: if ask is already ≤ target, place just under the ask
            # to jump the queue at near-equivalent cost.
            limit_price = adaptive_buy_price(bid, ask, target)
            signals.append(Signal(
                module_id=module_id,
                market_id=market["market_id"],
                bracket=cfg["bracket_pattern"],
                side="BUY",
                edge=0.0,                # not edge-driven; strategy is structural
                model_prob=0.0,           # not used by spike strategy
                market_price=limit_price,
                kelly_pct=pct * cfg.get("bracket_cap_pct_of_bankroll", 0.05),
                confidence=0.5,
                best_bid=bid,
                best_ask=ask,
                metadata={
                    "strategy": "spike_trading",
                    "tier": tier_idx,
                    "tier_type": "buy",
                    "skip_edge_check": True,
                    "target_price": target,
                    "adaptive_price": limit_price,
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
