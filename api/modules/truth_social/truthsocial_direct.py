"""Direct Truth Social API fetcher (Mastodon-compatible).

Independent of xTracker — used as a verification source for post counts and as
the source-of-truth raw archive for backfills.

Truth Social forked Mastodon, so the v1 statuses API is public and unauthenticated.
Cloudflare blocks Python httpx by TLS fingerprint, so we use curl_cffi which
impersonates a real Chrome TLS handshake. Even then, datacenter IPs and high
request volumes get rate-limited or 403'd; we rotate impersonate profiles and
back off aggressively (up to 15 min) to recover.

Optional: set TS_PROXY env var to route through a residential proxy for unattended
backfills. Format: "http://user:pass@host:port" or "socks5://host:port".
"""
import asyncio
import logging
import os
import random
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

_IMPERSONATE_PROFILES = ["chrome110", "safari17_0", "firefox133", "chrome116", "chrome119", "safari15_5"]

# Aggressive backoff schedule (seconds) for unattended runs
_BACKOFF_SCHEDULE = [10, 30, 90, 300, 600, 900]


def _proxy_config() -> dict | None:
    proxy = os.getenv("TS_PROXY")
    if not proxy:
        return None
    return {"https": proxy, "http": proxy}


async def _get_json(
    url: str,
    params: dict | None = None,
    max_retries: int = 6,
    aggressive: bool = False,
) -> tuple[dict | list | None, int | None]:
    """Fetch JSON with TLS impersonation and rotating profiles on rate-limit.

    Returns (data, last_status_code). data is None if all retries failed.
    `aggressive=True` uses _BACKOFF_SCHEDULE (up to 15 min waits) for unattended backfills.
    """
    if not HAS_CURL_CFFI:
        async with httpx.AsyncClient(timeout=20, headers=BROWSER_HEADERS) as client:
            try:
                res = await client.get(url, params=params)
                res.raise_for_status()
                return res.json(), 200
            except httpx.HTTPStatusError as e:
                return None, e.response.status_code
            except Exception:
                return None, None

    last_status: int | None = None
    proxies = _proxy_config()

    for attempt in range(max_retries):
        profile = _IMPERSONATE_PROFILES[attempt % len(_IMPERSONATE_PROFILES)]
        try:
            session_kwargs = {"timeout": 30, "impersonate": profile}
            if proxies:
                session_kwargs["proxies"] = proxies

            async with AsyncSession(**session_kwargs) as s:
                res = await s.get(url, params=params)
                last_status = res.status_code

                if res.status_code == 200:
                    return res.json(), 200

                if res.status_code in (429, 403, 503, 502):
                    if aggressive:
                        wait = _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
                    else:
                        wait = min(30, 5 * (attempt + 1))
                    wait += random.uniform(0, wait * 0.2)
                    log.info(f"Truth Social {res.status_code} on {profile}, backing off {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(wait)
                    continue

                log.warning(f"Truth Social {url} returned {res.status_code}")
                return None, res.status_code
        except Exception as e:
            log.warning(f"Truth Social request error ({profile}): {e}")
            await asyncio.sleep(5)

    log.warning(f"Truth Social {url} exhausted retries (last_status={last_status})")
    return None, last_status


async def lookup_account_id(handle: str = DEFAULT_HANDLE) -> str | None:
    try:
        data, _ = await _get_json(f"{TS_BASE}/accounts/lookup", {"acct": handle})
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


async def fetch_statuses_page(
    account_id: str,
    max_id: str | None = None,
    since_id: str | None = None,
    limit: int = PAGE_SIZE,
    aggressive: bool = False,
) -> tuple[list[dict] | None, int | None]:
    """Fetch one page of statuses. Returns (page, status_code)."""
    params: dict = {
        "limit": limit,
        "exclude_replies": "false",
        "exclude_reblogs": "false",
    }
    if max_id:
        params["max_id"] = max_id
    if since_id:
        params["since_id"] = since_id

    page, code = await _get_json(
        f"{TS_BASE}/accounts/{account_id}/statuses",
        params,
        aggressive=aggressive,
    )
    if not isinstance(page, list):
        return None, code
    return page, code


async def fetch_statuses_in_window(
    account_id: str,
    window_start: datetime,
    window_end: datetime,
    exclude_replies: bool = False,
    exclude_reblogs: bool = False,
    since_id: str | None = None,
) -> list[dict]:
    """Fetch all statuses within a time window. Optional since_id avoids re-pulling old posts."""
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)

    statuses: list[dict] = []
    max_id: str | None = None

    for _ in range(MAX_PAGES):
        page, _code = await fetch_statuses_page(account_id, max_id=max_id, since_id=since_id)
        if not page:
            break

        oldest_in_page: datetime | None = None
        for s in page:
            created = _parse_iso(s.get("created_at", ""))
            if created is None:
                continue
            if (not exclude_replies or not s.get("in_reply_to_id")) \
                    and (not exclude_reblogs or not s.get("reblog")):
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
    since_id: str | None = None,
) -> dict:
    aid = account_id or DEFAULT_ACCOUNT_ID
    if handle != DEFAULT_HANDLE and account_id is None:
        looked_up = await lookup_account_id(handle)
        if looked_up:
            aid = looked_up

    if not aid:
        return {"count": None, "latest_post_at": None, "account_id": None, "error": "no_account_id"}

    statuses = await fetch_statuses_in_window(aid, window_start, window_end, since_id=since_id)
    latest = max((_parse_iso(s.get("created_at", "")) for s in statuses), default=None)
    return {
        "count": len(statuses),
        "latest_post_at": latest.isoformat() if latest else None,
        "account_id": aid,
        "sample_ids": [s.get("id") for s in statuses[:5]],
    }
