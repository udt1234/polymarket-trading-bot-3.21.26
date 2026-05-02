"""Truth Social post fetch via CNN's public archive.

CNN runs a public archive of @realDonaldTrump posts at
https://ix.cnn.io/data/truth-social/truth_archive.json — refreshed every ~5
minutes from their own infrastructure (which has already defeated truthsocial.com's
Cloudflare challenge). For the bot's only use case (counting Trump posts in a
specific window), this is a strict superset of what truthsocial.com's API gives us:

- Public CDN (Fastly/Varnish), no auth, no rate limits, no Cloudflare challenge
- Same fields the bot already uses: id, created_at, content, url, media, counts
- ~30k+ posts, full archive going back to 2022
- 5-min refresh cadence is acceptable (the bot's snapshot job runs every 5 min anyway)

This fetcher is the FIRST-CHOICE source. Direct truthsocial.com hits are a
fallback now since they fail from datacenter IPs (Railway included).

Tradeoffs vs direct truthsocial.com:
- 5-min latency: a Trump post within the last 5 minutes may not yet be in the
  archive. Acceptable — the bot's auction windows are weekly so 5-min latency
  is in the noise.
- Trump-only: CNN doesn't archive other accounts. Module HANDLE constant must
  match `realDonaldTrump`. For Elon (or future handles), fall back to direct.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

log = logging.getLogger(__name__)

CNN_ARCHIVE_URL = "https://ix.cnn.io/data/truth-social/truth_archive.json"
CNN_HANDLE = "realDonaldTrump"
# Cache the full archive in-process for 4 minutes. CNN refreshes every 5,
# so we re-fetch shortly before the archive itself updates.
_CACHE_TTL_SECONDS = 240

# Module-level cache: (timestamp, posts_list)
_cache: tuple[float, list[dict]] | None = None
_cache_lock = asyncio.Lock()


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def _fetch_archive() -> list[dict]:
    """Fetch the full CNN archive. ~17 MB JSON, served from CDN with HTTP/2.
    Returns the list of post dicts. Raises on transport failure."""
    if httpx is None:
        raise RuntimeError("httpx not available — install httpx to use CNN archive")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        res = await client.get(CNN_ARCHIVE_URL, headers={
            "Accept": "application/json",
            "User-Agent": "polymarket-bot/1.0 (+truthsocial archive consumer)",
        })
        res.raise_for_status()
        data = res.json()
    if not isinstance(data, list):
        raise ValueError(f"CNN archive returned unexpected shape: {type(data).__name__}")
    return data


async def _get_archive_cached() -> list[dict]:
    """Cached archive fetch. One concurrent fetch even if many callers hit at once."""
    global _cache
    now = time.time()
    if _cache is not None and (now - _cache[0]) < _CACHE_TTL_SECONDS:
        return _cache[1]
    async with _cache_lock:
        # Re-check inside the lock — another coroutine may have refreshed already.
        if _cache is not None and (time.time() - _cache[0]) < _CACHE_TTL_SECONDS:
            return _cache[1]
        log.info(f"Fetching CNN truthsocial archive ({CNN_ARCHIVE_URL})")
        data = await _fetch_archive()
        _cache = (time.time(), data)
        log.info(f"CNN archive cached: {len(data)} posts")
        return data


async def count_posts_in_window_via_cnn(
    window_start: datetime, window_end: datetime, handle: str = CNN_HANDLE,
) -> dict:
    """Count posts in [window_start, window_end] for the given handle.

    Returns the same shape as truthsocial_direct.count_posts_in_window so the
    pacing endpoint and snapshot job can use either source interchangeably:
        { count, latest_post_at, account_id, source }
    """
    if handle != CNN_HANDLE:
        return {
            "count": None,
            "latest_post_at": None,
            "account_id": None,
            "error": f"CNN archive only covers {CNN_HANDLE}, not {handle}",
            "source": "cnn_archive",
        }

    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)

    posts = await _get_archive_cached()

    matched = []
    latest: datetime | None = None
    # Archive is newest-first, so we can short-circuit when we cross window_start.
    for p in posts:
        created = _parse_iso(p.get("created_at", ""))
        if created is None:
            continue
        if created < window_start:
            # Newest-first ordering — everything beyond this is older.
            break
        if created > window_end:
            continue
        matched.append(p)
        if latest is None or created > latest:
            latest = created

    return {
        "count": len(matched),
        "latest_post_at": latest.isoformat() if latest else None,
        "account_id": None,  # CNN archive doesn't expose this; not needed for counts.
        "source": "cnn_archive",
        "sample_ids": [p.get("id") for p in matched[:5]],
    }
