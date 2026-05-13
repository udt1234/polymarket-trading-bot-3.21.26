"""Copy Trading module — mirrors trades from configured whale wallets.

Strategy reference: _ImportantConfigFiles/COPY_TRADING_MODULE_SPEC.md

Cycle (every engine tick — module also has a faster polling cadence in
config, but evaluate() runs on the engine's interval):
  For each enabled wallet:
    1. Poll data-api /trades?user={wallet}, limit=50.
    2. Diff against last_seen_trade_ts in copy_trade_state.
    3. Cold-start guard: drop trades older than max_trade_age_sec on
       startup (never act on a flood of stale trades).
    4. Per trade: staleness gate, drift gate, dedupe check, 4 risk caps.
    5. Mirror via Signal -> executor; log every decision to copy_trade_log.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from api.modules.base import BaseModule
from api.services.risk_manager import Signal
from api.dependencies import get_supabase
from api.config import get_settings
from api.modules.copy_trading.module_config import get_module_config, save_module_config
from api.modules.copy_trading.data import poll_wallet_trades, fetch_wallet_portfolio_value
from api.modules.copy_trading.decision import (
    MIRRORED, SKIP_STALE, SKIP_DRIFT, SKIP_CAP, SKIP_DEDUPE,
    SKIP_CIRCUIT, SKIP_PERF_GATE, SKIP_NO_POSITION, SKIP_ZERO_SIZE,
    is_stale, is_drifted, compute_buy_size_usd, compute_sell_proportion,
    daily_loss_breached, whale_perf_gate_breached,
)
from api.modules.copy_trading.executor import build_buy_signal, build_sell_signal

log = logging.getLogger(__name__)


class CopyTradingModule(BaseModule):
    name = "copy_trading"
    enabled = True
    # Mirror-based strategy — does not gate on regime. The whale is the
    # signal source; transitions / surges are irrelevant.
    gates_by_regime = False

    def evaluate(self) -> list[Signal]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
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
            "strategy": "copy_trading_v1",
        }

    def get_display_keywords(self) -> list[str]:
        return ["copy trading", "copy_trading", "copy"]

    def get_config(self, module_id: str) -> dict:
        return get_module_config(module_id)

    def save_config(self, module_id: str, config: dict) -> None:
        save_module_config(module_id, config)

    def get_config_schema(self) -> list[dict]:
        return [
            {"key": "poll_interval_sec", "label": "Poll Interval (sec)", "type": "number",
             "section": "general", "min": 10, "max": 600, "step": 5,
             "help": "How often each wallet is polled for new trades."},
            {"key": "max_trade_age_sec", "label": "Max Trade Age (sec)", "type": "number",
             "section": "general", "min": 30, "max": 3600, "step": 30,
             "help": "Drop trades older than this on startup or in steady-state."},
            {"key": "max_price_drift_pct", "label": "Max Price Drift (%)", "type": "number",
             "section": "general", "min": 0, "max": 100, "step": 1,
             "help": "Skip copies when current market price drifts past this %."},
            {"key": "per_wallet_cap_pct", "label": "Per-Wallet Exposure Cap (%)", "type": "number",
             "section": "risk", "min": 0, "max": 50, "step": 0.5,
             "help": "Reject new BUYs from a wallet once our exposure exceeds this % of bankroll."},
            {"key": "per_trade_cap_pct", "label": "Per-Trade Size Cap (%)", "type": "number",
             "section": "risk", "min": 0, "max": 10, "step": 0.1,
             "help": "Clip individual mirrored orders at this % of bankroll."},
            {"key": "daily_loss_circuit_pct", "label": "Daily Loss Circuit (%)", "type": "number",
             "section": "risk", "min": -50, "max": 0, "step": 0.1,
             "help": "Pause whole module after this % daily loss (negative)."},
            {"key": "whale_perf_gate_window", "label": "Perf Gate Window", "type": "number",
             "section": "risk", "min": 1, "max": 100, "step": 1,
             "help": "Count of recent copies used to compute rolling whale ROI."},
            {"key": "whale_perf_gate_min_roi_pct", "label": "Perf Gate Min ROI (%)", "type": "number",
             "section": "risk", "min": -100, "max": 0, "step": 1,
             "help": "Auto-disable a wallet once its rolling ROI falls below this %."},
            {"key": "shadow_mode", "label": "Shadow Mode (decide only)", "type": "boolean",
             "section": "advanced",
             "help": "Log every decision but skip signal emission. Belt-and-suspenders on top of paper mode."},
        ]

    # ------------------------------------------------------------------
    # Main async logic
    # ------------------------------------------------------------------

    async def _evaluate_async(self) -> list[Signal]:
        sb = get_supabase()
        all_rows = sb.table("modules").select("*").execute().data or []
        matching_rows = [
            r for r in all_rows
            if (r.get("strategy") or "").lower().strip() == self.name
            or any(kw in (r.get("name") or "").lower() for kw in self.get_display_keywords())
        ]
        if not matching_rows:
            return []

        signals: list[Signal] = []
        for module_db in matching_rows:
            try:
                signals.extend(await self._evaluate_one_row(sb, module_db))
            except Exception as e:
                log.error(f"copy_trading _evaluate_one_row failed for module_id={module_db.get('id')}: {e}", exc_info=True)
        return signals

    async def _evaluate_one_row(self, sb, module_db: dict) -> list[Signal]:
        module_id = module_db["id"]
        db_status = (module_db.get("status") or "").lower()
        if db_status not in ("active", "paper"):
            return []
        cfg = get_module_config(module_id)

        # Circuit-breaker check (cap #3): if daily P&L from copy_trading is
        # under the circuit_pct threshold, pause the module for the day.
        bankroll = float(get_settings().bankroll or 1000.0)
        daily_pnl = self._daily_realized_pnl(sb, module_id)
        if daily_loss_breached(daily_pnl, bankroll, float(cfg["daily_loss_circuit_pct"])):
            self._log(sb, module_id, "risk", "warning",
                      f"Daily-loss circuit breached: pnl={daily_pnl:.2f} threshold={cfg['daily_loss_circuit_pct']}%")
            return []

        wallets = sb.table("copy_trade_wallets").select("*").eq("module_id", module_id).eq("enabled", True).execute().data or []
        if not wallets:
            return []

        signals: list[Signal] = []
        for wallet in wallets:
            try:
                signals.extend(await self._evaluate_wallet(sb, module_id, wallet, cfg, bankroll))
            except Exception as e:
                log.exception(f"copy_trading wallet {wallet.get('wallet_address')} failed: {e}")
                self._handle_poll_failure(sb, wallet, str(e))
        return signals

    async def _evaluate_wallet(
        self, sb, module_id: str, wallet: dict, cfg: dict, bankroll: float,
    ) -> list[Signal]:
        wallet_id = wallet["id"]
        wallet_address = wallet["wallet_address"]
        wallet_weight = float(wallet.get("weight_pct") or 1.0)

        # Whale-perf gate (cap #4): if this wallet's rolling ROI is bad,
        # auto-disable and stop polling it.
        state = self._get_state(sb, wallet_id)
        if whale_perf_gate_breached(
            int(state.get("recent_copy_count") or 0),
            state.get("recent_copy_roi_pct"),
            int(cfg["whale_perf_gate_window"]),
            float(cfg["whale_perf_gate_min_roi_pct"]),
        ):
            self._auto_disable_wallet(sb, wallet_id, reason="perf_gate")
            return []

        trades = await poll_wallet_trades(wallet_address, limit=50)
        self._touch_polled(sb, wallet_id)
        if not trades:
            return []

        # Cold-start / steady-state staleness filter: drop anything older
        # than max_trade_age_sec wholesale before anything else.
        max_age = int(cfg["max_trade_age_sec"])
        now = datetime.now(timezone.utc)
        fresh = [t for t in trades if not is_stale(t["timestamp"], max_age, now=now)]
        stale = [t for t in trades if t not in fresh]
        for st in stale:
            self._log_decision(sb, module_id, wallet_id, st, SKIP_STALE,
                               skip_reason=f"trade age > {max_age}s")

        # Diff against last_seen_trade_ts so we only consider new trades.
        last_seen = state.get("last_seen_trade_ts")
        last_seen_dt = self._parse_ts(last_seen)
        new_trades = [
            t for t in fresh
            if last_seen_dt is None or t["timestamp"] > last_seen_dt
        ]

        if not new_trades:
            return []

        # Fetch portfolio once per cycle (cheap) — used for size math.
        portfolio_value = await fetch_wallet_portfolio_value(wallet_address)
        signals: list[Signal] = []

        # Process oldest-first so SELL after BUY semantics on the same
        # market resolve in the right order.
        for trade in sorted(new_trades, key=lambda t: t["timestamp"]):
            try:
                sig = await self._decide_and_build(
                    sb, module_id, wallet, wallet_weight, trade, cfg, bankroll, portfolio_value,
                )
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                log.warning(f"copy_trading decide failed (trade={trade.get('whale_trade_id')}): {e}")
                self._log_decision(sb, module_id, wallet_id, trade, "skipped_error",
                                   skip_reason=str(e)[:200])

        # Bump last_seen_trade_ts to the newest trade we considered (even
        # if every one was skipped — so we don't keep re-evaluating them).
        newest_ts = max(t["timestamp"] for t in new_trades)
        self._update_last_seen(sb, wallet_id, newest_ts)

        return signals

    async def _decide_and_build(
        self, sb, module_id: str, wallet: dict, wallet_weight: float,
        trade: dict, cfg: dict, bankroll: float, portfolio_value: float,
    ) -> Signal | None:
        wallet_id = wallet["id"]

        # Dedupe check: was this whale_trade_id already logged? If yes, skip.
        if self._already_logged(sb, wallet_id, trade["whale_trade_id"]):
            self._log_decision(sb, module_id, wallet_id, trade, SKIP_DEDUPE,
                               skip_reason="already logged for this wallet")
            return None

        # Current market book — needed for drift gate + price building.
        book = await self._fetch_book(trade)
        current_best_bid = float(book.get("best_bid") or 0.0)
        current_best_ask = float(book.get("best_ask") or 0.0)
        current_mid = (current_best_bid + current_best_ask) / 2.0 if (current_best_bid > 0 and current_best_ask > 0) else max(current_best_bid, current_best_ask)

        # Drift gate
        if is_drifted(trade["price"], current_mid, float(cfg["max_price_drift_pct"])):
            self._log_decision(sb, module_id, wallet_id, trade, SKIP_DRIFT,
                               skip_reason=f"|{current_mid:.4f} - {trade['price']:.4f}| / {trade['price']:.4f} > {cfg['max_price_drift_pct']}%")
            return None

        market_id = trade["market_id"]
        token_id = trade.get("asset") or None
        event_slug = trade.get("event_slug") or None

        if trade["side"] == "BUY":
            existing_wallet_exposure = self._wallet_exposure_usd(sb, wallet_id)
            existing_market_notional = self._our_market_notional_usd(sb, module_id, wallet_id, market_id)
            size_usd, skip = compute_buy_size_usd(
                whale_price=trade["price"],
                whale_size_shares=trade["size"],
                whale_portfolio_value=portfolio_value,
                our_bankroll=bankroll,
                wallet_weight_pct=wallet_weight,
                per_trade_cap_pct=float(cfg["per_trade_cap_pct"]),
                per_wallet_cap_pct=float(cfg["per_wallet_cap_pct"]),
                our_existing_wallet_exposure_usd=existing_wallet_exposure,
                our_existing_market_notional_usd=existing_market_notional,
            )
            if skip is not None:
                self._log_decision(sb, module_id, wallet_id, trade, skip,
                                   skip_reason=f"buy sizer returned {skip}")
                return None

            if cfg.get("shadow_mode", True):
                self._log_decision(sb, module_id, wallet_id, trade, MIRRORED,
                                   skip_reason="shadow_mode: no signal emitted")
                return None

            sig = build_buy_signal(
                module_id=module_id, market_id=market_id, token_id=token_id,
                bracket=None, whale_price=trade["price"],
                current_best_bid=current_best_bid, current_best_ask=current_best_ask,
                size_usd=size_usd, our_bankroll=bankroll,
                wallet_id=wallet_id, wallet_address=wallet["wallet_address"],
                whale_trade_id=trade["whale_trade_id"], event_slug=event_slug,
                shadow_mode=False,
            )
            self._log_decision(sb, module_id, wallet_id, trade, MIRRORED)
            return sig

        # SELL path
        our_position = self._our_wallet_attributed_position(sb, module_id, wallet_id, market_id)
        if not our_position or float(our_position.get("size") or 0) <= 0:
            self._log_decision(sb, module_id, wallet_id, trade, SKIP_NO_POSITION,
                               skip_reason="no wallet-attributed position to sell")
            return None

        whale_pos_before = self._whale_position_size_before(sb, wallet_id, market_id, trade)
        sell_fraction = compute_sell_proportion(
            whale_size_sold=trade["size"], whale_position_size_before=whale_pos_before,
        )
        if sell_fraction <= 0:
            self._log_decision(sb, module_id, wallet_id, trade, SKIP_ZERO_SIZE,
                               skip_reason="sell fraction zero")
            return None

        if cfg.get("shadow_mode", True):
            self._log_decision(sb, module_id, wallet_id, trade, MIRRORED,
                               skip_reason="shadow_mode: no signal emitted")
            return None

        sig = build_sell_signal(
            module_id=module_id, market_id=market_id, token_id=token_id,
            bracket=None, sell_fraction=sell_fraction,
            current_best_bid=current_best_bid, current_best_ask=current_best_ask,
            wallet_id=wallet_id, wallet_address=wallet["wallet_address"],
            whale_trade_id=trade["whale_trade_id"],
            position_id=our_position.get("id"), event_slug=event_slug, shadow_mode=False,
        )
        self._log_decision(sb, module_id, wallet_id, trade, MIRRORED)
        return sig

    # ------------------------------------------------------------------
    # State / DB helpers
    # ------------------------------------------------------------------

    def _get_state(self, sb, wallet_id: str) -> dict:
        try:
            res = sb.table("copy_trade_state").select("*").eq("wallet_id", wallet_id).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            log.warning(f"_get_state failed: {e}")
        # Insert empty row on first poll so subsequent updates work.
        try:
            sb.table("copy_trade_state").insert({"wallet_id": wallet_id}).execute()
        except Exception:
            pass
        return {}

    def _touch_polled(self, sb, wallet_id: str):
        try:
            sb.table("copy_trade_state").upsert({
                "wallet_id": wallet_id,
                "last_polled_at": datetime.now(timezone.utc).isoformat(),
                "consecutive_poll_failures": 0,
            }).execute()
        except Exception:
            pass

    def _update_last_seen(self, sb, wallet_id: str, ts: datetime):
        try:
            sb.table("copy_trade_state").upsert({
                "wallet_id": wallet_id,
                "last_seen_trade_ts": ts.isoformat(),
                "last_polled_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            log.warning(f"_update_last_seen failed for {wallet_id}: {e}")

    def _handle_poll_failure(self, sb, wallet: dict, err_msg: str):
        try:
            current = sb.table("copy_trade_state").select("consecutive_poll_failures").eq(
                "wallet_id", wallet["id"],
            ).execute()
            current_failures = 0
            if current.data:
                current_failures = int(current.data[0].get("consecutive_poll_failures") or 0)
            sb.table("copy_trade_state").upsert({
                "wallet_id": wallet["id"],
                "consecutive_poll_failures": current_failures + 1,
                "last_polled_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

    def _already_logged(self, sb, wallet_id: str, whale_trade_id: str) -> bool:
        try:
            res = sb.table("copy_trade_log").select("id").eq(
                "wallet_id", wallet_id,
            ).eq("whale_trade_id", whale_trade_id).limit(1).execute()
            return bool(res.data)
        except Exception:
            return False

    def _log_decision(
        self, sb, module_id: str, wallet_id: str, trade: dict, action: str,
        skip_reason: str | None = None, our_signal_id: str | None = None,
    ):
        try:
            sb.table("copy_trade_log").insert({
                "wallet_id": wallet_id,
                "module_id": module_id,
                "whale_trade_id": trade["whale_trade_id"],
                "whale_trade_ts": trade["timestamp"].isoformat() if isinstance(trade["timestamp"], datetime) else trade["timestamp"],
                "whale_side": trade["side"],
                "whale_price": trade["price"],
                "whale_size": trade["size"],
                "market_id": trade.get("market_id") or "",
                "bracket": None,
                "our_action": action,
                "skip_reason": skip_reason,
                "our_signal_id": our_signal_id,
            }).execute()
        except Exception as e:
            log.warning(f"_log_decision insert failed: {e}")

    def _auto_disable_wallet(self, sb, wallet_id: str, reason: str):
        try:
            sb.table("copy_trade_wallets").update({
                "enabled": False,
                "auto_disabled_at": datetime.now(timezone.utc).isoformat(),
                "auto_disabled_reason": reason,
            }).eq("id", wallet_id).execute()
        except Exception as e:
            log.warning(f"_auto_disable_wallet failed: {e}")

    def _daily_realized_pnl(self, sb, module_id: str) -> float:
        """Sum of realized_pnl from copy_trade_log for today (UTC)."""
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            res = sb.table("copy_trade_log").select("realized_pnl").eq(
                "module_id", module_id,
            ).gte("created_at", f"{today}T00:00:00+00:00").execute()
            return float(sum(float(r.get("realized_pnl") or 0) for r in (res.data or [])))
        except Exception:
            return 0.0

    def _wallet_exposure_usd(self, sb, wallet_id: str) -> float:
        """Sum of notional from open positions tagged with this wallet_id.

        We attribute by copy_source_wallet in order metadata. Phase 1 keeps
        this simple: scan positions where metadata->>copy_wallet_id matches.
        """
        try:
            res = sb.table("positions").select("size,avg_price,metadata,status").execute()
            total = 0.0
            for p in (res.data or []):
                if (p.get("status") or "").lower() != "open":
                    continue
                meta = p.get("metadata") or {}
                if isinstance(meta, dict) and str(meta.get("copy_wallet_id") or "") == str(wallet_id):
                    total += float(p.get("size") or 0) * float(p.get("avg_price") or 0)
            return total
        except Exception:
            return 0.0

    def _our_market_notional_usd(self, sb, module_id: str, wallet_id: str, market_id: str) -> float:
        try:
            res = sb.table("positions").select("size,avg_price,metadata,status,module_id,market_id").eq(
                "module_id", module_id,
            ).eq("market_id", market_id).execute()
            total = 0.0
            for p in (res.data or []):
                if (p.get("status") or "").lower() != "open":
                    continue
                meta = p.get("metadata") or {}
                if isinstance(meta, dict) and str(meta.get("copy_wallet_id") or "") == str(wallet_id):
                    total += float(p.get("size") or 0) * float(p.get("avg_price") or 0)
            return total
        except Exception:
            return 0.0

    def _our_wallet_attributed_position(self, sb, module_id: str, wallet_id: str, market_id: str) -> dict | None:
        try:
            res = sb.table("positions").select("*").eq("module_id", module_id).eq("market_id", market_id).execute()
            for p in (res.data or []):
                if (p.get("status") or "").lower() != "open":
                    continue
                meta = p.get("metadata") or {}
                if isinstance(meta, dict) and str(meta.get("copy_wallet_id") or "") == str(wallet_id):
                    return p
        except Exception:
            return None
        return None

    def _whale_position_size_before(self, sb, wallet_id: str, market_id: str, trade: dict) -> float:
        """Estimate the whale's position size on this market BEFORE this
        SELL trade. Phase 1: walk our copy_trade_log mirrored BUYs minus
        prior SELLs for the same (wallet, market). When unknown, fall back
        to trade.size (treat as full exit)."""
        try:
            res = sb.table("copy_trade_log").select("whale_side,whale_size,whale_trade_ts").eq(
                "wallet_id", wallet_id,
            ).eq("market_id", market_id).eq("our_action", "mirrored").execute()
            bought = 0.0
            sold = 0.0
            for r in (res.data or []):
                if (r.get("whale_side") or "").upper() == "BUY":
                    bought += float(r.get("whale_size") or 0)
                else:
                    sold += float(r.get("whale_size") or 0)
            inferred = max(bought - sold, 0.0)
            if inferred > 0:
                return inferred
        except Exception:
            pass
        return float(trade.get("size") or 0)

    async def _fetch_book(self, trade: dict) -> dict:
        """Best-effort order book for the market the whale traded on.

        Phase 1: use shared.polymarket.fetch_order_book on the asset token
        id when present. On failure, return empty bid/ask — the drift gate
        will pass (we don't punish on missing book) and the executor will
        snap to the whale's price."""
        token_id = trade.get("asset")
        if not token_id:
            return {}
        try:
            from api.modules.shared.polymarket import fetch_order_book
            book = await fetch_order_book(token_id)
            return book or {}
        except Exception as e:
            log.debug(f"copy_trading _fetch_book failed for token={token_id}: {e}")
            return {}

    def _parse_ts(self, ts) -> datetime | None:
        if ts is None:
            return None
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

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
