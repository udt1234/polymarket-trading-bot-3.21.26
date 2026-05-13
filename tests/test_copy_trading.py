"""Phase 1 acceptance tests for the copy_trading module.

Covers the 5 mandatory cases listed in COPY_TRADING_MODULE_SPEC.md §6:
  1. Dedupe — same whale_trade_id processed twice → second is skipped
  2. Staleness gate — trades older than max_trade_age_sec are skipped
  3. Per-trade cap — order size clipped at per_trade_cap_pct of bankroll
  4. Daily-loss circuit — module pauses when realized daily P&L breaches
  5. Cold-start drop — on startup, trades older than max_trade_age_sec
     are dropped wholesale (no flood of stale orders)
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from api.modules.copy_trading.decision import (
    is_stale, is_drifted, compute_buy_size_usd, compute_sell_proportion,
    daily_loss_breached, whale_perf_gate_breached,
    SKIP_CAP, SKIP_ZERO_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(ts: datetime, side: str = "BUY", price: float = 0.10, size: float = 100.0,
           whale_trade_id: str = "tx-abc"):
    return {
        "whale_trade_id": whale_trade_id,
        "timestamp": ts,
        "side": side,
        "price": price,
        "size": size,
        "asset": "tok-1",
        "condition_id": "cond-1",
        "market_id": "cond-1",
        "event_slug": "elon-tweets-48h-100-119",
    }


# ---------------------------------------------------------------------------
# 1. Dedupe — same whale_trade_id seen twice should not double-emit
# ---------------------------------------------------------------------------

class TestDedupe:
    def test_already_logged_short_circuits(self):
        """If copy_trade_log already has a row for (wallet_id, whale_trade_id),
        the module's _already_logged() returns True and no signal is built."""
        from api.modules.copy_trading.module import CopyTradingModule
        mod = CopyTradingModule()

        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "log-row-1"}
        ]
        assert mod._already_logged(sb, "wallet-1", "tx-abc") is True

    def test_not_logged_returns_false(self):
        from api.modules.copy_trading.module import CopyTradingModule
        mod = CopyTradingModule()
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        assert mod._already_logged(sb, "wallet-1", "tx-abc") is False


# ---------------------------------------------------------------------------
# 2. Staleness gate — trades older than max_trade_age_sec skipped
# ---------------------------------------------------------------------------

class TestStalenessGate:
    def test_fresh_trade_not_stale(self):
        now = datetime.now(timezone.utc)
        ts = now - timedelta(seconds=60)
        assert is_stale(ts, max_age_sec=300, now=now) is False

    def test_trade_exactly_at_threshold_not_stale(self):
        # Boundary: exactly max_age_sec old should still pass (>, not >=)
        now = datetime.now(timezone.utc)
        ts = now - timedelta(seconds=300)
        assert is_stale(ts, max_age_sec=300, now=now) is False

    def test_old_trade_is_stale(self):
        now = datetime.now(timezone.utc)
        ts = now - timedelta(seconds=600)
        assert is_stale(ts, max_age_sec=300, now=now) is True


# ---------------------------------------------------------------------------
# 3. Per-trade size cap — size clipped at per_trade_cap_pct * bankroll
# ---------------------------------------------------------------------------

