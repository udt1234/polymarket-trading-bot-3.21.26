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
    adaptive_buy_price,
    slow_bleed_sell_price,
)
from api.modules.spike_trading.strategies import get_strategy, all_strategy_names
from api.modules.spike_trading.strategies.base import AuctionState

log = logging.getLogger(__name__)


class SpikeTradingModule(BaseModule):
    name = "spike_trading"
    enabled = True
    # Spike runs a structural lottery-ticket ladder regardless of regime.
    # Don't let the dashboard show "Watching — regime in transition".
    gates_by_regime = False

    # ------------------------------------------------------------------
    # BaseModule contract
    # ------------------------------------------------------------------

    # evaluate() inherited from BaseModule — delegates to _evaluate_async().

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
        """First enabled auction_type across ALL DB rows mapped to this module.
        Used by engine.* methods that expect a single handle/platform/window
        (post-count snapshot, dashboard default). Multi-auction iteration
        happens in _evaluate_async.

        Matches every row whose `strategy='spike_trading'` OR whose name
        contains a display keyword — same resolution as the registry. This
        makes duplication safe: a new 'Spike Trading v2' row is picked up
        without code changes.
        """
        try:
            sb = get_supabase()
            all_rows = sb.table("modules").select("id,name,strategy").execute().data or []
            matching = [
                r for r in all_rows
                if (r.get("strategy") or "").lower().strip() == self.name
                or any(kw in (r.get("name") or "").lower() for kw in self.get_display_keywords())
            ]
            for r in matching:
                cfg = get_module_config(r["id"])
                for at in cfg.get("auction_types", []) or []:
                    if at.get("enabled"):
                        return at
            # No enabled auction type — fall back to first available
            for r in matching:
                cfg = get_module_config(r["id"])
                ats = cfg.get("auction_types", []) or []
                if ats:
                    return ats[0]
            return None
        except Exception:
            return None

    def get_handle(self) -> str:
        at = self._first_enabled_auction()
        return at.get("handle", "elonmusk") if at else "elonmusk"

    def get_buy_order_ttl_hours(self) -> float:
        """Spike places deep limits (0.3-15¢) that can sit on the book up to
        24h waiting for a price drop. Override BaseModule's 5-min default."""
        return 24.0

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
            {"key": "spike_total_commitment_usd", "label": "Total $ per auction (5-tier ladder)", "type": "number",
             "section": "buy", "min": 5, "max": 35, "step": 5,
             "help": "Total USD across all 5 buy tiers per auction. Default $25. Tier sizes "
                     "scale proportionally. Capped at $35 until the kelly_pct→notional refactor "
                     "lands — above $35 the cheapest tier trips the per-trade exposure cap."},
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
        """Evaluate every DB row that maps to this module class.

        Resolution: rows whose `strategy='spike_trading'` OR whose display
        name contains 'spike trading' / 'spike' (mirrors registry.for_db_row).
        This is what makes module duplication safe — the user can create a
        new row with name 'Spike Trading v2' and the engine will pick it up
        as long as `strategy='spike_trading'`.

        Each matching row gets its own pass through the auction_types ×
        bracket_profiles loop with its own module_id, config, and signals.
        """
        sb = get_supabase()
        # Find all DB rows for this module class. Prefer strategy match;
        # fall back to display-keyword match for backwards compat.
        all_rows = sb.table("modules").select("*").execute().data or []
        matching_rows = [
            r for r in all_rows
            if (r.get("strategy") or "").lower().strip() == self.name
            or any(kw in (r.get("name") or "").lower() for kw in self.get_display_keywords())
        ]
        if not matching_rows:
            log.warning(f"No DB rows match module class '{self.name}'; create one before enabling.")
            return []

        all_signals: list[Signal] = []
        for module_db in matching_rows:
            try:
                all_signals.extend(await self._evaluate_one_row(sb, module_db))
            except Exception as e:
                log.error(f"_evaluate_one_row failed for module_id={module_db.get('id')}: {e}", exc_info=True)
        return all_signals

    async def _evaluate_one_row(self, sb, module_db: dict) -> list[Signal]:
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
        if h_to_close is None:
            # Window timing unknown — refuse to evaluate. Pacing logic divides
            # by elapsed_hours; defaulting to "0 hours left" would trigger
            # premature SELL-NOW classification on a parse failure.
            self._log(sb, module_id, "decision", "warning",
                      f"[{label}] {market_id}: tracking has no parseable endDate ({end_iso!r}) — skipping cycle")
            return []
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

            # Only emit the ladder if we have a tracker row. Otherwise fills
            # would be orphaned with nothing to classify SELL-NOW / HOLD off.
            if not self._open_position(sb, module_id, market, bracket, current_price):
                self._log(sb, module_id, "decision", "warning",
                          f"[{label}] {market_id}: could not create spike_positions row — "
                          f"refusing to emit ladder (would orphan fills)")
                return []
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
            # Phantom-position guard: a spike_positions row can sit in
            # state=MONITORING with entry_size_shares=0 when the buy ladder
            # placed orders that never filled (typical for the 0.3¢/0.5¢
            # tiers). The LiveExecutor then queries the canonical `positions`
            # table, finds no row, and raises 'No open BUY position to sell'.
            # That fires every cycle (every 5 min) and trips the Degraded
            # banner. Skip the SELL signal and liquidate the phantom row so
            # it stops cycling forever.
            try:
                shares = float(position.get("entry_size_shares") or 0)
            except (TypeError, ValueError):
                shares = 0.0
            if shares <= 0:
                self._log(sb, module_id, "risk", "warning",
                          f"[{label}] {market_id} SELL-NOW with 0 shares "
                          f"(phantom row {position['id'][:8]}…). "
                          f"Auto-liquidating spike_positions row; no SELL emitted.")
                try:
                    sb.table("spike_positions").update({
                        "state": "LIQUIDATED",
                        "closed_at": datetime.now(timezone.utc).isoformat(),
                        "last_decision": "AUTO_LIQUIDATE_NO_SHARES",
                        "last_decision_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", position["id"]).execute()
                except Exception as e:
                    log.warning(f"phantom liquidation update failed for {position['id']}: {e}")
                return []
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

        2026-05-14 rewrite: tiers now carry `notional_usd` (dollar amount
        per tier) instead of `pct`-of-bankroll. Size = notional_usd / price,
        validated against the three Polymarket CLOB minimums before the
        signal is emitted:
          - price >= min_tick (e.g. 0.01); below-tick prices snap UP, but
            we never silently snap by >50% — those tiers are dropped.
          - notional_usd >= $1 (CLOB minimum notional)
          - size >= 5 shares (orderMinSize on most markets, with a small
            cushion for the live-fill-price difference)
        Tiers that fail any check are dropped with a warning instead of
        being sent to the executor for rejection.
        """
        signals: list[Signal] = []
        bid = float(market.get("best_bid") or 0.0)
        ask = float(market.get("best_ask") or 1.0)
        bracket = profile.get("bracket")
        min_tick = float(market.get("min_tick_size") or 0.01)
        clob_min_shares = float(market.get("min_order_size") or 5)
        # Hard floor for CLOB notional (the API doesn't expose this; it's a
        # platform-wide rule the user has confirmed).
        clob_min_notional_usd = 1.0

        # Skip-dying-market guard: if best_ask has already collapsed to the
        # market's tick floor, the auction is essentially resolved against
        # this bracket — buying any quantity is throwing money away because
        # the bracket cannot recover above 1¢ before settlement. Drop the
        # whole ladder here instead of emitting tiers that the risk manager
        # will reject anyway (and that previously produced kelly_pct=3.0/5.0
        # nonsense on neg_risk markets where min_tick=0.001).
        if ask > 0 and ask <= min_tick * 1.5:
            log.info(
                f"Spike skipping market {market.get('market_id')} bracket={bracket}: "
                f"best_ask={ask} at/below tick floor (min_tick={min_tick}). "
                f"Auction is resolving against us; no buy ladder emitted."
            )
            return signals

        # Determine if the prior 2-day auction settled outside <40 (i.e.
        # >=40 won). Spike's strategy widens the top tier from 15¢ to 22¢
        # in that regime. Cached in cfg for the duration of the auction;
        # `_resolve_prior_above_bracket` queries auction_archive once.
        params_with_context = dict(params or {})
        try:
            params_with_context["prior_above_bracket"] = self._resolve_prior_above_bracket(
                module_id, cfg,
            )
        except Exception as exc:
            log.warning(f"prior-above-bracket lookup failed: {exc}")
            params_with_context["prior_above_bracket"] = False
        # Total commitment override (default $25, user-editable from cfg).
        # Hard-cap at $35 — above that the cheapest tier's share count makes
        # `kelly_pct = size/1000` exceed the per-trade exposure cap (0.15)
        # and the risk manager rejects every signal. Until the kelly→notional
        # refactor lands, this ceiling keeps the ladder shippable.
        total_commitment = cfg.get("spike_total_commitment_usd")
        if total_commitment is not None:
            tc = float(total_commitment)
            if tc > 35.0:
                log.warning(
                    f"spike_total_commitment_usd={tc} > $35 cap; clamping. "
                    f"Above $35 the cheapest tier trips the per-trade kelly cap."
                )
                tc = 35.0
            params_with_context["spike_total_commitment_usd"] = tc

        for tier in strategy.build_buy_ladder(state, params_with_context):
            target = float(tier.get("price", 0))
            notional_usd = float(tier.get("notional_usd", 0))
            label = tier.get("label", "tier")
            if target <= 0 or notional_usd <= 0:
                continue

            # 1) Resolve actual limit price using the adaptive_buy_price
            #    helper (jumps the queue if the ask is already cheaper than
            #    our target), then snap to the market's min_tick.
            limit_price = adaptive_buy_price(bid, ask, target)
            pre_snap = limit_price
            if min_tick > 0:
                snapped = round(limit_price / min_tick) * min_tick
                if snapped < min_tick:
                    snapped = min_tick
                limit_price = round(snapped, 4)

            # 2) If the tick-snap moved price by >50% of the strategy's
            #    intent, the tier is no longer the strategy the user picked.
            #    Drop it rather than overpaying silently.
            if pre_snap > 0 and abs(limit_price - pre_snap) / pre_snap > 0.5:
                log.warning(
                    f"Spike tier price snapped >50%: label={label} "
                    f"intended={pre_snap:.4f} snapped={limit_price:.4f} "
                    f"min_tick={min_tick} — dropping tier."
                )
                continue

            # 3) Compute shares from notional. The CLOB enforces 5-share
            #    AND $1-notional minimums; both must pass.
            size = round(notional_usd / limit_price)
            if size < clob_min_shares:
                log.warning(
                    f"Spike tier below min shares: label={label} "
                    f"notional=${notional_usd:.2f} price={limit_price:.4f} "
                    f"size={size} < min_order_size={clob_min_shares} — dropping tier."
                )
                continue
            actual_notional = size * limit_price
            if actual_notional < clob_min_notional_usd:
                log.warning(
                    f"Spike tier below CLOB min notional: label={label} "
                    f"notional=${actual_notional:.2f} < ${clob_min_notional_usd:.2f} "
                    f"— dropping tier."
                )
                continue

            # kelly_pct = real dollar notional / bankroll. The risk manager
            # uses kelly_pct as "fraction of bankroll deployed" — at 1¢ tick
            # that math worked, but at 0.001 (neg_risk) tick, size/1000 was
            # bogus: $3 notional at 0.001 price = 3000 shares, kelly_pct =
            # 3.0 (300% of bankroll!) which the risk manager correctly
            # rejected. Compute kelly_pct from the real notional instead.
            from api.config import get_settings as _gs
            _bankroll = float(getattr(_gs(), "bankroll", 1000.0) or 1000.0)
            kelly_pct = actual_notional / _bankroll if _bankroll > 0 else 0.0

            signals.append(Signal(
                module_id=module_id,
                market_id=market["market_id"],
                bracket=bracket,
                side="BUY",
                edge=0.0,
                model_prob=0.0,
                market_price=limit_price,
                kelly_pct=kelly_pct,
                confidence=0.5,
                best_bid=bid,
                best_ask=ask,
                token_id=market.get("token1"),
                metadata={
                    "strategy": "spike_trading", "signal_type": "spike",
                    "strategy_name": strategy.name,
                    "profile_label": profile.get("label"),
                    "tier": tier.get("tier"),
                    "tier_label": label,
                    "tier_type": "buy",
                    "tier_notional_usd": round(notional_usd, 2),
                    "tier_shares": int(size),
                    "skip_edge_check": True,
                    "target_price": target,
                    "adaptive_price": limit_price,
                    "prior_above_bracket": bool(params_with_context.get("prior_above_bracket")),
                    "event_slug": market.get("slug"),
                },
            ))
        return signals

    def _resolve_prior_above_bracket(self, module_id: str, cfg: dict) -> bool:
        """Did the most recent resolved 2-day auction settle OUTSIDE <40?

        Used to widen the top tier (15¢ → 22¢). Queries auction_archive
        for the last `(handle, window_days~2)` resolved row. Returns True
        when `winning_bracket` is set and is NOT '<40' AND parses to >=40.
        """
        try:
            handle = self.get_handle()
        except Exception:
            handle = None
        if not handle:
            return False
        try:
            sb = get_supabase()
            res = (
                sb.table("auction_archive")
                .select("winning_bracket")
                .eq("handle", handle)
                .gte("window_days", 1.5)
                .lte("window_days", 2.5)
                .lt("end_date", datetime.now(timezone.utc).isoformat())
                .order("end_date", desc=True)
                .limit(1)
                .execute()
            )
            row = (res.data or [None])[0]
            if not row:
                return False
            wb = (row.get("winning_bracket") or "").strip()
            if not wb or wb == "<40":
                return False
            # Parse numeric lower edge of the winning bracket; '>=40' wins
            # the widening regime. '40-49', '50-59', ..., '240+' all qualify.
            lo = self._bracket_lower_edge(wb)
            return lo >= 40
        except Exception:
            return False

    @staticmethod
    def _bracket_lower_edge(label: str) -> int:
        """Numeric lower edge for a bracket label. '<40'→0, '40-49'→40,
        '240+'→240. Returns 0 on parse failure (safe default — won't
        trip the widening regime)."""
        label = (label or "").strip()
        if not label or label.startswith("<"):
            return 0
        if label.endswith("+"):
            try:
                return int(label[:-1])
            except ValueError:
                return 0
        if "-" in label:
            try:
                return int(label.split("-", 1)[0])
            except ValueError:
                return 0
        try:
            return int(label)
        except ValueError:
            return 0

    # Legacy single-bracket builder (`_build_buy_ladder`) removed 2026-05-16.
    # Only `_build_buy_ladder_for_profile` is in use. Legacy config keys
    # (`buy_ladder` with pct, `buy_tier_*_price/pct`, `bracket_pattern`)
    # also dropped — see `module_config.py` for the canonical schema.

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
                token_id=market.get("token1"),
                metadata={
                    "strategy": "spike_trading", "signal_type": "spike",
                    "tier_type": "slow_bleed",
                    "reason": "SELL-NOW thin book — auto slow-bleed",
                    "position_id": position["id"],
                    "skip_edge_check": True,
                    "force_exit": True,
                    "event_slug": market.get("slug"),
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
            token_id=market.get("token1"),
            metadata={
                "strategy": "spike_trading", "signal_type": "spike",
                "tier_type": "market_sell",
                "reason": "SELL-NOW classifier triggered",
                "position_id": position["id"],
                "skip_edge_check": True,
                "force_exit": True,
                "event_slug": market.get("slug"),
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

    def _open_position(self, sb, module_id: str, market: dict, bracket: str, current_price: float) -> bool:
        """Insert the spike_positions tracker row. Returns True when a row
        exists after this call (either freshly inserted OR pre-existing from
        a parallel cycle that won the race). Returns False when neither —
        meaning the caller MUST NOT emit ladder signals (otherwise fills
        would be orphaned with no tracker row to classify them).
        """
        # Re-check under the partial unique index — between _get_open_position
        # and here, another cycle could have raced us. If a row already exists
        # in WAITING/MONITORING, no-op rather than letting the DB raise.
        existing = self._get_open_position(sb, module_id, market["market_id"], bracket)
        if existing:
            return True
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
            return True
        except Exception as e:
            # Most common cause: partial unique index conflict from a parallel
            # cycle. Distinguish: if the row now exists (parallel cycle won),
            # return True; otherwise this was a real failure (DB down, missing
            # table, etc.) and the caller must NOT emit ladder signals.
            log.warning(f"_open_position insert failed: {e}")
            recovered = self._get_open_position(sb, module_id, market["market_id"], bracket)
            return recovered is not None

    def _snapshot(self, sb, position_id: str, state: PositionState, decision: str):
        try:
            sb.table("spike_state_snapshots").insert({
                "position_id": position_id,
                "cum_tweets": state.cum_tweets,
                "hours_to_close": round(state.hours_to_close, 2),
                "current_price": state.current_price,
                "decision": decision,
            }).execute()
        except Exception as e:
            # Snapshot failures are non-fatal — don't break the trading cycle.
            # But DO surface them: a missing migration would silently kill the
            # backtest data stream otherwise (see lessons.md 2026-05-02).
            log.warning(f"_snapshot insert failed for position={position_id}: {e}")

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
