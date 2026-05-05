import logging
import httpx
from api.config import get_settings

log = logging.getLogger(__name__)

VALID_REGIMES = {"SURGE", "HIGH", "NORMAL", "LOW", "QUIET", "TRANSITION"}

SYSTEM_PROMPT = """You classify news context into a posting regime for a social media activity prediction model.
Given recent headlines about a public figure, classify the expected posting behavior.

Respond with ONLY one of: SURGE, HIGH, NORMAL, LOW, QUIET
- SURGE: Major controversy, legal event, public feud, or crisis that will drive extreme posting
- HIGH: Significant news event, rally, speech, policy announcement
- NORMAL: Typical news cycle, no major catalysts
- LOW: Quiet period, travel, low-engagement news
- QUIET: Extended absence indicators, vacation, minimal public activity"""


async def classify_news_regime(
    headlines: list[str],
    conflict_score: int = 0,
    schedule_events: list[str] | None = None,
    handle: str = "Trump",
) -> dict:
    settings = get_settings()
    api_key = getattr(settings, "anthropic_api_key", None)
    if not api_key:
        return {"override": None, "reason": "no API key"}

    if not headlines and conflict_score < 3 and not schedule_events:
        return {"override": None, "reason": "insufficient context"}

    context = f"Headlines about {handle} (last 24h):\n"
    for h in headlines[:10]:
        context += f"- {h}\n"
    if schedule_events:
        context += f"\nScheduled events: {', '.join(schedule_events)}\n"
    context += f"\nConflict score (0-20): {conflict_score}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-20250414",
                    "max_tokens": 10,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": context}],
                },
            )
            res.raise_for_status()
            data = res.json()
            answer = data["content"][0]["text"].strip().upper()

            if answer in VALID_REGIMES:
                log.info(f"Claude regime override: {answer}")
                return {"override": answer, "reason": f"Claude classified from {len(headlines)} headlines"}
            return {"override": None, "reason": f"invalid response: {answer}"}
    except Exception as e:
        log.warning(f"Claude regime classification failed: {e}")
        return {"override": None, "reason": str(e)}