class TestPerTradeCap:
    def test_per_trade_cap_clips_oversized_target(self):
        # Whale uses 50% of their book ($500 on $1000 portfolio).
        # We would target 50% of our bankroll ($500), but per_trade_cap is
        # 1% so we should clip to $10.
        size_usd, skip = compute_buy_size_usd(
            whale_price=0.10, whale_size_shares=5000,  # $500 notional
            whale_portfolio_value=1000.0,
            our_bankroll=1000.0, wallet_weight_pct=1.0,
            per_trade_cap_pct=1.0, per_wallet_cap_pct=5.0,
            our_existing_wallet_exposure_usd=0.0,
            our_existing_market_notional_usd=0.0,
        )
        assert skip is None
        assert size_usd == pytest.approx(10.0)

    def test_per_wallet_cap_rejects_when_over(self):
        # Existing exposure already at $50 with a 5% / $1000 = $50 cap.
        # New BUY must be rejected outright with SKIP_CAP.
        size_usd, skip = compute_buy_size_usd(
            whale_price=0.10, whale_size_shares=100,
            whale_portfolio_value=1000.0,
            our_bankroll=1000.0, wallet_weight_pct=1.0,
            per_trade_cap_pct=1.0, per_wallet_cap_pct=5.0,
            our_existing_wallet_exposure_usd=50.0,
            our_existing_market_notional_usd=0.0,
        )
        assert size_usd == 0.0
        assert skip == SKIP_CAP

    def test_topup_subtracts_existing_market_holdings(self):
        # Target would be $10 but we already hold $9.50 on this market.
        # Delta is $0.50, which is below the $1 floor → skip silently.
        size_usd, skip = compute_buy_size_usd(
            whale_price=0.10, whale_size_shares=5000,
            whale_portfolio_value=1000.0,
            our_bankroll=1000.0, wallet_weight_pct=1.0,
            per_trade_cap_pct=1.0, per_wallet_cap_pct=5.0,
            our_existing_wallet_exposure_usd=9.50,
            our_existing_market_notional_usd=9.50,
        )
        assert size_usd == 0.0
        assert skip == SKIP_ZERO_SIZE


# ---------------------------------------------------------------------------
# 4. Daily-loss circuit breaker — module pauses past threshold
# ---------------------------------------------------------------------------

class TestDailyLossCircuit:
    def test_no_breach_when_pnl_above_threshold(self):
        # -$15 P&L, -2% of $1000 = -$20 threshold. Not breached.
        assert daily_loss_breached(daily_pnl_usd=-15.0, bankroll=1000.0, circuit_pct=-2.0) is False

    def test_breach_at_or_past_threshold(self):
        # -$20 exactly = threshold → breached.
        assert daily_loss_breached(daily_pnl_usd=-20.0, bankroll=1000.0, circuit_pct=-2.0) is True

    def test_breach_well_past_threshold(self):
        assert daily_loss_breached(daily_pnl_usd=-100.0, bankroll=1000.0, circuit_pct=-2.0) is True

    def test_no_breach_with_zero_bankroll(self):
        # Defensive: don't divide-by-zero / treat unknown bankroll as breach.
        assert daily_loss_breached(daily_pnl_usd=-50.0, bankroll=0.0, circuit_pct=-2.0) is False

    def test_module_short_circuits_on_breach(self):
        """When the daily-loss check trips, _evaluate_one_row returns []
        before touching any wallets."""
        from api.modules.copy_trading.module import CopyTradingModule
        mod = CopyTradingModule()

        sb = MagicMock()
        # daily P&L = -$50 (well past -$20 threshold)
        sb.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value.data = [
            {"realized_pnl": -50.0},
        ]
        # wallets query MUST NOT be reached — return a tripwire row that
        # would otherwise produce a signal if the breach didn't short-circuit.
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "wallet-1", "wallet_address": "0xdead", "weight_pct": 1.0,
             "enabled": True, "module_id": "module-1"},
        ]

        import asyncio
        with patch("api.modules.copy_trading.module.get_module_config") as gmc, \
             patch("api.modules.copy_trading.module.get_settings") as gs:
            gmc.return_value = {
                "poll_interval_sec": 30, "max_trade_age_sec": 300,
                "max_price_drift_pct": 20.0,
                "per_wallet_cap_pct": 5.0, "per_trade_cap_pct": 1.0,
                "daily_loss_circuit_pct": -2.0,
                "whale_perf_gate_window": 10, "whale_perf_gate_min_roi_pct": -30.0,
                "shadow_mode": True,
            }
            gs.return_value = MagicMock(bankroll=1000.0)
            result = asyncio.run(mod._evaluate_one_row(sb, {"id": "module-1", "status": "paper"}))

        assert result == []


