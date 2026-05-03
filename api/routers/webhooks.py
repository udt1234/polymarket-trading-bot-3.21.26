"""Public webhook endpoints (no auth middleware).

Endpoints here MUST authenticate via shared secret in the URL path
(e.g. /webhooks/ifttt/{secret}/...) or in headers, since they are not
behind the require_auth middleware. The secret is set via env var
`WEBHOOK_SECRET` and rotated by changing the env var.
"""
import os
import re
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request

from api.dependencies import get_supabase

log = logging.getLogger(__name__)
router = APIRouter()


def _check_secret(provided: str) -> None:
    expected = os.getenv("WEBHOOK_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="WEBHOOK_SECRET not configured")
    if provided != expected:
        raise HTTPException(status_code=401, detail="invalid secret")


def _extract_tweet_id(url: str | None, link_to_tweet: str | None = None) -> str | None:
    for candidate in (url, link_to_tweet):
        if not candidate:
            continue
        m = re.search(r"status(?:es)?/(\d+)", candidate)
        if m:
            return m.group(1)
    return None


@router.post("/ifttt/{secret}/elon-tweet")
async def ifttt_elon_tweet(secret: str, request: Request):
    """IFTTT 'New tweet by specific user' (elonmusk) webhook.

    Configure IFTTT applet:
      Trigger: Twitter → New tweet by specific user (elonmusk)
      Action:  Webhooks → Make a web request
        URL: https://<api-host>/api/webhooks/ifttt/<WEBHOOK_SECRET>/elon-tweet
        Method: POST
        Content Type: application/json
        Body: {
          "user_name": "{{UserName}}",
          "text": "<<<{{Text}}>>>",
          "created_at": "{{CreatedAt}}",
          "link_to_tweet": "{{LinkToTweet}}",
          "first_link_url": "{{FirstLinkUrl}}",
          "tweet_embed_code": "<<<{{TweetEmbedCode}}>>>"
        }
    """
    _check_secret(secret)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    text = payload.get("text") or ""
    link = payload.get("link_to_tweet") or payload.get("url")
    tweet_id = _extract_tweet_id(payload.get("url"), link)
    if not tweet_id:
        # IFTTT sometimes can't give us an ID — synthesize one to avoid losing the row
        tweet_id = f"ifttt-{datetime.now(timezone.utc).timestamp()}"

    created_raw = payload.get("created_at") or payload.get("CreatedAt") or ""
    try:
        # IFTTT format: "May 03, 2026 at 02:45AM"
        created_at = datetime.strptime(created_raw, "%B %d, %Y at %I:%M%p").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        try:
            created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except Exception:
            created_at = datetime.now(timezone.utc)

    is_reply = text.startswith("@") or text.startswith("RT @") is False and "@" in text[:3]
    is_retweet = text.startswith("RT @")
    is_quote = bool(payload.get("tweet_embed_code")) and not is_retweet

    sb = get_supabase()
    try:
        sb.table("elon_tweets").upsert({
            "id": tweet_id,
            "handle": payload.get("user_name", "elonmusk").lower(),
            "created_at": created_at.isoformat(),
            "url": link,
            "text": text,
            "is_reply": is_reply,
            "is_retweet": is_retweet,
            "is_quote": is_quote,
            "raw": payload,
            "source": "ifttt",
        }).execute()
    except Exception as e:
        log.error(f"Failed to store IFTTT tweet {tweet_id}: {e}")
        raise HTTPException(status_code=500, detail="storage failed")

    return {"ok": True, "id": tweet_id}


@router.get("/ifttt/{secret}/test")
async def ifttt_test(secret: str):
    """Quick connectivity test for IFTTT setup."""
    _check_secret(secret)
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}
