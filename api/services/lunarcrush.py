import logging
import httpx
from api.config import get_settings

log = logging.getLogger(__name__)

LUNARCRUSH_BASE = "https://lunarcrush.com/api4/public"


async def fetch_social_sentiment(topic: str) -> dict:
    settings = get_settings()
    if not settings.lunarcrush_api_key:
        log.warning("No LunarCrush API key configured, returning neutral data")
        return _neutral_sentiment()

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{LUNARCRUSH_BASE}/topic/{topic}/v1",
                headers={"Authorization": f"Bearer {settings.lunarcrush_api_key}"},
            )
            res.raise_for_status()
            raw = res.json()

        data = raw.get("data", raw)
        return {
            "galaxy_score": data.get("galaxy_score", 0),
            "alt_rank": data.get("alt_rank", 0),
            "social_volume": data.get("num_posts", 0),
            "social_engagement": data.get("social_score", 0),
            "sentiment_score": data.get("sentiment", 50),
            "bullish_pct": data.get("bullish", 50),
            "bearish_pct": data.get("bearish", 50),
            "news_count": data.get("news", 0),
        }
    except Exception as e:
        log.warning(f"LunarCrush API error: {e}")
        return _neutral_sentiment()


async def fetch_creator_metrics(screen_name: str, network: str = "x") -> dict:
    settings = get_settings()
    if not settings.lunarcrush_api_key:
        return {"interactions": 0, "posts_active": 0, "followers": 0, "velocity": 0.0}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{LUNARCRUSH_BASE}/creator/{network}/{screen_name}/v1",
                headers={"Authorization": f"Bearer {settings.lunarcrush_api_key}"},
            )
            res.raise_for_status()
            data = res.json().get("data", res.json())

        interactions = data.get("interactions", 0)
        posts = data.get("posts_active", 0)
        velocity = interactions / max(posts, 1)

        return {
            "interactions": interactions,
            "posts_active": posts,
            "followers": data.get("followers", 0),
            "velocity": round(velocity, 2),
            "social_dominance": data.get("social_dominance", 0),
            "influencer_rank": data.get("influencer_rank", 0),
        }
    except Exception as e:
        log.warning(f"LunarCrush creator fetch error: {e}")
        return {"interactions": 0, "posts_active": 0, "followers": 0, "velocity": 0.0}


def compute_lunarcrush_modifier(sentiment_data: dict, creator_data: dict | None = None) -> float:
    if not sentiment_data or all(v == 0 for v in sentiment_data.values()):
        return 1.0

    mod = 1.0
    social_volume = sentiment_data.get("social_volume", 0)
    sentiment = sentiment_data.get("sentiment_score", 50)
    bullish = sentiment_data.get("bullish_pct", 50)
    galaxy = sentiment_data.get("galaxy_score", 0)

    if social_volume > 5000:
        mod += 0.10
    elif social_volume > 1000:
        mod += 0.05
    elif social_volume < 100:
        mod -= 0.10

    if sentiment > 75:
        mod += 0.10
    elif sentiment > 60:
        mod += 0.05
    elif sentiment < 30:
        mod -= 0.10

    if bullish > 70:
        mod += 0.08
    elif bullish < 30:
        mod -= 0.08

    if galaxy > 80:
        mod += 0.07

    if social_volume > 10000 and sentiment > 70:
        mod += 0.10

    # Engagement velocity: high velocity = likely to keep posting (behavioral reinforcement)
    if creator_data:
        velocity = creator_data.get("velocity", 0)
        dominance = creator_data.get("social_dominance", 0)
        if velocity > 500:
            mod += 0.12
        elif velocity > 200:
            mod += 0.06
        if dominance > 5:
            mod += 0.08
        elif dominance > 2:
            mod += 0.04

    return max(0.5, min(mod, 1.5))


def _neutral_sentiment() -> dict:
    return {
        "galaxy_score": 0,
        "alt_rank": 0,
        "social_volume": 0,
        "social_engagement": 0,
        "sentiment_score": 50,
        "bullish_pct": 50,
        "bearish_pct": 50,
        "news_count": 0,
    }