# ---------------------------------------------------------------------------
# 5. Cold-start drop — trades older than max_trade_age_sec dropped wholesale
# ---------------------------------------------------------------------------

class TestColdStartDrop:
    def test_cold_start_drops_old_trades(self):
        """On startup (last_seen_trade_ts is None), all polled trades older
        than max_trade_age_sec are filtered out before the diff step. The
        module must not flood the executor with a wallet's full history."""
        now = datetime.now(timezone.utc)
        recent = _trade(now - timedelta(seconds=30), whale_trade_id="tx-fresh")
        stale_5min = _trade(now - timedelta(minutes=10), whale_trade_id="tx-old1")
        stale_1day = _trade(now - timedelta(days=1), whale_trade_id="tx-ancient")

        trades = [recent, stale_5min, stale_1day]

        max_age = 300
        fresh = [t for t in trades if not is_stale(t["timestamp"], max_age, now=now)]
        stale = [t for t in trades if is_stale(t["timestamp"], max_age, now=now)]
        assert len(fresh) == 1
        assert fresh[0]["whale_trade_id"] == "tx-fresh"
        assert len(stale) == 2
        assert {t["whale_trade_id"] for t in stale} == {"tx-old1", "tx-ancient"}

    def test_cold_start_logs_each_stale_trade_as_skipped(self):
        """On startup, EVERY stale trade still gets a copy_trade_log row
        (action=skipped_stale). Auditability is non-negotiable."""
        from api.modules.copy_trading.module import CopyTradingModule
        mod = CopyTradingModule()

        sb = MagicMock()
        now = datetime.now(timezone.utc)
        stale_trade = _trade(now - timedelta(minutes=15), whale_trade_id="tx-old1")

        mod._log_decision(sb, "module-1", "wallet-1", stale_trade,
                          action="skipped_stale", skip_reason="cold-start drop")

        insert_call = sb.table.return_value.insert.call_args
        assert insert_call is not None
        row = insert_call.args[0]
        assert row["our_action"] == "skipped_stale"
        assert row["whale_trade_id"] == "tx-old1"
        assert row["whale_side"] == "BUY"


# ---------------------------------------------------------------------------
# Extra: bonus sanity checks for the other risk caps the spec requires
# ---------------------------------------------------------------------------

class TestWhalePerfGate:
    def test_no_gate_before_window_fills(self):
        # Only 5 copies done — window is 10 — no gate yet.
        assert whale_perf_gate_breached(
            recent_copy_count=5, recent_copy_roi_pct=-50.0,
            window=10, min_roi_pct=-30.0,
        ) is False

    def test_gate_trips_below_min_roi(self):
        assert whale_perf_gate_breached(
            recent_copy_count=10, recent_copy_roi_pct=-35.0,
            window=10, min_roi_pct=-30.0,
        ) is True

    def test_no_gate_above_min_roi(self):
        assert whale_perf_gate_breached(
            recent_copy_count=10, recent_copy_roi_pct=-25.0,
            window=10, min_roi_pct=-30.0,
        ) is False


class TestDriftGate:
    def test_no_drift_within_tolerance(self):
        assert is_drifted(whale_price=0.10, current_price=0.115, max_drift_pct=20.0) is False

    def test_drift_beyond_tolerance(self):
        assert is_drifted(whale_price=0.10, current_price=0.13, max_drift_pct=20.0) is True

    def test_no_drift_when_book_unknown(self):
        assert is_drifted(whale_price=0.10, current_price=0.0, max_drift_pct=20.0) is False


class TestSellProportion:
    def test_partial_sell(self):
        # Whale sold 30 of 100 shares → mirror 30%.
        assert compute_sell_proportion(whale_size_sold=30, whale_position_size_before=100) == pytest.approx(0.30)

    def test_full_exit(self):
        assert compute_sell_proportion(whale_size_sold=100, whale_position_size_before=100) == pytest.approx(1.0)

    def test_zero_position_returns_zero(self):
        assert compute_sell_proportion(whale_size_sold=50, whale_position_size_before=0) == 0.0
