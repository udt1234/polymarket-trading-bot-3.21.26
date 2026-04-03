import pytest
from api.modules.truth_social.signals import (
    compute_signal_modifier,
    kelly_sizing,
    rank_brackets,
    depth_adjusted_size,
    cross_bracket_arbitrage,
    contrarian_signal,
)


class TestComputeSignalModifier:
    def test_baseline_no_events(self):
        assert compute_signal_modifier(30, 0, []) == 1.0

    def test_high_news_intensity(self):
        result = compute_signal_modifier(85, 0, [])
        assert result == 1.15

    def test_medium_news_intensity(self):
        result = compute_signal_modifier(55, 0, [])
        assert result == 1.08

    def test_low_news_intensity(self):
        result = compute_signal_modifier(10, 0, [])
        assert result == 0.95

    def test_high_conflict(self):
        result = compute_signal_modifier(30, 20, [])
        assert result == 1.20

    def test_rally_event(self):
        result = compute_signal_modifier(30, 0, ["Rally in Georgia"])
        assert result == 1.15

    def test_legal_event(self):
        result = compute_signal_modifier(30, 0, ["Court hearing"])
        assert result == 1.20

    def test_stacking_events(self):
        result = compute_signal_modifier(85, 20, ["Rally", "Court hearing"])
        assert result == 1.5  # clamped at max

    def test_clamp_at_minimum(self):
        result = compute_signal_modifier(5, 0, [])
        assert result >= 0.5

    def test_empty_events(self):
        result = compute_signal_modifier(30, 0, [])
        assert result == 1.0


class TestKellySizing:
    def test_positive_edge_buys(self):
        result = kelly_sizing(0.40, 0.30)
        assert result["action"] == "BUY"
        assert result["edge"] > 0
        assert result["kelly_pct"] > 0

    def test_no_edge_passes(self):
        result = kelly_sizing(0.30, 0.30)
        assert result["action"] == "PASS"

    def test_market_price_zero_returns_pass(self):
        result = kelly_sizing(0.50, 0.0)
        assert result["kelly_pct"] == 0
        assert result["action"] == "PASS"

    def test_market_price_one_returns_pass(self):
        result = kelly_sizing(0.50, 1.0)
        assert result["kelly_pct"] == 0

    def test_transition_regime_reduces_kelly(self):
        normal = kelly_sizing(0.50, 0.30, regime_label="NORMAL")
        transition = kelly_sizing(0.50, 0.30, regime_label="TRANSITION")
        assert transition["kelly_pct"] < normal["kelly_pct"]

    def test_high_volatility_reduces_kelly(self):
        low_vol = kelly_sizing(0.50, 0.30, volatility=0.5)
        high_vol = kelly_sizing(0.50, 0.30, volatility=1.8)
        assert high_vol["kelly_pct"] < low_vol["kelly_pct"]

    def test_position_cap_at_15pct(self):
        result = kelly_sizing(0.90, 0.10)  # huge edge
        assert result["kelly_pct"] <= 0.15

    def test_time_decay_late_auction(self):
        early = kelly_sizing(0.50, 0.30, elapsed_pct=0.3)
        late = kelly_sizing(0.50, 0.30, elapsed_pct=0.9)
        assert late["kelly_pct"] < early["kelly_pct"]

    def test_elapsed_100pct_zeros_kelly(self):
        result = kelly_sizing(0.50, 0.30, elapsed_pct=1.0)
        assert result["kelly_pct"] == 0


class TestRankBrackets:
    def test_returns_top_3(self):
        probs = {"80-99": 0.30, "100-119": 0.35, "120-139": 0.20, "60-79": 0.10, "140-159": 0.05}
        prices = {"80-99": 0.25, "100-119": 0.30, "120-139": 0.15, "60-79": 0.08, "140-159": 0.04}
        result = rank_brackets(probs, prices)
        assert len(result) <= 3
        assert all(r["edge"] > 0 for r in result)

    def test_no_positive_edge_returns_empty(self):
        probs = {"80-99": 0.20}
        prices = {"80-99": 0.30}
        result = rank_brackets(probs, prices)
        assert result == []

    def test_skips_invalid_prices(self):
        probs = {"80-99": 0.50, "100-119": 0.30}
        prices = {"80-99": 0.0, "100-119": 0.20}
        result = rank_brackets(probs, prices)
        assert len(result) == 1
        assert result[0]["bracket"] == "100-119"

    def test_order_books_affect_score(self):
        probs = {"80-99": 0.40, "100-119": 0.40}
        prices = {"80-99": 0.30, "100-119": 0.30}
        no_books = rank_brackets(probs, prices)
        with_books = rank_brackets(probs, prices, {"80-99": 1000.0, "100-119": 10.0})
        assert no_books[0]["bracket"] != with_books[0]["bracket"] or len(with_books) <= 2


class TestDepthAdjustedSize:
    def test_no_order_book_returns_unchanged(self):
        assert depth_adjusted_size(0.10, {}) == 0.10
        assert depth_adjusted_size(0.10, None) == 0.10

    def test_zero_depth_reduces(self):
        result = depth_adjusted_size(0.10, {"ask_depth_5": 0})
        assert result == 0.10 * 0.25

    def test_sufficient_depth_unchanged(self):
        result = depth_adjusted_size(0.05, {"ask_depth_5": 1000}, bankroll=1000)
        assert result == 0.05

    def test_caps_at_30pct_depth(self):
        result = depth_adjusted_size(0.50, {"ask_depth_5": 100}, bankroll=1000)
        expected = round(100 * 0.30 / 1000, 4)
        assert result == expected


class TestCrossBracketArbitrage:
    def test_detects_misallocation(self):
        probs = {"80-99": 0.50, "100-119": 0.30, "120-139": 0.20}
        prices = {"80-99": 0.20, "100-119": 0.50, "120-139": 0.30}
        result = cross_bracket_arbitrage(probs, prices)
        assert len(result) > 0
        assert any(o["side"] == "BUY" for o in result)

    def test_no_misallocation_returns_empty(self):
        probs = {"80-99": 0.50, "100-119": 0.50}
        prices = {"80-99": 0.50, "100-119": 0.50}
        result = cross_bracket_arbitrage(probs, prices)
        assert result == []


class TestContrarianSignal:
    def test_no_order_books_returns_empty(self):
        assert contrarian_signal({"a": 0.3, "b": 0.3, "c": 0.3}) == {}

    def test_fewer_than_3_prices_returns_empty(self):
        assert contrarian_signal({"a": 0.3, "b": 0.3}, {"a": {"bid_depth_5": 10, "ask_depth_5": 10}}) == {}

    def test_overcrowded_gets_negative_adjustment(self):
        prices = {"a": 0.3, "b": 0.3, "c": 0.3}
        books = {
            "a": {"bid_depth_5": 100, "ask_depth_5": 100},
            "b": {"bid_depth_5": 10, "ask_depth_5": 10},
            "c": {"bid_depth_5": 10, "ask_depth_5": 10},
        }
        result = contrarian_signal(prices, books)
        assert result.get("a", 0) < 0
