import time
import pytest
from unittest.mock import patch, MagicMock
from api.services.risk_manager import RiskManager, Signal
from tests.conftest import make_signal


class TestCircuitBreaker:
    def test_not_tripped_passes(self, risk_manager, settings):
        sig = make_signal()
        passed, _ = risk_manager._check_circuit_breaker(sig, settings)
        assert passed

    def test_tripped_within_cooldown_fails(self, risk_manager, settings):
        risk_manager.circuit_breaker_tripped = True
        risk_manager._cooldown_until = time.time() + 9999
        passed, reason = risk_manager._check_circuit_breaker(sig := make_signal(), settings)
        assert not passed
        assert "cooldown" in reason

    def test_tripped_after_cooldown_resets(self, risk_manager, settings):
        risk_manager.circuit_breaker_tripped = True
        risk_manager._cooldown_until = time.time() - 1
        passed, _ = risk_manager._check_circuit_breaker(make_signal(), settings)
        assert passed
        assert not risk_manager.circuit_breaker_tripped
        assert risk_manager.consecutive_losses == 0

    def test_disabled_always_passes(self, risk_manager, settings):
        settings.circuit_breaker_enabled = False
        risk_manager.circuit_breaker_tripped = True
        passed, _ = risk_manager._check_circuit_breaker(make_signal(), settings)
        assert passed

    def test_record_loss_trips_at_threshold(self, risk_manager):
        with patch("api.services.risk_manager.get_settings") as mock_gs:
            s = MagicMock()
            s.circuit_breaker_max_consecutive_losses = 3
            s.circuit_breaker_cooldown_minutes = 10
            mock_gs.return_value = s
            for _ in range(3):
                risk_manager.record_loss()
            assert risk_manager.circuit_breaker_tripped
            assert risk_manager._cooldown_until > time.time()

    def test_record_win_resets_counter(self, risk_manager):
        risk_manager.consecutive_losses = 4
        risk_manager.record_win()
        assert risk_manager.consecutive_losses == 0


class TestEdgeThreshold:
    def test_above_threshold_passes(self, risk_manager, settings):
        sig = make_signal(edge=0.05)
        passed, _ = risk_manager._check_edge_threshold(sig, settings)
        assert passed

    def test_below_threshold_fails(self, risk_manager, settings):
        sig = make_signal(edge=0.01)
        passed, _ = risk_manager._check_edge_threshold(sig, settings)
        assert not passed

    def test_exact_threshold_fails(self, risk_manager, settings):
        sig = make_signal(edge=0.019)
        passed, _ = risk_manager._check_edge_threshold(sig, settings)
        assert not passed

    def test_negative_edge_above_threshold_passes(self, risk_manager, settings):
        sig = make_signal(edge=-0.05)
        passed, _ = risk_manager._check_edge_threshold(sig, settings)
        assert passed


class TestKellyValid:
    def test_positive_kelly_passes(self, risk_manager, settings):
        passed, _ = risk_manager._check_kelly_valid(make_signal(kelly_pct=0.05), settings)
        assert passed

    def test_zero_kelly_fails(self, risk_manager, settings):
        passed, _ = risk_manager._check_kelly_valid(make_signal(kelly_pct=0), settings)
        assert not passed

    def test_negative_kelly_fails(self, risk_manager, settings):
        passed, _ = risk_manager._check_kelly_valid(make_signal(kelly_pct=-0.01), settings)
        assert not passed


class TestPositionSize:
    def test_within_limit_passes(self, risk_manager, settings):
        passed, _ = risk_manager._check_position_size(make_signal(kelly_pct=0.10), settings)
        assert passed

    def test_exceeds_limit_fails(self, risk_manager, settings):
        passed, _ = risk_manager._check_position_size(make_signal(kelly_pct=0.20), settings)
        assert not passed


class TestDailyLoss:
    def test_no_loss_passes(self, risk_manager, settings):
        passed, _ = risk_manager._check_daily_loss(make_signal(), settings)
        assert passed

    def test_loss_at_limit_fails(self, risk_manager, settings):
        risk_manager._daily_pnl = -51.0  # > 5% of $1000
        passed, _ = risk_manager._check_daily_loss(make_signal(), settings)
        assert not passed

    def test_loss_below_limit_passes(self, risk_manager, settings):
        risk_manager._daily_pnl = -49.0
        passed, _ = risk_manager._check_daily_loss(make_signal(), settings)
        assert passed


class TestWeeklyLoss:
    def test_loss_at_limit_fails(self, risk_manager, settings):
        risk_manager._weekly_pnl = -101.0  # > 10% of $1000
        passed, _ = risk_manager._check_weekly_loss(make_signal(), settings)
        assert not passed


class TestDrawdown:
    def test_no_peak_passes(self, risk_manager, settings):
        passed, _ = risk_manager._check_drawdown(make_signal(), settings)
        assert passed

    def test_within_drawdown_passes(self, risk_manager, settings):
        risk_manager._peak_value = 1000
        risk_manager._current_value = 900
        passed, _ = risk_manager._check_drawdown(make_signal(), settings)
        assert passed

    def test_exceeds_drawdown_fails(self, risk_manager, settings):
        risk_manager._peak_value = 1000
        risk_manager._current_value = 800  # 20% drawdown > 15%
        passed, _ = risk_manager._check_drawdown(make_signal(), settings)
        assert not passed


