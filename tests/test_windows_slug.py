"""Regression: Polymarket started appending a year to tweet slugs, and the
anchored slug regex stopped matching. Every window parsed as None, so S2 and
Copytrader found no live auction and went silent for 10+ days (2026-09-01)."""
from api.modules.shared import windows


def _parse(slug):
    return windows.parse_slug_window(slug)


class TestSlugWindow:
    def test_year_suffix_parses(self):
        win = _parse("elon-musk-of-tweets-august-31-september-2-2026")
        assert win is not None
        assert (win[0].year, win[0].month, win[0].day) == (2026, 8, 31)
        assert (win[1].year, win[1].month, win[1].day) == (2026, 9, 2)
        assert win[0].hour == 12 and win[1].hour == 12

    def test_year_suffix_duration_type(self):
        assert windows.duration_type(*_parse(
            "elon-musk-of-tweets-august-31-september-2-2026")) == "2-day"
        assert windows.duration_type(*_parse(
            "elon-musk-of-tweets-september-1-september-8-2026")) == "7-day"

    def test_legacy_slug_without_year_still_parses(self):
        win = _parse("elon-musk-of-tweets-may-23-may-25")
        assert win is not None
        assert (win[0].month, win[0].day, win[1].month, win[1].day) == (5, 23, 5, 25)

    def test_year_in_slug_wins_over_nearest_to_now(self):
        win = _parse("elon-musk-of-tweets-january-2-january-4-2024")
        assert win is not None and win[0].year == 2024

    def test_new_year_straddle_uses_end_year(self):
        win = _parse("elon-musk-of-tweets-december-30-january-2-2027")
        assert win is not None
        assert win[0].year == 2026 and win[1].year == 2027

    def test_monthly_slug_has_no_window(self):
        assert _parse("elon-musk-of-tweets-october-2026") is None
