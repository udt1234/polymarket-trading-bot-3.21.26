import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from api.config import get_settings
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


@dataclass
class Signal:
    module_id: str
    market_id: str
    bracket: str
    side: str
    edge: float
    model_prob: float
    market_price: float
    kelly_pct: float
    confidence: float = 1.0
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_depth_5: float = 0.0
    ask_depth_5: float = 0.0
    metadata: dict = field(default_factory=dict)
    post_detected_at: str | None = None


class RiskManager:
    def __init__(self):
        self.consecutive_losses = 0
        self.circuit_breaker_tripped = False
        self._cooldown_until = 0
        self._daily_pnl = 0.0
        self._weekly_pnl = 0.0
        self._peak_value = 0.0
        self._current_value = 0.0
        self._risk_synced = False
        self._load_persisted_state()

    def _load_persisted_state(self):
        try:
            sb = get_supabase()
            res = sb.table("settings").select("value").eq("key", "circuit_breaker_state").execute()
            if res.data:
                state = res.data[0].get("value", {})
                self.consecutive_losses = state.get("consecutive_losses", 0)
                self.circuit_breaker_tripped = state.get("tripped", False)
                self._cooldown_until = state.get("cooldown_until", 0)
                log.info(f"Loaded circuit breaker state: losses={self.consecutive_losses}, tripped={self.circuit_breaker_tripped}")
        except Exception:
            pass

    def _persist_state(self):
        try:
            sb = get_supabase()
            sb.table("settings").upsert({
                "key": "circuit_breaker_state",
                "value": {
                    "consecutive_losses": self.consecutive_losses,
                    "tripped": self.circuit_breaker_tripped,
                    "cooldown_until": self._cooldown_until,
                },
            }).execute()
        except Exception:
            pass

    def check(self, signal: Signal) -> tuple[bool, str]:
        settings = get_settings()
        checks = [
            self._check_circuit_breaker,
            self._check_edge_threshold,
            self._check_kelly_valid,
            self._check_position_size,
            self._check_daily_loss,
            self._check_weekly_loss,
            self._check_drawdown,
            self._check_portfolio_exposure,
            self._check_single_market_exposure,
            self._check_correlated_exposure,
            self._check_duplicate,
            self._check_cross_module_correlation,
            self._check_settlement_decay,
            self._check_spread,
            self._check_liquidity,
        ]
        for check_fn in checks:
            passed, reason = check_fn(signal, settings)
            if not passed:
                self._log_rejection(signal, reason)
                return False, reason
        return True, "approved"

    def _check_circuit_breaker(self, signal: Signal, settings) -> tuple[bool, str]:
        if not settings.circuit_breaker_enabled:
            return True, ""
        if self.circuit_breaker_tripped:
            if time.time() < self._cooldown_until:
                return False, "circuit breaker cooldown"
            self.circuit_breaker_tripped = False
            self.consecutive_losses = 0
        return True, ""

    def _check_edge_threshold(self, signal: Signal, settings) -> tuple[bool, str]:
        if abs(signal.edge) < settings.min_edge_threshold:
            return False, f"edge {signal.edge:.4f} below threshold {settings.min_edge_threshold}"
        return True, ""

    def _check_kelly_valid(self, signal: Signal, settings) -> tuple[bool, str]:
        if signal.kelly_pct <= 0:
            return False, "negative kelly"
        return True, ""

    def _check_position_size(self, signal: Signal, settings) -> tuple[bool, str]:
        if signal.kelly_pct > settings.max_single_market_exposure:
            return False, f"kelly {signal.kelly_pct:.4f} exceeds max single market {settings.max_single_market_exposure}"
        return True, ""

    def _check_daily_loss(self, signal: Signal, settings) -> tuple[bool, str]:
        if not self._risk_synced:
            return False, "risk state not synced — blocking until PnL data available"
        if self._daily_pnl < -(settings.bankroll * settings.daily_loss_limit):
            return False, "daily loss limit hit"
        return True, ""

    def _check_weekly_loss(self, signal: Signal, settings) -> tuple[bool, str]:
        if not self._risk_synced:
            return False, "risk state not synced — blocking until PnL data available"
        if self._weekly_pnl < -(settings.bankroll * settings.weekly_loss_limit):
            return False, "weekly loss limit hit"
        return True, ""

    def _check_drawdown(self, signal: Signal, settings) -> tuple[bool, str]:
        if not self._risk_synced:
            return False, "risk state not synced — blocking until PnL data available"
        if self._peak_value > 0:
            dd = (self._peak_value - self._current_value) / self._peak_value
            if dd > settings.max_drawdown:
                return False, f"drawdown {dd:.2%} exceeds max {settings.max_drawdown:.2%}"
        return True, ""

    def _check_portfolio_exposure(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            positions = sb.table("positions").select("size,avg_price").eq("status", "open").execute()
            total_exposure = sum(abs(p["size"] * p["avg_price"]) for p in positions.data)
            new_notional = signal.kelly_pct * settings.bankroll
            if (total_exposure + new_notional) / settings.bankroll > settings.max_portfolio_exposure:
                return False, f"portfolio exposure {(total_exposure + new_notional) / settings.bankroll:.2%} exceeds {settings.max_portfolio_exposure:.0%}"
        except Exception as e:
            log.error(f"Portfolio exposure check failed (fail-closed): {e}")
            return False, "portfolio exposure check unavailable — DB error"
        return True, ""

    def _check_single_market_exposure(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            positions = sb.table("positions").select("size,avg_price").eq("status", "open").eq("market_id", signal.market_id).eq("bracket", signal.bracket).execute()
            existing = sum(abs(p["size"] * p["avg_price"]) for p in positions.data)
            new_notional = signal.kelly_pct * settings.bankroll
            if (existing + new_notional) / settings.bankroll > settings.max_single_market_exposure:
                return False, f"single market exposure exceeded for {signal.bracket}"
        except Exception as e:
            log.error(f"Single market exposure check failed (fail-closed): {e}")
            return False, "single market exposure check unavailable — DB error"
        return True, ""

    def _check_correlated_exposure(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            positions = sb.table("positions").select("size,avg_price").eq("status", "open").eq("market_id", signal.market_id).execute()
            correlated = sum(abs(p["size"] * p["avg_price"]) for p in positions.data)
            new_notional = signal.kelly_pct * settings.bankroll
            if (correlated + new_notional) / settings.bankroll > settings.max_correlated_exposure:
                return False, f"correlated exposure exceeded for {signal.market_id}"
        except Exception as e:
            log.error(f"Correlated exposure check failed (fail-closed): {e}")
            return False, "correlated exposure check unavailable — DB error"
        return True, ""

    def _check_duplicate(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            existing = (
                sb.table("positions")
                .select("id,avg_price,module_id")
                .eq("status", "open")
                .eq("module_id", signal.module_id)
                .eq("bracket", signal.bracket)
                .execute()
            )
            if existing.data:
                pos = existing.data[0]
                orig_edge = pos["avg_price"]
                if orig_edge > 0:
                    entry_edge = signal.market_price - orig_edge
                    if signal.edge < entry_edge + 0.03:
                        return False, f"duplicate bracket {signal.bracket}: edge not improved by 3%+ (current={signal.edge:.4f})"
        except Exception as e:
            log.error(f"Duplicate check failed (fail-closed): {e}")
            return False, "duplicate check unavailable — DB error"
        return True, ""

    def _check_cross_module_correlation(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            positions = (
                sb.table("positions")
                .select("module_id,bracket,size,avg_price,side")
                .eq("status", "open")
                .execute()
            )
            if not positions.data:
                return True, ""

            high_brackets = {"100-119", "120-139", "140-159", "160-179", "180-199", "200+"}
            low_brackets = {"0-19", "20-39", "40-59"}

            is_high = signal.bracket in high_brackets
            is_low = signal.bracket in low_brackets

            if not is_high and not is_low:
                return True, ""

            target_set = high_brackets if is_high else low_brackets
            similar_notional = 0
            module_ids = set()
            for p in positions.data:
                if p["bracket"] in target_set and p["side"] == signal.side:
                    similar_notional += abs(p["size"] * p["avg_price"])
                    module_ids.add(p["module_id"])

            new_notional = signal.kelly_pct * settings.bankroll
            total = similar_notional + new_notional
            if len(module_ids) >= 2 and total / settings.bankroll > 0.30:
                return False, f"cross-module correlation: {len(module_ids)} modules, {total / settings.bankroll:.1%} in similar brackets"
        except Exception as e:
            log.error(f"Cross-module correlation check failed (fail-closed): {e}")
            return False, "cross-module correlation check unavailable — DB error"
        return True, ""

    def _check_settlement_decay(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            module = sb.table("modules").select("resolution_date").eq("id", signal.module_id).single().execute()
            if module.data and module.data.get("resolution_date"):
                res_date = datetime.fromisoformat(module.data["resolution_date"].replace("Z", "+00:00"))
                hours_remaining = (res_date - datetime.now(timezone.utc)).total_seconds() / 3600
                if hours_remaining < 2:
                    return False, "too close to settlement (<2h)"
                if hours_remaining < 12:
                    max_kelly = signal.kelly_pct * (hours_remaining / 24)
                    if max_kelly < 0.005:
                        return False, f"settlement decay reduced kelly to {max_kelly:.4f}"
        except Exception as e:
            log.error(f"Settlement decay check failed (fail-closed): {e}")
            return False, "settlement decay check unavailable — DB error"
        return True, ""

    def _check_spread(self, signal: Signal, settings) -> tuple[bool, str]:
        if signal.best_bid == 0.0 and signal.best_ask == 1.0:
            return False, "no order book data available — cannot verify spread"
        spread = signal.best_ask - signal.best_bid
        if spread <= 0:
            return False, f"crossed/locked book (bid={signal.best_bid:.4f}, ask={signal.best_ask:.4f})"
        if settings.slippage_tolerance > 0 and spread > settings.slippage_tolerance:
            return False, f"bid-ask spread {spread:.4f} exceeds tolerance {settings.slippage_tolerance}"
        return True, ""

    def _check_liquidity(self, signal: Signal, settings) -> tuple[bool, str]:
        depth = signal.ask_depth_5 if signal.side == "BUY" else signal.bid_depth_5
        target_size = signal.kelly_pct * settings.bankroll
        if depth <= 0:
            return False, "no order book depth available"
        max_fill = depth * 0.30
        if target_size > max_fill:
            return False, f"order size ${target_size:.2f} exceeds 30% of depth ${depth:.2f}"
        return True, ""

    def reset_circuit_breaker(self):
        self.circuit_breaker_tripped = False
        self.consecutive_losses = 0
        self._cooldown_until = 0
        self._persist_state()
        log.info("Circuit breaker MANUALLY RESET")

    def get_circuit_breaker_state(self) -> dict:
        remaining = max(0, int(self._cooldown_until - time.time())) if self.circuit_breaker_tripped else 0
        return {
            "tripped": self.circuit_breaker_tripped,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_until": self._cooldown_until,
            "cooldown_remaining_s": remaining,
        }

    def record_loss(self, module_id: str | None = None):
        settings = get_settings()
        self.consecutive_losses += 1
        if self.consecutive_losses >= settings.circuit_breaker_max_consecutive_losses:
            self.circuit_breaker_tripped = True
            self._cooldown_until = time.time() + settings.circuit_breaker_cooldown_minutes * 60
            log.warning(f"Circuit breaker TRIPPED after {self.consecutive_losses} consecutive losses")
            try:
                import asyncio as _asyncio
                from api.services.notifications import notify_circuit_breaker
                _asyncio.get_event_loop().run_until_complete(
                    notify_circuit_breaker(self.consecutive_losses, settings.circuit_breaker_cooldown_minutes)
                )
            except Exception:
                pass
        auto_kill_threshold = getattr(settings, "auto_kill_consecutive_losses", 0)
        if auto_kill_threshold > 0 and self.consecutive_losses >= auto_kill_threshold and module_id:
            self._auto_pause_module(module_id)
        self._persist_state()

    def record_win(self):
        self.consecutive_losses = 0
        self._persist_state()

    def _auto_pause_module(self, module_id: str):
        try:
            sb = get_supabase()
            sb.table("modules").update({"status": "paused"}).eq("id", module_id).execute()
            sb.table("logs").insert({
                "level": "warning",
                "message": f"Auto-kill: module paused after {self.consecutive_losses} consecutive losses",
                "module_id": module_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            log.warning(f"AUTO-KILL: Module {module_id} paused after {self.consecutive_losses} consecutive losses")
        except Exception as e:
            log.error(f"Failed to auto-pause module {module_id}: {e}")

    def update_pnl(self, daily: float, weekly: float, peak: float, current: float):
        self._daily_pnl = daily
        self._weekly_pnl = weekly
        self._peak_value = peak
        self._risk_synced = True
        self._current_value = current

    def _log_rejection(self, signal: Signal, reason: str):
        try:
            sb = get_supabase()
            now = datetime.now(timezone.utc).isoformat()
            sb.table("signals").insert({
                "module_id": signal.module_id,
                "market_id": signal.market_id,
                "bracket": signal.bracket,
                "side": signal.side,
                "edge": signal.edge,
                "model_prob": signal.model_prob,
                "market_price": signal.market_price,
                "kelly_pct": signal.kelly_pct,
                "approved": False,
                "rejection_reason": reason,
                "metadata": signal.metadata if signal.metadata else {},
                "post_detected_at": signal.post_detected_at or now,
            }).execute()
        except Exception:
            pass