class TestPortfolioExposure:
    @patch("api.services.risk_manager.get_supabase")
    def test_within_limit_passes(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"size": 100, "avg_price": 0.30}
        ]
        sig = make_signal(kelly_pct=0.05)
        passed, _ = risk_manager._check_portfolio_exposure(sig, settings)
        assert passed

    @patch("api.services.risk_manager.get_supabase")
    def test_exceeds_limit_fails(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"size": 500, "avg_price": 0.80}  # $400 existing
        ]
        sig = make_signal(kelly_pct=0.15)  # +$150 new = $550 = 55% > 50%
        passed, _ = risk_manager._check_portfolio_exposure(sig, settings)
        assert not passed

    @patch("api.services.risk_manager.get_supabase")
    def test_db_error_fails_closed(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.side_effect = Exception("DB down")
        passed, reason = risk_manager._check_portfolio_exposure(make_signal(), settings)
        assert not passed
        assert "DB error" in reason


class TestSingleMarketExposure:
    @patch("api.services.risk_manager.get_supabase")
    def test_db_error_fails_closed(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.side_effect = Exception("DB down")
        passed, reason = risk_manager._check_single_market_exposure(make_signal(), settings)
        assert not passed
        assert "DB error" in reason


class TestCorrelatedExposure:
    @patch("api.services.risk_manager.get_supabase")
    def test_db_error_fails_closed(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.side_effect = Exception("DB down")
        passed, reason = risk_manager._check_correlated_exposure(make_signal(), settings)
        assert not passed
        assert "DB error" in reason


class TestDuplicate:
    @patch("api.services.risk_manager.get_supabase")
    def test_no_existing_passes(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        passed, _ = risk_manager._check_duplicate(make_signal(), settings)
        assert passed

    @patch("api.services.risk_manager.get_supabase")
    def test_db_error_fails_closed(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.side_effect = Exception("DB down")
        passed, reason = risk_manager._check_duplicate(make_signal(), settings)
        assert not passed
        assert "DB error" in reason


class TestSettlementDecay:
    @patch("api.services.risk_manager.get_supabase")
    def test_db_error_fails_closed(self, mock_sb, risk_manager, settings):
        mock_sb.return_value.table.side_effect = Exception("DB down")
        passed, reason = risk_manager._check_settlement_decay(make_signal(), settings)
        assert not passed
        assert "DB error" in reason


class TestSpreadCheck:
    def test_real_spread_within_tolerance_passes(self, risk_manager, settings):
        sig = make_signal(best_bid=0.295, best_ask=0.305)  # spread=0.01 < 0.02
        passed, _ = risk_manager._check_spread(sig, settings)
        assert passed

    def test_spread_exceeds_tolerance_fails(self, risk_manager, settings):
        sig = make_signal(best_bid=0.20, best_ask=0.40)  # spread=0.20
        passed, reason = risk_manager._check_spread(sig, settings)
        assert not passed
        assert "spread" in reason

    def test_no_order_book_data_fails(self, risk_manager, settings):
        sig = make_signal(best_bid=0.0, best_ask=1.0)
        passed, reason = risk_manager._check_spread(sig, settings)
        assert not passed  # fails either on sentinel or tolerance

    def test_default_signal_fails_spread(self, risk_manager, settings):
        sig = Signal(
            module_id="m", market_id="mk", bracket="100-119",
            side="BUY", edge=0.05, model_prob=0.35, market_price=0.30,
            kelly_pct=0.05,
        )
        passed, _ = risk_manager._check_spread(sig, settings)
        assert not passed


class TestLiquidityCheck:
    def test_sufficient_depth_passes(self, risk_manager, settings):
        sig = make_signal(kelly_pct=0.05, ask_depth_5=500.0)
        passed, _ = risk_manager._check_liquidity(sig, settings)
        assert passed

    def test_zero_depth_fails(self, risk_manager, settings):
        sig = make_signal(ask_depth_5=0.0)
        passed, reason = risk_manager._check_liquidity(sig, settings)
        assert not passed
        assert "no order book depth" in reason

    def test_order_exceeds_30pct_depth_fails(self, risk_manager, settings):
        sig = make_signal(kelly_pct=0.10, ask_depth_5=100.0)
        # target_size = 0.10 * 1000 = $100, max_fill = 100 * 0.30 = $30
        passed, reason = risk_manager._check_liquidity(sig, settings)
        assert not passed
        assert "30%" in reason

    def test_sell_uses_bid_depth(self, risk_manager, settings):
        sig = make_signal(side="SELL", bid_depth_5=0.0, ask_depth_5=1000.0)
        passed, _ = risk_manager._check_liquidity(sig, settings)
        assert not passed


class TestFullCheckPipeline:
    @patch("api.services.risk_manager.get_supabase")
    @patch("api.services.risk_manager.get_settings")
    def test_valid_signal_passes_all_checks(self, mock_gs, mock_sb, risk_manager):
        from tests.conftest import make_signal
        mock_gs.return_value = MagicMock(
            circuit_breaker_enabled=True,
            min_edge_threshold=0.02,
            max_single_market_exposure=0.15,
            bankroll=1000.0,
            daily_loss_limit=0.05,
            weekly_loss_limit=0.10,
            max_drawdown=0.15,
            max_portfolio_exposure=0.50,
            max_correlated_exposure=0.30,
            slippage_tolerance=0.02,
        )
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None
        mock_sb.return_value.table.return_value.select.return_value.execute.return_value.data = []
        mock_sb.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        sig = make_signal(
            edge=0.05, kelly_pct=0.05,
            best_bid=0.295, best_ask=0.305,  # spread=0.01 < tolerance 0.02
            ask_depth_5=500.0, bid_depth_5=500.0,
        )
        passed, reason = risk_manager.check(sig)
        assert passed, f"Expected pass but got: {reason}"
