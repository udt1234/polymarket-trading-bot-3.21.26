import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from api.services.engine import TradingEngine


class TestEngineExecutorSelection:
    @patch("api.services.engine.ModuleRegistry")
    @patch("api.services.engine.get_settings")
    def test_paper_mode_uses_paper_executor(self, mock_gs, mock_reg):
        from api.services.executor import PaperExecutor
        mock_gs.return_value = MagicMock(paper_mode=True, shadow_mode=False, default_interval=300)
        engine = TradingEngine()
        engine.start(interval=9999)
        assert isinstance(engine.executor, PaperExecutor)
        assert not engine._multi_mode
        engine.stop()

    @patch("api.services.engine.get_multi_exec_profiles", create=True)
    @patch("api.services.engine.ModuleRegistry")
    @patch("api.services.engine.get_settings")
    def test_live_mode_single_profile(self, mock_gs, mock_reg, mock_profiles):
        from api.services.executor import LiveExecutor
        mock_gs.return_value = MagicMock(paper_mode=False, shadow_mode=False, default_interval=300)
        with patch("api.services.engine.get_multi_exec_profiles", return_value=[{"name": "solo"}]):
            engine = TradingEngine()
            engine.start()
            assert isinstance(engine.executor, LiveExecutor)
            engine.stop()


class TestEngineCycleGuards:
    def test_circuit_breaker_skips_cycle(self):
        engine = TradingEngine()
        engine._running = True
        engine.risk_manager.circuit_breaker_tripped = True
        engine._run_cycle()
        assert engine._cycle_count == 1  # incremented but short-circuited

    @patch("api.services.engine.get_supabase")
    def test_stale_data_skips_cycle(self, mock_sb):
        mock_sb.return_value.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        engine = TradingEngine()
        engine._running = True
        engine.risk_manager.circuit_breaker_tripped = False
        engine.executor = MagicMock()
        engine.registry = MagicMock()
        engine.registry.active_modules.return_value = []
        engine._run_cycle()
        assert engine._stale_data


class TestEngineResolutions:
    @patch("api.services.engine.check_resolutions")
    def test_passes_risk_manager(self, mock_cr):
        engine = TradingEngine()
        engine._run_resolutions()
        mock_cr.assert_called_once_with(risk_manager=engine.risk_manager)


class TestEngineSyncRiskState:
    @patch("api.services.engine.get_supabase")
    def test_updates_pnl(self, mock_sb):
        mock_sb.return_value.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"portfolio_value": 1100, "daily_return": 0.02, "total_pnl": 100},
            {"portfolio_value": 1080, "daily_return": 0.01, "total_pnl": 80},
        ]
        engine = TradingEngine()
        engine._sync_risk_state()
        assert engine.risk_manager._peak_value == 1100
        assert engine.risk_manager._current_value == 1100

    @patch("api.services.engine.get_supabase")
    def test_db_error_logs_warning(self, mock_sb):
        mock_sb.return_value.table.side_effect = Exception("DB down")
        engine = TradingEngine()
        engine._sync_risk_state()  # should not raise
