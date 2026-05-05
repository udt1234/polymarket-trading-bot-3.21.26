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
  3. Shadow mode (cfg.shadow_mode=True): all decisions logged, no Signals
     returned to the engine — nothing trades. Default for Phase 1.

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
)
from api.modules.spike_trading.decision import (
    PositionState,
    classify_decision,
    should_market_sell,
    should_cancel_aggressive_tiers,
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
        # Belt-and-suspenders kill-switch: if DB status isn't 'active' or 'paper',
        # short-circuit. ('paper' lets us run logic without trading, same as
        # shadow_mode in cfg below.)
        db_status = (module_db.get("status") or "").lower()
        if db_status not in ("active", "paper"):
            return []
        cfg = get_module_config(module_id)
        # If the DB row says 'paper', force shadow_mode regardless of cfg
        if db_status == "paper":
            cfg = {**cfg, "shadow_mode": True}

        signals: list[Signal] = []

        active_trackings = await fetch_active_short_window_trackings(
            handle=cfg["handle"],
            platform=cfg["platform"],
            target_window_days=cfg["window_days"],
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

        if cfg.get("shadow_mode", True):
            # Phase 1 default: log only, don't trade.
            for s in signals:
                self._log(sb, module_id, "decision", "info",
                          f"[SHADOW] Would emit: {s.side} {s.bracket} @ {s.market_price:.4f} kelly={s.kelly_pct:.4f}")
            return []

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
        cum_tweets = await fetch_cumulative_tweets(cfg["handle"], tracking.get("id"))
        h_to_close = hours_to_close(end_iso)
        # Use mid as proxy for "current price" — robust to one-sided books
        current_price = (market["best_bid"] + market["best_ask"]) / 2.0 if market["best_ask"] > 0 else market["best_bid"]

        # ---- No position yet → maybe place buy ladder ----
        if not position:
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
        decision = classify_decision(state, cfg)

        # Always snapshot
        self._snapshot(sb, position["id"], state, decision)
        self._log(sb, module_id, "decision", "info",
                  f"{market_id} {bracket} state=({cum_tweets} tweets, "
                  f"{h_to_close:.1f}h left, price={current_price*100:.1f}¢, "
                  f"pnl={pnl_pct:+.1f}%) → {decision}")

        sb.table("spike_positions").update({
            "state": "MONITORING",
            "current_tweets": cum_tweets,
            "hours_to_close": round(h_to_close, 2),
            "last_decision": decision,
            "last_decision_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", position["id"]).execute()

        if should_market_sell(decision):
            return self._build_market_sell(sb, module_id, market, position)

        # HOLD / HOLD-LIGHT / SELL — no immediate signal action.
        # (A future enhancement: cancel/adjust live limit-sell orders here.)
        return []

    # ------------------------------------------------------------------
    # Signal builders
    # ------------------------------------------------------------------

    def _build_buy_ladder(self, module_id: str, market: dict, cfg: dict) -> list[Signal]:
        """Emit two buy Signals at tier 1 and tier 2 prices.

        Signal contract:
          - side='BUY'
          - market_price = limit price for this tier
          - kelly_pct    = % of allocation for this tier (from cfg)
          - metadata     = tier index + spike_trading flag
        """
        signals = []
        for tier_idx, (price_key, pct_key) in enumerate([
            ("buy_tier_1_price", "buy_tier_1_pct"),
            ("buy_tier_2_price", "buy_tier_2_pct"),
        ], start=1):
            price = float(cfg.get(price_key, 0.0))
            pct = float(cfg.get(pct_key, 0.0))
            if price <= 0 or pct <= 0:
                continue
            signals.append(Signal(
                module_id=module_id,
                market_id=market["market_id"],
                bracket=cfg["bracket_pattern"],
                side="BUY",
                edge=0.0,                # not edge-driven; strategy is structural
                model_prob=0.0,           # not used by spike strategy
                market_price=price,
                kelly_pct=pct * cfg.get("bracket_cap_pct_of_bankroll", 0.05),
                confidence=0.5,
                best_bid=market["best_bid"],
                best_ask=market["best_ask"],
                metadata={
                    "strategy": "spike_trading",
                    "tier": tier_idx,
                    "tier_type": "buy",
                    "shadow_mode": cfg.get("shadow_mode", True),
                },
            ))
        return signals

    # Minimum acceptable bid for a SELL-NOW exit. Below this, the book is so
    # thin that placing a sell at the bid is functionally a market order at 0
    # — we'd dump the position for nothing AND likely not even fill due to
    # tick-size rounding. Better to flag and let a human handle.
    SELLNOW_MIN_BID = 0.005   # 0.5¢

    def _build_market_sell(self, sb, module_id: str, market: dict, position: dict) -> list[Signal]:
        """Emit a SELL signal aggressively priced to fill on the dying bracket.

        Critical safety: if the bid book is empty (best_bid below tick floor),
        we cannot exit cleanly. Log loud and skip — operator-visible. Better
        a stuck position with an alert than a silent unfillable order.
        """
        bid = float(market.get("best_bid") or 0.0)
        ask = float(market.get("best_ask") or 1.0)

        if bid < self.SELLNOW_MIN_BID:
            # No liquidity to exit on. Log + alert, do nothing.
            self._log(sb, module_id, "risk", "warning",
                      f"SELL-NOW triggered for {market['market_id']} but best_bid={bid:.4f} "
                      f"is below floor {self.SELLNOW_MIN_BID:.4f}. Position remains open. "
                      f"Manual exit required.")
            try:
                from api.services.alerts import send_slack
                import asyncio
                asyncio.get_event_loop().create_task(send_slack(
                    f":warning: *Spike Trading: stuck SELL-NOW*\n"
                    f"Market `{market['market_id']}` SELL-NOW classifier fired but bid book is empty "
                    f"(best_bid={bid*100:.2f}¢). Position cannot exit cleanly — manual review needed."
                ))
            except Exception:
                pass
            return []

        # Aggressive limit at the bid: fills against existing buy orders.
        # If bid book is thin we may only partial-fill, but the engine's exit
        # path will retry next cycle.
        return [Signal(
            module_id=module_id,
            market_id=market["market_id"],
            bracket=position["bracket"],
            side="SELL",
            edge=0.0,
            model_prob=0.0,
            market_price=bid,             # cross the spread, take whatever bid liquidity exists
            kelly_pct=1.0,                # 100% — exit everything
            confidence=1.0,
            best_bid=bid,
            best_ask=ask,
            metadata={
                "strategy": "spike_trading",
                "tier_type": "market_sell",
                "reason": "SELL-NOW classifier triggered",
                "position_id": position["id"],
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
