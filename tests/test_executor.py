import pytest
from unittest.mock import patch, MagicMock
from api.services.executor import PaperExecutor, LiveExecutor
from tests.conftest import make_signal


class TestPaperExecutor:
    @patch("api.services.executor.open_position")
    @patch("api.services.executor.get_supabase")
    def test_execute_buy_returns_order(self, mock_sb, mock_op):
        mock_sb.return_value = MagicMock()
        executor = PaperExecutor()
        sig = make_signal(kelly_pct=0.10, market_price=0.30)
        result = executor.execute(sig)
        assert result["status"] == "filled"
        assert result["executor"] == "paper"
        assert result["price"] == 0.30
        assert result["side"] == "BUY"

    @patch("api.services.executor.open_position")
    @patch("api.services.executor.get_supabase")
    def test_buy_decrements_balance(self, mock_sb, mock_op):
        mock_sb.return_value = MagicMock()
        executor = PaperExecutor()
        initial = executor.balance
        sig = make_signal(kelly_pct=0.10, market_price=0.30)
        executor.execute(sig)
        assert executor.balance < initial

    @patch("api.services.executor.open_position")
    @patch("api.services.executor.get_supabase")
    def test_sell_increments_balance(self, mock_sb, mock_op):
        mock_sb.return_value = MagicMock()
        executor = PaperExecutor()
        initial = executor.balance
        sig = make_signal(side="SELL", kelly_pct=0.10, market_price=0.30)
        executor.execute(sig)
        assert executor.balance > initial

    @patch("api.services.executor.open_position")
    @patch("api.services.executor.get_supabase")
    def test_writes_to_orders_and_trades(self, mock_sb, mock_op):
        sb = MagicMock()
        mock_sb.return_value = sb
        executor = PaperExecutor()
        executor.execute(make_signal())
        tables_called = [call.args[0] for call in sb.table.call_args_list]
        assert "orders" in tables_called
        assert "trades" in tables_called


class TestLiveExecutor:
    @patch("api.services.executor.open_position")
    @patch("api.services.executor.get_supabase")
    def test_gtc_order_type(self, mock_sb, mock_op):
        mock_sb.return_value = MagicMock()
        executor = LiveExecutor(profile={
            "name": "test",
            "polymarket_api_key": "key",
            "polymarket_secret": "secret",
            "polymarket_passphrase": "pass",
            "polymarket_private_key": "0xabc",
        })

        mock_client = MagicMock()
        executor._client = mock_client

        sig = make_signal()
        executor.execute(sig)

        order_dict = mock_client.create_and_post_order.call_args[0][0]
        assert order_dict["type"] == "GTC"
        assert "price" in order_dict
        assert order_dict["price"] == sig.market_price

    @patch("api.services.executor.get_supabase")
    def test_missing_credentials_raises(self, mock_sb):
        mock_sb.return_value = MagicMock()
        executor = LiveExecutor(profile={"name": "empty"})
        with pytest.raises(ValueError, match="Missing Polymarket credentials"):
            executor._get_client()

    @patch("api.services.executor.get_supabase")
    def test_clob_failure_marks_rejected(self, mock_sb):
        sb = MagicMock()
        mock_sb.return_value = sb
        executor = LiveExecutor(profile={
            "name": "test",
            "polymarket_api_key": "k",
            "polymarket_secret": "s",
            "polymarket_passphrase": "p",
            "polymarket_private_key": "0x1",
        })
        mock_client = MagicMock()
        mock_client.create_and_post_order.side_effect = Exception("CLOB error")
        executor._client = mock_client

        with pytest.raises(Exception):
            executor.execute(make_signal())

        update_calls = sb.table.return_value.update.call_args_list
        assert any(
            call.args[0].get("status") == "rejected"
            for call in update_calls
        )
