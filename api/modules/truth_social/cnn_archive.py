import httpx
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

CNN_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"


async def fetch_cnn_truth_archive() -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(CNN_ARCHIVE_URL, headers={"User-Agent": "Mozilla/5.0"})
            res.raise_for_status()
            posts = res.json()

        if not isinstance(posts, list):
            return {"count_today": 0, "count_week": 0, "latest_post": None, "available": False}

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())

        count_today = 0
        count_week = 0
        latest_ts = None

        for post in posts:
            created = post.get("created_at", post.get("date", ""))
            if not created:
                continue
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if dt >= today_start:
                count_today += 1
            if dt >= week_start:
                count_week += 1
            if latest_ts is None or dt > latest_ts:
                latest_ts = dt

        return {
            "count_today": count_today,
            "count_week": count_week,
            "total_archive": len(posts),
            "latest_post": latest_ts.isoformat() if latest_ts else None,
            "available": True,
        }

    except Exception as e:
        log.debug(f"CNN archive fetch failed: {e}")
        return {"count_today": 0, "count_week": 0, "latest_post": None, "available": False}


def compute_count_divergence(xtracker_count: int, cnn_count: int) -> dict:
    diff = cnn_count - xtracker_count
    if xtracker_count > 0:
        pct = diff / xtracker_count * 100
    else:
        pct = 0

    return {
        "xtracker": xtracker_count,
        "cnn": cnn_count,
        "diff": diff,
        "diff_pct": round(pct, 1),
        "has_edge": abs(diff) >= 2,
    }
