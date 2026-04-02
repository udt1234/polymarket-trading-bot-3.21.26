import httpx
import re
import logging
from xml.etree import ElementTree

log = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

CONFLICT_KEYWORDS = {
    3: ["war", "strike", "bombing", "invasion", "attack", "assassination"],
    2: ["tariff", "sanction", "embargo", "trade war", "retaliation"],
    1: ["tension", "threat", "warning", "escalation", "dispute", "clash"],
}

SCHEDULE_PATTERNS = {
    "rally": r"\brall(?:y|ies)\b",
    "speech": r"\bspeech\b|\baddress\b|\bremarks\b",
    "legal": r"\bcourt\b|\btrial\b|\bhearing\b|\bsentencing\b",
    "indictment": r"\bindict\b|\bcharg(?:e|ed|es)\b|\barraign\b",
    "golf": r"\bgolf\b",
    "debate": r"\bdebate\b",
    "summit": r"\bsummit\b|\bmeeting\b.*\bleader\b",
}


SUPPLEMENTAL_QUERIES = {
    "Trump": ["Trump Truth Social", "Trump rally speech", "Trump court trial"],
    "Elon Musk": ["Elon Musk Twitter", "Elon Musk SpaceX Tesla", "Elon Musk DOGE"],
}


async def fetch_google_news(query: str = "Trump", max_results: int = 50) -> dict:
    queries = [query] + SUPPLEMENTAL_QUERIES.get(query, [])
    all_headlines = []
    seen_titles = set()

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for q in queries:
            try:
                res = await client.get(
                    GOOGLE_NEWS_RSS,
                    params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                res.raise_for_status()
                root = ElementTree.fromstring(res.content)
                for item in root.findall(".//item")[:max_results]:
                    title = item.findtext("title", "")
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_headlines.append({"title": title, "pub_date": item.findtext("pubDate", "")})
            except Exception as e:
                log.debug(f"News fetch for '{q}' failed: {e}")
                continue

    if not all_headlines:
        return {
            "headline_count": 0, "headlines": [],
            "conflict_score": 0, "schedule_events": [],
            "query": query, "status": "error",
        }

    headline_count = len(all_headlines)
    conflict_score = _compute_conflict_score(all_headlines)
    schedule_events = _detect_schedule_events(all_headlines)

    return {
        "headline_count": headline_count,
        "headlines": [h["title"] for h in all_headlines],
        "conflict_score": conflict_score,
        "schedule_events": schedule_events,
        "query": query,
        "status": "ok",
    }


def _compute_conflict_score(headlines: list[dict]) -> int:
    score = 0
    all_text = " ".join(h["title"].lower() for h in headlines)

    for points, keywords in CONFLICT_KEYWORDS.items():
        for kw in keywords:
            count = all_text.count(kw)
            score += count * points

    return score


def _detect_schedule_events(headlines: list[dict]) -> list[str]:
    events = []
    all_text = " ".join(h["title"].lower() for h in headlines)

    for event_type, pattern in SCHEDULE_PATTERNS.items():
        if re.search(pattern, all_text, re.IGNORECASE):
            events.append(event_type)

    return events
