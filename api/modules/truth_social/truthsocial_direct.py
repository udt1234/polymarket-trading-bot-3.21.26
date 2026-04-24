"""Direct Truth Social API fetcher (Mastodon-compatible).

Independent of xTracker — used as a verification source for post counts.
Truth Social forked Mastodon, so the v1 statuses API is public and unauthenticated.
Cloudflare blocks Python httpx by TLS fingerprint, so we use curl_cffi which
impersonates a real Chrome TLS handshake.
"""
import asyncio
import logging
from datetime import datetime, timezone

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    import httpx
    HAS_CURL_CFFI = False

log = logging.getLogger(__name__)

TS_BASE = "https://truthsocial.com/api/v1"
DEFAULT_HANDLE = "realDonaldTrump"
DEFAULT_ACCOUNT_ID = "107780257626128497"
PAGE_SIZE = 40
MAX_PAGES = 30

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://truthsocial.com/",
    "Origin": "https://truthsocial.com",
}


_IMPERSONATE_PROFILES = ["chrome110", "safari17_0", "firefox133", "chrome116"]


async def _get_json(url: str, params: dict | None = None, max_retries: int = 5) -> dict | list | None:
    if HAS_CURL_CFFI:
        for attempt in range(max_retries):
            profile = _IMPERSONATE_PROFILES[attempt % len(_IMPERSONATE_PROFILES)]
            try:
                async with AsyncSession(timeout=25, impersonate=profile) as s:
                    res = await s.get(url, params=params)
                    if res.status_code == 200:
                        return res.json()
                    if res.status_code in (429, 403):
                        wait = min(30, 3 * (attempt + 1))
                        log.info(f"Truth Social {res.status_code} on {profile}, backing off {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    log.warning(f"Truth Social {url} returned {res.status_code}")
                    return None
            except Exception as e:
                log.warning(f"Truth Social request error ({profile}): {e}")
                await asyncio.sleep(3)
        log.warning(f"Truth Social {url} exhausted retries")
        return None
    else:
        async with httpx.AsyncClient(timeout=20, headers=BROWSER_HEADERS) as client:
            res = await client.get(url, params=params)
            res.raise_for_status()
            return res.json()


async def lookup_account_id(handle: str = DEFAULT_HANDLE) -> str | None:
    try:
        data = await _get_json(f"{TS_BASE}/accounts/lookup", {"acct": handle})
        if isinstance(data, dict):
            return data.get("id")
        return None
    except Exception as e:
        log.warning(f"Truth Social lookup failed for {handle}: {e}")
        return None


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def fetch_statuses_in_window(
    account_id: str,
    window_start: datetime,
    window_end: datetime,
    exclude_replies: bool = False,
    exclude_reblogs: bool = False,
) -> list[dict]:
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)

    statuses: list[dict] = []
    max_id: str | None = None

    for _ in range(MAX_PAGES):
        params: dict = {
            "limit": PAGE_SIZE,
            "exclude_replies": str(exclude_replies).lower(),
            "exclude_reblogs": str(exclude_reblogs).lower(),
        }
        if max_id:
            params["max_id"] = max_id

        try:
            page = await _get_json(f"{TS_BASE}/accounts/{account_id}/statuses", params)
        except Exception as e:
            log.warning(f"Truth Social statuses fetch failed: {e}")
            break

        if not isinstance(page, list) or not page:
            break

        oldest_in_page: datetime | None = None
        for s in page:
            created = _parse_iso(s.get("created_at", ""))
            if created is None:
                continue
            if window_start <= created <= window_end:
                statuses.append(s)
            if oldest_in_page is None or created < oldest_in_page:
                oldest_in_page = created

        if oldest_in_page and oldest_in_page < window_start:
            break

        last_id = page[-1].get("id")
        if not last_id or last_id == max_id:
            break
        max_id = last_id
        await asyncio.sleep(1.5)

    return statuses


async def count_posts_in_window(
    window_start: datetime,
    window_end: datetime,
    handle: str = DEFAULT_HANDLE,
    account_id: str | None = None,
) -> dict:
    aid = account_id or DEFAULT_ACCOUNT_ID
    if handle != DEFAULT_HANDLE and account_id is None:
        looked_up = await lookup_account_id(handle)
        if looked_up:
            aid = looked_up

    if not aid:
        return {"count": None, "latest_post_at": None, "account_id": None, "error": "no_account_id"}

    statuses = await fetch_statuses_in_window(aid, window_start, window_end)
    latest = max((_parse_iso(s.get("created_at", "")) for s in statuses), default=None)
    return {
        "count": len(statuses),
        "latest_post_at": latest.isoformat() if latest else None,
        "account_id": aid,
        "sample_ids": [s.get("id") for s in statuses[:5]],
    }
