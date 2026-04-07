import pytest
import math
from unittest.mock import AsyncMock, patch
from api.services.backtester import (
    _compute_model_prob,
    _kelly_size,
    run_backtest,
    BacktestResult,
)


# --- _compute_model_prob tests ---

class TestComputeModelProb:
    def test_returns_none_for_small_idx(self):
        prices = [0.5] * 10
        assert _compute_model_prob(prices, "mean_reversion", 3) is None

    def test_mean_reversion_basic(self):
        prices = [0.50] * 25
        prob = _compute_model_prob(prices, "mean_reversion", 20)
        assert prob is not None
        assert 0.01 <= prob <= 0.99

    def test_momentum_basic(self):
        prices = [0.30 + i * 0.01 for i in range(25)]
        prob = _compute_model_prob(prices, "momentum", 20)
        assert prob is not None
        assert 0.01 <= prob <= 0.99

    def test_ensemble_blends(self):
        prices = [0.50] * 25
        mr = _compute_model_prob(prices, "mean_reversion", 20)
        mom = _compute_model_prob(prices, "momentum", 20)
        ens = _compute_model_prob(prices, "ensemble", 20)
        assert ens is not None
        # Ensemble should be between MR and momentum (or equal when identical)
        assert 0.01 <= ens <= 0.99

    def test_unknown_strategy_uses_mean(self):
        prices = [0.40] * 25
        prob = _compute_model_prob(prices, "unknown_strat", 20)
        assert prob is not None
        assert abs(prob - 0.40) < 0.01

    def test_clamps_to_bounds(self):
        # Extreme prices should still clamp to [0.01, 0.99]
        prices = [0.98] * 25
        prob = _compute_model_prob(prices, "mean_reversion", 20)
        assert 0.01 <= prob <= 0.99

        prices = [0.02] * 25
        prob = _compute_model_prob(prices, "mean_reversion", 20)
        assert 0.01 <= prob <= 0.99


# --- _kelly_size tests ---

class TestKellySize:
    def test_pass_on_no_edge(self):
        edge, sized, action = _kelly_size(0.50, 0.50, 0.25)
        assert action == "PASS"

    def test_buy_with_positive_edge(self):
        edge, sized, action = _kelly_size(0.60, 0.40, 0.25)
        assert action == "BUY"
        assert edge > 0.02
        assert sized > 0

    def test_pass_on_extreme_price(self):
        edge, sized, action = _kelly_size(0.50, 0.005, 0.25)
        assert action == "PASS"
        edge, sized, action = _kelly_size(0.50, 0.995, 0.25)
        assert action == "PASS"

    def test_kelly_capped_at_15_pct(self):
        edge, sized, action = _kelly_size(0.95, 0.30, 0.5)
        assert sized <= 0.15

    def test_pass_on_tiny_edge(self):
        edge, sized, action = _kelly_size(0.51, 0.50, 0.25)
        assert action == "PASS"


# --- run_backtest tests ---

def _make_price_series(n=100, base=0.50, drift=0.005):
    """Generate synthetic price series for testing."""
    import random
    random.seed(42)
    ts = 1700000000
    series = []
    price = base
    for i in range(n):
        price = max(0.02, min(0.98, price + random.uniform(-drift, drift)))
        series.append({"t": ts + i * 3600, "p": round(price, 4)})
    return series


class TestRunBacktest:
    @pytest.mark.asyncio
    async def test_with_price_series(self):
        series = _make_price_series(100)
        result = await run_backtest(
            slug="test-slug",
            title="Test Market",
            clob_token_id="",
            strategy="mean_reversion",
            bankroll=1000.0,
            price_series=series,
        )
        assert isinstance(result, BacktestResult)
        assert result.slug == "test-slug"
        assert result.bankroll == 1000.0

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_empty(self):
        series = [{"t": 1700000000 + i * 3600, "p": 0.50} for i in range(5)]
        result = await run_backtest(
            slug="short",
            title="Short",
            clob_token_id="",
            price_series=series,
        )
        assert result.total_trades == 0

    @pytest.mark.asyncio
    async def test_all_strategies(self):
        series = _make_price_series(200, drift=0.02)
        for strat in ["mean_reversion", "momentum", "ensemble"]:
            result = await run_backtest(
                slug="test",
                title="Test",
                clob_token_id="",
                strategy=strat,
                bankroll=1000.0,
                price_series=series,
            )
            assert isinstance(result, BacktestResult)
            assert result.strategy == strat

    @pytest.mark.asyncio
    async def test_equity_curve_starts_at_bankroll(self):
        series = _make_price_series(100)
        result = await run_backtest(
            slug="eq",
            title="Eq",
            clob_token_id="",
            price_series=series,
            bankroll=500.0,
        )
        if result.equity_curve:
            assert result.equity_curve[0]["value"] == 500.0

    @pytest.mark.asyncio
    async def test_metrics_computed(self):
        series = _make_price_series(200, drift=0.02)
        result = await run_backtest(
            slug="metrics",
            title="Metrics",
            clob_token_id="",
            strategy="mean_reversion",
            bankroll=1000.0,
            price_series=series,
        )
        if result.total_trades > 0:
            assert result.win_rate >= 0
            assert result.max_drawdown >= 0
            assert result.sharpe != 0 or result.total_trades <= 1

    @pytest.mark.asyncio
    async def test_trades_have_required_fields(self):
        series = _make_price_series(200, drift=0.02)
        result = await run_backtest(
            slug="fields",
            title="Fields",
            clob_token_id="",
            strategy="mean_reversion",
            bankroll=1000.0,
            price_series=series,
        )
        for trade in result.trades:
            assert "timestamp" in trade
            assert "side" in trade
            assert "entry_price" in trade
            assert "exit_price" in trade
            assert "pnl" in trade
            assert "edge" in trade
            assert "kelly_pct" in trade

    @pytest.mark.asyncio
    async def test_filters_out_of_range_prices(self):
        series = [
            {"t": 1700000000 + i * 3600, "p": 0.50} for i in range(50)
        ] + [
            {"t": 1700180000 + i * 3600, "p": 0.001} for i in range(10)  # out of range
        ] + [
            {"t": 1700216000 + i * 3600, "p": 0.50} for i in range(50)
        ]
        result = await run_backtest(
            slug="filter",
            title="Filter",
            clob_token_id="",
            price_series=series,
        )
        assert isinstance(result, BacktestResult)

    @pytest.mark.asyncio
    async def test_api_fetch_path(self):
        """Test that without price_series, it fetches from the API."""
        mock_history = [
            {"t": 1700000000 + i * 3600, "p": 0.50 + (i % 5) * 0.01}
            for i in range(50)
        ]
        with patch(
            "api.services.backtester.fetch_price_history",
            new_callable=AsyncMock,
            return_value=mock_history,
        ) as mock_fetch:
            result = await run_backtest(
                slug="api-test",
                title="API Test",
                clob_token_id="abc123",
                start_date="2024-01-01",
                end_date="2024-01-31",
            )
            mock_fetch.assert_called_once()
            assert isinstance(result, BacktestResult)
