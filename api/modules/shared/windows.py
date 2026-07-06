"""Auction window resolution (BUILD_SPEC C3).

Windows run noon ET to noon ET, exclusive at 12:00:00 PM ET. PARSE the
window from the market slug (e.g. elon-musk-of-tweets-may-23-may-25 =
May 23 noon ET to May 25 noon ET). Do NOT use Gamma startDate (listing
date, often ~2 days early) or trade-derived timestamps (~2x too wide).
xTracker tracking start/endDate are the official window (16:00Z = noon
EDT) and serve as the fallback when a slug doesn't parse.
"""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}

_SLUG_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)-(\d{1,2})-(january|february|march|april|may|june|"
    r"july|august|september|october|november|december)-(\d{1,2})$")


def _noon_et(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, 0, tzinfo=ET)


def parse_slug_window(slug: str, now: datetime | None = None) -> tuple[datetime, datetime] | None:
    """Parse '...-july-3-july-10' into (start, end) noon-ET datetimes.
    Years are inferred so the window lands nearest to `now` (slugs carry no
    year). Returns None when the slug has no date pair (e.g. monthly)."""
    m = _SLUG_RE.search(slug.strip().strip("/").split("/")[-1])
    if not m:
        return None
    now = now or datetime.now(ET)
    sm, sd, em, ed = _MONTHS[m.group(1)], int(m.group(2)), _MONTHS[m.group(3)], int(m.group(4))
    best = None
    for start_year in (now.year - 1, now.year, now.year + 1):
        try:
            start = _noon_et(start_year, sm, sd)
            end_year = start_year + 1 if (em, ed) < (sm, sd) else start_year
            end = _noon_et(end_year, em, ed)
        except ValueError:
            continue
        if end <= start:
            continue
        mid = start + (end - start) / 2
        dist = abs((mid - now).total_seconds())
        if best is None or dist < best[0]:
            best = (dist, start, end)
    return (best[1], best[2]) if best else None


def resolve_window(slug: str, tracking: dict | None = None) -> tuple[datetime, datetime] | None:
    """Best-available window: slug parse first, xTracker dates second."""
    win = parse_slug_window(slug) if slug else None
    if win:
        return win
    if tracking and tracking.get("startDate") and tracking.get("endDate"):
        s = datetime.fromisoformat(tracking["startDate"].replace("Z", "+00:00")).astimezone(ET)
        e = datetime.fromisoformat(tracking["endDate"].replace("Z", "+00:00")).astimezone(ET)
        # xTracker ends at :59:59 - normalize to the exclusive noon boundary.
        if e.minute == 59:
            e = (e + timedelta(seconds=1)).replace(microsecond=0)
        return s, e
    return None


def duration_days(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 86400.0


def duration_type(start: datetime, end: datetime) -> str:
    d = duration_days(start, end)
    if abs(d - 2) <= 0.2:
        return "2-day"
    if abs(d - 7) <= 0.3:
        return "7-day"
    if 27 <= d <= 32:
        return "monthly"
    return "unknown"


def elapsed_fraction(start: datetime, end: datetime, now: datetime | None = None) -> float:
    """Elapsed fraction of the window, floored 0.001 and capped 0.99 (D2)."""
    now = now or datetime.now(ET)
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.99
    frac = (now.astimezone(ET) - start).total_seconds() / total
    return min(max(frac, 0.001), 0.99)
