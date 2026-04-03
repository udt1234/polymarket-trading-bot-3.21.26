import pytest
from api.modules.truth_social.pacing import (
    regular_pace,
    bayesian_pace,
    dow_hourly_bayesian_pace,
)


class TestRegularPace:
    def test_basic_extrapolation(self):
        assert regular_pace(50, 3.5, 7.0) == pytest.approx(100.0)

    def test_zero_elapsed_returns_zero(self):
        assert regular_pace(50, 0, 7.0) == 0

    def test_negative_elapsed_returns_zero(self):
        assert regular_pace(50, -1, 7.0) == 0

    def test_zero_posts(self):
        assert regular_pace(0, 3.5, 7.0) == 0.0

    def test_elapsed_exceeds_total(self):
        result = regular_pace(100, 10, 7.0)
        assert result < 100  # projection < actual


class TestBayesianPace:
    def test_early_period_trusts_history(self):
        result = bayesian_pace(10, 0.5, 6.5, 100.0, 7.0)
        assert result > 50  # closer to hist_mean than observed pace

    def test_late_period_trusts_observed(self):
        result = bayesian_pace(80, 6.0, 1.0, 100.0, 7.0)
        observed = (80 / 6.0) * 7.0
        assert abs(result - observed) < abs(result - 100.0)

    def test_zero_elapsed_returns_hist_mean(self):
        result = bayesian_pace(0, 0, 7.0, 100.0, 7.0)
        assert result == 100.0

    def test_zero_remaining_uses_floor(self):
        result = bayesian_pace(100, 7.0, 0, 100.0, 7.0)
        assert result > 0  # prior_weight floors at 0.5

    def test_negative_remaining_uses_floor(self):
        result = bayesian_pace(100, 8.0, -1.0, 100.0, 7.0)
        assert result > 0


class TestDowHourlyBayesianPace:
    def test_basic_projection(self):
        remaining = [{"hour": 10, "dow": 0}, {"hour": 11, "dow": 0}]
        hourly_avgs = {10: 2.0, 11: 3.0}
        dow_weights = {0: 1.2}
        result = dow_hourly_bayesian_pace(50, remaining, hourly_avgs, dow_weights, 100.0, 3.5, 3.5)
        assert result > 50

    def test_empty_remaining_hours(self):
        result = dow_hourly_bayesian_pace(80, [], {}, {}, 100.0, 7.0, 0)
        assert result > 0  # Bayesian blend of running_total and hist_mean

    def test_missing_hour_key_defaults_to_zero(self):
        remaining = [{"hour": 99, "dow": 0}]
        hourly_avgs = {10: 5.0}  # hour 99 not present
        result = dow_hourly_bayesian_pace(50, remaining, hourly_avgs, {0: 1.0}, 100.0, 3.5, 3.5)
        # hour 99 contributes 0, so projected_remaining ≈ 0
        assert result < 100

    def test_missing_dow_key_defaults_to_one(self):
        remaining = [{"hour": 10, "dow": 99}]  # dow 99 not in weights
        hourly_avgs = {10: 5.0}
        dow_weights = {0: 2.0}  # dow 99 missing
        result = dow_hourly_bayesian_pace(50, remaining, hourly_avgs, dow_weights, 100.0, 3.5, 3.5)
        assert result > 50  # hour 10 contributes 5.0 * 1.0 = 5.0

    def test_dow_weight_zero_nullifies_hour(self):
        remaining = [{"hour": 10, "dow": 0}]
        hourly_avgs = {10: 100.0}
        dow_weights = {0: 0.0}
        result = dow_hourly_bayesian_pace(0, remaining, hourly_avgs, dow_weights, 50.0, 0, 7.0)
        # projected_remaining = 100 * 0 = 0, raw_projection = 0
        assert result == pytest.approx(50.0, abs=1)  # equals hist_mean
