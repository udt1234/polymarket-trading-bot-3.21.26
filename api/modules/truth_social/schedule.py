import httpx
import logging
from datetime import datetime, timezone
from xml.etree import ElementTree

log = logging.getLogger(__name__)

SCHEDULE_IMPACT = {
    "rally": 1.25, "speech": 1.15, "press_conference": 1.20,
    "court": 1.30, "foreign_travel": 0.70, "domestic_travel": 0.85,
    "golf": 1.05, "camp_david": 0.80, "vacation": 0.75,
    "debate": 1.20, "state_dinner": 0.90, "bilateral_meeting": 0.90,
    "fundraiser": 1.10, "signing": 1.10, "executive_order": 1.15,
}

# Factbase is the best free structured source (updates daily from WH press office)
FACTBASE_JSON = "https://media-cdn.factba.se/rss/json/trump/calendar-full.json"
FACTBASE_CSV = "https://media-cdn.factba.se/rss/csv/trump/calendar.csv"


async def fetch_presidential_schedule() -> list[dict]:
    events = []

    # Source 1: Factbase JSON (best — structured, daily, from WH press office)
    events.extend(await _fetch_factbase_json())

    # Source 2: News fallback (always available)
    if not events:
        events.extend(await _fetch_news_schedule())

    # Deduplicate by event_type per date
    seen = set()
    unique = []
    for e in events:
        key = f"{str(e.get('date', ''))[:10]}_{e.get('event_type', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return unique


async def _fetch_factbase_json() -> list[dict]:
    events = []
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            res = await client.get(FACTBASE_JSON, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                data = res.json()
                items = data if isinstance(data, list) else data.get("events", data.get("data", []))
                for item in items[-60:]:
                    # Factbase JSON has: date, title/details, location, type
                    details = item.get("title", item.get("details", item.get("description", "")))
                    date = item.get("date", item.get("start", ""))
                    location = item.get("location", "")

                    event_type = _classify_event(f"{details} {location}")
                    if event_type:
                        events.append({
                            "date": date,
                            "event_type": event_type,
                            "description": details[:100],
                            "location": location[:50] if location else "",
                            "impact": SCHEDULE_IMPACT.get(event_type, 1.0),
                            "source": "factbase",
                        })
                log.debug(f"Factbase: {len(events)} schedule events from {len(items)} items")
    except Exception as e:
        log.debug(f"Factbase JSON fetch failed: {e}")

    # Fallback: try the older factba.se calendar API
    if not events:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    "https://factba.se/json/json-calendar.php",
                    params={"type": "calendar"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if res.status_code == 200:
                    for item in res.json()[:30]:
                        event_type = _classify_event(item.get("details", ""))
                        if event_type:
                            events.append({
                                "date": item.get("date", ""),
                                "event_type": event_type,
                                "description": item.get("details", "")[:100],
                                "impact": SCHEDULE_IMPACT.get(event_type, 1.0),
                                "source": "factbase_legacy",
                            })
        except Exception as e:
            log.debug(f"Factbase legacy fetch failed: {e}")

    return events


async def _fetch_news_schedule() -> list[dict]:
    events = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(
                "https://news.google.com/rss/search",
                params={
                    "q": "Trump schedule OR Trump rally OR Trump travel OR Trump court OR Trump executive order",
                    "hl": "en-US", "gl": "US", "ceid": "US:en",
                },
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if res.status_code == 200:
                root = ElementTree.fromstring(res.content)
                for item in root.findall(".//item")[:20]:
                    title = item.findtext("title", "")
                    event_type = _classify_event(title)
                    if event_type:
                        events.append({
                            "date": item.findtext("pubDate", ""),
                            "event_type": event_type,
                            "description": title[:100],
                            "impact": SCHEDULE_IMPACT.get(event_type, 1.0),
                            "source": "news",
                        })
    except Exception as e:
        log.debug(f"News schedule fallback failed: {e}")
    return events


def _classify_event(text: str) -> str | None:
    text = text.lower()
    if any(w in text for w in ["rally", "campaign event", "maga rally", "campaign rally"]):
        return "rally"
    if any(w in text for w in ["court", "trial", "hearing", "arraign", "sentenc"]):
        return "court"
    if any(w in text for w in ["overseas", "abroad", "foreign trip", "state visit", "g7", "g20", "nato"]):
        return "foreign_travel"
    if any(w in text for w in ["bilateral meeting", "bilateral"]):
        return "bilateral_meeting"
    if any(w in text for w in ["travel", "depart", "arrive", "air force one", "marine one"]):
        return "domestic_travel"
    if any(w in text for w in ["speech", "address", "remarks", "state of the union"]):
        return "speech"
    if any(w in text for w in ["press conference", "press briefing", "presser"]):
        return "press_conference"
    if any(w in text for w in ["executive order", "presidential memorandum", "signing ceremony"]):
        return "executive_order"
    if any(w in text for w in ["fundraiser", "fundraising", "donor event"]):
        return "fundraiser"
    if "golf" in text:
        return "golf"
    if "camp david" in text:
        return "camp_david"
    if any(w in text for w in ["vacation", "mar-a-lago holiday", "christmas break"]):
        return "vacation"
    if "debate" in text:
        return "debate"
    if "state dinner" in text:
        return "state_dinner"
    return None


def compute_schedule_modifier(events: list[dict], today: str | None = None) -> float:
    if not events:
        return 1.0

    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_events = [e for e in events if today in str(e.get("date", ""))]

    if not today_events:
        return 1.0

    modifiers = [e["impact"] for e in today_events]
    if any(m > 1.0 for m in modifiers):
        return max(modifiers)
    return min(modifiers)
