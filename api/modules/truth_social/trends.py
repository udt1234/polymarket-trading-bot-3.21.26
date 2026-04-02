import logging

log = logging.getLogger(__name__)


async def fetch_google_trends(keyword: str = "Trump Truth Social", timeframe: str = "now 7-d") -> dict:
    """
    Fetch Google Trends interest-over-time for a keyword.
    Returns trend direction and current interest level.
    Requires: pip install pytrends
    """
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=300, timeout=(10, 25))
        pytrends.build_payload([keyword], timeframe=timeframe, geo="US")
        df = pytrends.interest_over_time()

        if df.empty:
            return {"interest": 0, "trend": "flat", "change_pct": 0, "available": False}

        values = df[keyword].tolist()
        current = values[-1] if values else 0
        avg_recent = sum(values[-6:]) / max(len(values[-6:]), 1)
        avg_prior = sum(values[:-6]) / max(len(values[:-6]), 1) if len(values) > 6 else avg_recent

        if avg_prior > 0:
            change_pct = (avg_recent - avg_prior) / avg_prior * 100
        else:
            change_pct = 0

        if change_pct > 20:
            trend = "surging"
        elif change_pct > 5:
            trend = "rising"
        elif change_pct < -20:
            trend = "dropping"
        elif change_pct < -5:
            trend = "declining"
        else:
            trend = "flat"

        return {
            "interest": current,
            "trend": trend,
            "change_pct": round(change_pct, 1),
            "avg_recent": round(avg_recent, 1),
            "avg_prior": round(avg_prior, 1),
            "available": True,
        }

    except ImportError:
        log.debug("pytrends not installed — skipping Google Trends")
        return {"interest": 0, "trend": "flat", "change_pct": 0, "available": False}
    except Exception as e:
        log.warning(f"Google Trends fetch failed: {e}")
        return {"interest": 0, "trend": "flat", "change_pct": 0, "available": False}


def compute_trends_modifier(trends_data: dict) -> float:
    if not trends_data.get("available"):
        return 1.0

    trend = trends_data.get("trend", "flat")
    change = trends_data.get("change_pct", 0)

    if trend == "surging":
        return 1.15
    elif trend == "rising":
        return 1.08
    elif trend == "dropping":
        return 0.85
    elif trend == "declining":
        return 0.92
    return 1.0
