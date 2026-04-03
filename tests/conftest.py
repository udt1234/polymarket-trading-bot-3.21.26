import pytest
from unittest.mock import MagicMock, patch
from api.services.risk_manager import Signal
from api.config import Settings


def make_signal(**overrides):
    defaults = {
        "module_id": "test-module",
        "market_id": "test-market",
        "bracket": "100-119",
        "side": "BUY",
        "edge": 0.05,
        "model_prob": 0.35,
        "market_price": 0.30,
        "kelly_pct": 0.05,
        "confidence": 0.8,
        "best_bid": 0.28,
        "best_ask": 0.32,
        "bid_depth_5": 500.0,
        "ask_depth_5": 500.0,
    }
    defaults.update(overrides)
    return Signal(**defaults)


@pytest.fixture
def signal():
    return make_signal()


@pytest.fixture
def settings():
    return Settings(
        paper_mode=True,
        bankroll=1000.0,
        max_portfolio_exposure=0.50,
        max_single_market_exposure=0.15,
        max_correlated_exposure=0.30,
        daily_loss_limit=0.05,
        weekly_loss_limit=0.10,
        max_drawdown=0.15,
        min_edge_threshold=0.02,
        slippage_tolerance=0.02,
        kelly_fraction=0.25,
        circuit_breaker_enabled=True,
        circuit_breaker_max_consecutive_losses=5,
        circuit_breaker_cooldown_minutes=30,
    )


@pytest.fixture
def mock_supabase():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None
    sb.table.return_value.select.return_value.not_.return_value.in_.return_value.execute.return_value.data = []
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return sb


@pytest.fixture
def risk_manager():
    from api.services.risk_manager import RiskManager
    return RiskManager()
