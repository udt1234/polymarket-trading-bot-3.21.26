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
    # ERC-1155 CLOB token ID (256-bit integer as string). REQUIRED for live
    # execution — CLOB rejects `tokenID = bracket label`. Populated by
    # module emitters from `market["token1"]` (Gamma `clobTokenIds[0]` for
    # YES). When unset, LiveExecutor refuses to submit the order.
    token_id: str | None = None


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
        except Exception as e:
            # Was silently swallowed pre-2026-05-16. If state load fails on
            # boot, we silently default to consecutive_losses=0 + tripped=False,
            # which means a real prior trip would be FORGOTTEN and the bot
            # would resume trading despite the recent loss streak. Surface so
            # the operator can investigate before that becomes a real loss.
            log.error(f"_load_persisted_state failed — circuit breaker resumes at DEFAULT (0 losses, not tripped); investigate: {e}")

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
        except Exception as e:
            # If persist fails, the next process restart will read whatever
            # was last successfully persisted. That could roll BACK a real
            # circuit-breaker trip, causing the bot to resume trading on a
            # losing streak. Surface to logs.
            log.error(f"_persist_state failed — circuit-breaker state may not survive restart (losses={self.consecutive_losses}, tripped={self.circuit_breaker_tripped}): {e}")

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
            self._check_negative_ev_aggregate,
            self._check_auction_aggregate_price,
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
        # Structural strategies (e.g. spike_trading) intentionally set edge=0
        # because their thesis isn't "model price > market price" — it's
        # "buy a lottery ticket at a fixed cheap price". Let them through
        # via an explicit opt-out flag in metadata. Other strategies still
        # face the global floor. Spike sizing is bounded by its own
        # bracket_cap_pct_of_bankroll and stop_loss_pct.
        meta = signal.metadata or {}
        if meta.get("skip_edge_check") is True:
            return True, ""
        # Modules can RAISE the bar via signal metadata, but never lower it below the global floor
        meta_threshold = meta.get("min_edge_threshold")
        if meta_threshold is None:
            threshold = settings.min_edge_threshold
        else:
            threshold = max(float(meta_threshold), settings.min_edge_threshold)
        if abs(signal.edge) < threshold:
            return False, f"edge {signal.edge:.4f} below threshold {threshold}"
        return True, ""

    def _check_kelly_valid(self, signal: Signal, settings) -> tuple[bool, str]:
        if signal.kelly_pct <= 0:
            return False, "negative kelly"
        return True, ""

    def _check_position_size(self, signal: Signal, settings) -> tuple[bool, str]:
        # kelly_pct semantics differ by side:
        #   BUY  -> fraction of bankroll to deploy (must obey the per-market cap)
        #   SELL -> fraction of the existing position to liquidate (1.0 = full
        #           exit, which is the normal SELL-NOW emergency-exit path).
        # Without the side gate, every Spike SELL-NOW would be rejected with
        # "kelly 1.0 exceeds max single market 0.15" — the bot would be unable
        # to exit a losing or expiring position.
        if signal.side == "SELL":
            return True, ""
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
        # SELL signals REDUCE portfolio exposure, so the per-cycle BUY-cap
        # check doesn't apply. Without this gate, a SELL with kelly_pct=1.0
        # gets treated as adding 100% of bankroll to exposure and is rejected.
        if signal.side == "SELL":
            return True, ""
        try:
            sb = get_supabase()
            positions = sb.table("positions").select("size,avg_price").eq("status", "open").execute()
            total_exposure = sum(abs(p["size"] * p["avg_price"]) for p in positions.data)
            # ALSO count unfilled BUY orders resting on the book — GTC limits
            # that haven't crossed yet still represent committed exposure
            # because they can fill any time. Without this, multi-profile
            # Spike laddering can silently exceed the portfolio cap.
            unfilled = sb.table("orders").select("size,price,side,status").eq("status", "submitted").execute()
            for o in (unfilled.data or []):
                if (o.get("side") or "").upper() == "BUY":
                    total_exposure += abs((o.get("size") or 0) * (o.get("price") or 0))
            new_notional = signal.kelly_pct * settings.bankroll
            if (total_exposure + new_notional) / settings.bankroll > settings.max_portfolio_exposure:
                return False, f"portfolio exposure {(total_exposure + new_notional) / settings.bankroll:.2%} exceeds {settings.max_portfolio_exposure:.0%}"
        except Exception as e:
            log.error(f"Portfolio exposure check failed (fail-closed): {e}")
            return False, "portfolio exposure check unavailable — DB error"
        return True, ""

    def _check_single_market_exposure(self, signal: Signal, settings) -> tuple[bool, str]:
        # SELL is an unwind — kelly_pct=1.0 means "100% of THIS position", not
        # 100% of bankroll. Single-market exposure caps don't apply to exits.
        if signal.side == "SELL":
            return True, ""
        try:
            sb = get_supabase()
            positions = sb.table("positions").select("size,avg_price").eq("status", "open").eq("market_id", signal.market_id).eq("bracket", signal.bracket).execute()
            existing = sum(abs(p["size"] * p["avg_price"]) for p in positions.data)
            # Count unfilled BUY orders for THIS market+bracket too. Same
            # rationale as portfolio exposure: resting GTC limits commit us.
            unfilled = sb.table("orders").select("size,price,side,status").eq("status", "submitted").eq("market_id", signal.market_id).eq("bracket", signal.bracket).execute()
            for o in (unfilled.data or []):
                if (o.get("side") or "").upper() == "BUY":
                    existing += abs((o.get("size") or 0) * (o.get("price") or 0))
            new_notional = signal.kelly_pct * settings.bankroll
            if (existing + new_notional) / settings.bankroll > settings.max_single_market_exposure:
                return False, f"single market exposure exceeded for {signal.bracket}"
        except Exception as e:
            log.error(f"Single market exposure check failed (fail-closed): {e}")
            return False, "single market exposure check unavailable — DB error"
        return True, ""

    def _check_correlated_exposure(self, signal: Signal, settings) -> tuple[bool, str]:
        # SELL unwinds, doesn't add exposure.
        if signal.side == "SELL":
            return True, ""
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

    def _check_negative_ev_aggregate(self, signal: Signal, settings) -> tuple[bool, str]:
        """
        For mutually-exclusive bracket markets (Polymarket style), only one bracket wins and pays $1/share.
        If we're already holding positions in other brackets in this market, the total EV of adding
        this new signal must be positive.

        EV = sum over brackets of [ P(bracket wins) × shares_in_bracket × $1 ] - total_cost

        Structural strategies (e.g. spike_trading) opt out via skip_edge_check
        — they don't have a model_prob to compute EV from, so this check
        would always reject them. Their sizing is bounded by their own
        per-tier % caps.
        """
        # SELL doesn't add bracket exposure — the aggregate-EV check is a
        # BUY-only entry gate.
        if signal.side == "SELL":
            return True, ""
        if (signal.metadata or {}).get("skip_edge_check") is True:
            return True, ""
        try:
            sb = get_supabase()
            existing = sb.table("positions").select("bracket,size,avg_price").eq("status", "open").eq("market_id", signal.market_id).eq("side", "BUY").execute()
            positions = existing.data or []

            by_bracket: dict = {}
            for p in positions:
                b = p["bracket"]
                cost = (p.get("size") or 0) * (p.get("avg_price") or 0)
                shares = p.get("size") or 0
                prev = by_bracket.get(b, {"shares": 0, "cost": 0})
                by_bracket[b] = {"shares": prev["shares"] + shares, "cost": prev["cost"] + cost}

            new_shares = (signal.kelly_pct * settings.bankroll) / max(signal.market_price, 0.001)
            new_cost = new_shares * signal.market_price

            b = signal.bracket
            prev = by_bracket.get(b, {"shares": 0, "cost": 0})
            by_bracket[b] = {"shares": prev["shares"] + new_shares, "cost": prev["cost"] + new_cost}

            total_cost = sum(x["cost"] for x in by_bracket.values())

            probs = (signal.metadata or {}).get("bracket_probs", {}) if signal.metadata else {}
            if not probs:
                probs = {signal.bracket: signal.model_prob}

            expected_payout = 0.0
            for b, info in by_bracket.items():
                p_win = float(probs.get(b, 0))
                expected_payout += p_win * info["shares"]

            ev = expected_payout - total_cost
            if ev < 0:
                return False, f"aggregate EV negative: payout ${expected_payout:.2f} < cost ${total_cost:.2f}"
        except Exception as e:
            # Fail-CLOSED to match every other exposure check in this file.
            # Prior fail-open was inconsistent and flagged in the 2026-04-27 QA pass.
            log.error(f"Aggregate EV check failed (fail-closed): {e}")
            return False, "aggregate EV check unavailable — DB error"
        return True, ""

    def _check_auction_aggregate_price(self, signal: Signal, settings) -> tuple[bool, str]:
        """Cap the SUM of avg_prices across all brackets we hold in this auction.

        In a mutually-exclusive bracket market, exactly one bracket pays $1/share.
        The sum of per-bracket avg_prices is the implied probability mass we've
        bought. If we keep that sum below the ceiling (default 0.65), then any
        winning bracket guarantees a positive return.

        Per-module override via signal.metadata['auction_aggregate_price_ceiling'].
        Set to 0 (or None) to disable.
        """
        # SELL exits don't add new bracket exposure to the aggregate cap.
        if signal.side == "SELL":
            return True, ""
        # Per-module override via signal metadata. Modules may set this STRICTER
        # (lower) than the global floor — but the floor itself caps the maximum
        # leniency, mirroring the min_edge_threshold pattern. If both are 0 the
        # check is fully disabled (operator opt-out via settings).
        meta_ceiling = (signal.metadata or {}).get("auction_aggregate_price_ceiling")
        floor = float(getattr(settings, "auction_aggregate_price_ceiling_floor", 0.0) or 0.0)
        meta_ceiling_f = float(meta_ceiling) if meta_ceiling is not None else 0.0
        if meta_ceiling_f > 0 and floor > 0:
            ceiling = min(meta_ceiling_f, floor)
        elif meta_ceiling_f > 0:
            ceiling = meta_ceiling_f
        elif floor > 0:
            ceiling = floor
        else:
            return True, ""
        try:
            sb = get_supabase()
            existing = (
                sb.table("positions")
                .select("bracket,avg_price")
                .eq("status", "open")
                .eq("market_id", signal.market_id)
                .eq("side", "BUY")
                .execute()
            )
            # Sum per-bracket avg_price across distinct brackets we already hold.
            by_bracket: dict[str, float] = {}
            for p in existing.data or []:
                b = p.get("bracket")
                ap = float(p.get("avg_price") or 0)
                if b and ap > 0:
                    by_bracket[b] = max(by_bracket.get(b, 0.0), ap)
            current_sum = sum(by_bracket.values())
            # If we're adding to an existing bracket, the avg_price changes — for the
            # purposes of this check, use whichever is higher (the new market_price is
            # what we'd buy at right now, so it's the worst-case contribution).
            new_contribution = max(by_bracket.get(signal.bracket, 0.0), float(signal.market_price))
            projected_sum = current_sum - by_bracket.get(signal.bracket, 0.0) + new_contribution
            if projected_sum > ceiling:
                return False, (
                    f"auction aggregate price ${projected_sum:.2f} would exceed "
                    f"ceiling ${ceiling:.2f} (current ${current_sum:.2f} + new bracket "
                    f"{signal.bracket} @ ${new_contribution:.2f})"
                )
        except Exception as e:
            log.error(f"Auction aggregate price check failed (fail-closed): {e}")
            return False, "auction aggregate price check unavailable — DB error"
        return True, ""

    def _check_duplicate(self, signal: Signal, settings) -> tuple[bool, str]:
        try:
            sb = get_supabase()
            # Must scope by market_id too — Spike can run on multiple concurrent
            # 2-day auctions (e.g. current + pre-launched next), and each lives
            # in a different market. Without this filter, a position in
            # auction A's `<40` blocks valid entries in auction B's `<40`.
            existing = (
                sb.table("positions")
                .select("id,avg_price,module_id,market_id")
                .eq("status", "open")
                .eq("module_id", signal.module_id)
                .eq("market_id", signal.market_id)
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
        # SELL must be allowed near settlement — that's WHEN SELL-NOW fires.
        # Blocking exits within 2h of close would strand positions on dying
        # brackets through final resolution.
        if signal.side == "SELL":
            return True, ""
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
        # Structural strategies (spike_trading) place LIMIT BUY orders that
        # may be well below the current bid — they intentionally don't care
        # about the live spread because they wait for the market to come to
        # them. SELL signals (SELL-NOW exits) DO care about the spread —
        # crossing a wide spread on exit is real slippage. Only bypass for
        # BUY side.
        if (signal.metadata or {}).get("skip_edge_check") is True and signal.side == "BUY":
            return True, ""
        # Emergency-exit bypass for SELL signals: when a position MUST close
        # (auction near settlement, bracket dying), refusing the exit because
        # spread is wide is the wrong call — the alternative is holding to
        # zero. Logged loudly so we can detect misuse.
        if (signal.metadata or {}).get("force_exit") is True and signal.side == "SELL":
            log.warning(
                f"SELL force_exit bypassing spread check: "
                f"bracket={signal.bracket} market={signal.market_id} "
                f"reason={(signal.metadata or {}).get('reason', 'unspecified')}"
            )
            return True, ""
        # Either default sentinel means no real book data was populated by the
        # module (Signal dataclass defaults: best_bid=0.0, best_ask=1.0). Prior
        # AND condition only matched when BOTH defaults were present, leaving a
        # gap where best_bid=0.0 + a non-1 ask passed through.
        if signal.best_bid == 0.0 or signal.best_ask == 1.0:
            # Cheap-lottery BUYs intentionally target thin/empty books — buying
            # 0.3¢-5¢ tickets and holding to resolution is the whole thesis.
            # Killing them because Gamma returned bestBid=null was eating 90%
            # of Truth Social's signals on 100-119 / 120-139 brackets where
            # nobody else is bidding. Let cheap BUYs through; SELLs still
            # require a real book (crossing on exit is real slippage).
            if signal.side == "BUY" and signal.market_price < 0.10:
                return True, ""
            return False, "no order book data available — cannot verify spread"
        spread = signal.best_ask - signal.best_bid
        if spread <= 0:
            return False, f"crossed/locked book (bid={signal.best_bid:.4f}, ask={signal.best_ask:.4f})"
        if settings.slippage_tolerance > 0 and spread > settings.slippage_tolerance:
            return False, f"bid-ask spread {spread:.4f} exceeds tolerance {settings.slippage_tolerance}"
        return True, ""

    def _check_liquidity(self, signal: Signal, settings) -> tuple[bool, str]:
        # Structural strategies opt out for BUY — limit orders wait for fills,
        # depth at signal time isn't relevant. SELL signals must still verify
        # bid depth because they're crossing the spread to exit; an empty
        # bid side at SELL time means the order sails at any matching bid.
        if (signal.metadata or {}).get("skip_edge_check") is True and signal.side == "BUY":
            return True, ""
        # Emergency-exit bypass — see _check_spread comment. Holding a dying
        # position to zero is worse than crossing into an empty book.
        if (signal.metadata or {}).get("force_exit") is True and signal.side == "SELL":
            log.warning(
                f"SELL force_exit bypassing liquidity check: "
                f"bracket={signal.bracket} market={signal.market_id} "
                f"reason={(signal.metadata or {}).get('reason', 'unspecified')}"
            )
            return True, ""
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
                from api.services.engine import _fire_and_forget_async
                from api.services.notifications import notify_circuit_breaker
                from api.services.alerts import notify_bot_paused
                # Fire-and-forget to avoid blocking the engine cycle for up
                # to 20 seconds (two 10s httpx timeouts). Code review caught
                # this as a real stall risk on slow Slack endpoints.
                _fire_and_forget_async(
                    notify_circuit_breaker(self.consecutive_losses, settings.circuit_breaker_cooldown_minutes)
                )
                _fire_and_forget_async(notify_bot_paused(
                    reason=f"Circuit breaker tripped after {self.consecutive_losses} consecutive losses",
                    scope="circuit_breaker",
                    details={
                        "cooldown_minutes": settings.circuit_breaker_cooldown_minutes,
                        "consecutive_losses": self.consecutive_losses,
                    },
                ))
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
            mod_row = sb.table("modules").select("name,status").eq("id", module_id).single().execute()
            old_status = (mod_row.data or {}).get("status", "active")
            mod_name = (mod_row.data or {}).get("name") or module_id
            sb.table("modules").update({
                "status": "inactive",
                "inactive_reason": "circuit_breaker",
                "inactive_since": datetime.now(timezone.utc).isoformat(),
                "inactive_detail": f"Auto-paused after {self.consecutive_losses} consecutive losses",
            }).eq("id", module_id).execute()
            sb.table("logs").insert({
                "level": "warning",
                "message": f"Auto-kill: module paused after {self.consecutive_losses} consecutive losses",
                "module_id": module_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            log.warning(f"AUTO-KILL: Module {module_id} paused after {self.consecutive_losses} consecutive losses")
            try:
                from api.services.engine import _fire_and_forget_async
                from api.services.alerts import notify_module_status_change
                _fire_and_forget_async(notify_module_status_change(
                    module_id=module_id,
                    name=mod_name,
                    old_status=old_status,
                    new_status="inactive",
                    reason=f"Circuit breaker: {self.consecutive_losses} consecutive losses",
                ))
            except Exception:
                pass
        except Exception as e:
            log.error(f"Failed to auto-pause module {module_id}: {e}")

    def update_pnl(self, daily: float, weekly: float, peak: float, current: float):
        self._daily_pnl = daily
        self._weekly_pnl = weekly
        self._peak_value = peak
        self._risk_synced = True
        self._current_value = current

    def mark_synced_empty(self):
        """Mark risk state as synced with NO historical PnL data — used when
        daily_pnl table is empty (fresh deploy, paper mode, or first-ever run).
        Loss-cap checks then evaluate against zero PnL (no losses yet =
        cap not hit) instead of fail-closed blocking every trade forever.

        Without this, a clean Supabase install has _risk_synced=False
        permanently, _check_daily_loss / _weekly_loss / _drawdown all
        return False with "risk state not synced", and the bot silently
        rejects every signal."""
        self._daily_pnl = 0.0
        self._weekly_pnl = 0.0
        self._peak_value = 0.0
        self._current_value = 0.0
        self._risk_synced = True

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
        except Exception as e:
            # Was a silent pass — log the cause so it is visible in Railway.
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"signals insert failed (rejection log) module={signal.module_id} bracket={signal.bracket}: {e}"
            )
