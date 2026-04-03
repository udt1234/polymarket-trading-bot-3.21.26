import pytest
from api.modules.truth_social.projection import (
    ensemble_weights,
    bracket_probabilities,
    ensemble_projection,
    calibration_adjusted_weights,
    BRACKET_LABELS,
)


class TestEnsembleWeights:
    def test_early_phase(self):
        w = ensemble_weights(1.0, 7.0)
        assert w["historical"] > w["pace"]
        assert "hawkes" in w

    def test_late_phase(self):
        w = ensemble_weights(6.0, 7.0)
        assert w["pace"] > w["historical"]

    def test_mid_phase(self):
        w = ensemble_weights(3.5, 7.0)
        assert w["bayesian"] >= w["pace"]

    def test_weights_sum_to_one(self):
        for elapsed in [0.5, 1.75, 3.5, 5.25, 6.5]:
            w = ensemble_weights(elapsed, 7.0)
            assert sum(w.values()) == pytest.approx(1.0, abs=0.01)

    def test_surge_regime_increases_hawkes(self):
        normal = ensemble_weights(3.5, 7.0, regime_label="NORMAL")
        surge = ensemble_weights(3.5, 7.0, regime_label="SURGE")
        assert surge["hawkes"] > normal["hawkes"]

    def test_zero_total_days(self):
        w = ensemble_weights(0, 0)
        assert sum(w.values()) == pytest.approx(1.0, abs=0.01)

    def test_elapsed_exceeds_total_uses_late(self):
        w = ensemble_weights(10, 7.0)
        assert w["pace"] > 0.3  # late phase


class TestBracketProbabilities:
    def test_sums_to_one(self):
        probs = bracket_probabilities(100.0, 30.0)
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)

    def test_all_brackets_present(self):
        probs = bracket_probabilities(100.0, 30.0)
        assert set(probs.keys()) == set(BRACKET_LABELS)

    def test_peak_near_mean(self):
        probs = bracket_probabilities(110.0, 20.0)
        assert probs["100-119"] > probs["0-19"]
        assert probs["100-119"] > probs["200+"]

    def test_small_std_floored_at_10(self):
        probs = bracket_probabilities(100.0, 1.0)
        assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)

    def test_zero_mean(self):
        probs = bracket_probabilities(0.0, 30.0)
        assert probs["0-19"] == max(probs.values())  # first bracket has highest prob


class TestEnsembleProjection:
    def test_basic_projection_sums_to_one(self):
        outputs = {"pace": 100, "bayesian": 110, "dow": 105, "historical": 95}
        weights = {"pace": 0.25, "bayesian": 0.30, "dow": 0.20, "historical": 0.17, "hawkes": 0.08}
        result = ensemble_projection(outputs, weights, 25.0)
        assert sum(result.values()) == pytest.approx(1.0, abs=0.01)

    def test_signal_modifier_shifts_distribution(self):
        outputs = {"pace": 100}
        weights = {"pace": 1.0}
        normal = ensemble_projection(outputs, weights, 25.0, signal_modifier=1.0)
        boosted = ensemble_projection(outputs, weights, 25.0, signal_modifier=1.3)
        # Higher modifier shifts mass to higher brackets
        assert boosted.get("120-139", 0) > normal.get("120-139", 0)

    def test_empty_model_outputs(self):
        result = ensemble_projection({}, {}, 25.0)
        assert all(v == 0 for v in result.values())

    def test_model_not_in_weights_ignored(self):
        outputs = {"pace": 100, "unknown_model": 200}
        weights = {"pace": 1.0}
        result = ensemble_projection(outputs, weights, 25.0)
        assert sum(result.values()) == pytest.approx(1.0, abs=0.01)


class TestCalibrationAdjustedWeights:
    def test_no_scores_returns_unchanged(self):
        base = {"pace": 0.3, "bayesian": 0.7}
        assert calibration_adjusted_weights(base) == base
        assert calibration_adjusted_weights(base, {}) == base

    def test_better_score_increases_weight(self):
        base = {"pace": 0.5, "bayesian": 0.5}
        scores = {"pace": 0.1, "bayesian": 0.3}  # lower = better
        adjusted = calibration_adjusted_weights(base, scores)
        assert adjusted["pace"] > adjusted["bayesian"]

    def test_adjusted_weights_sum_to_one(self):
        base = {"pace": 0.25, "bayesian": 0.30, "dow": 0.20, "historical": 0.17, "hawkes": 0.08}
        scores = {"pace": 0.15, "bayesian": 0.10, "dow": 0.20}
        adjusted = calibration_adjusted_weights(base, scores)
        assert sum(adjusted.values()) == pytest.approx(1.0, abs=0.01)
