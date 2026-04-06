"""
Backfill historical bracket prices from Polymarket CLOB API into Supabase.

Pulls hourly price data for all past and active Trump Truth Social auctions.

Usage:
  python scripts/backfill_prices.py
  python scripts/backfill_prices.py --weeks 4    # only last 4 weeks
  python scripts/backfill_prices.py --dry-run    # preview without writing

Requires: SUPABASE_URL + SUPABASE_KEY in .env
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"
XTRACKER_BASE = "https://xtracker.polymarket.com/api"
CHUNK_DAYS = 14
RATE_DELAY = 0.5


async def fetch_all_trackings(handle: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(
            f"{XTRACKER_BASE}/users/{handle}/trackings",
            params={"platform": "truthsocial"},
        )
        res.raise_for_status()
        data = res.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(items, dict):
            items = items.get("trackings", [])
        return [t for t in items if "truth social" in t.get("title", "").lower()]


def extract_slug(tracking: dict) -> str | None:
    from urllib.parse import urlparse
    import re
    link = tracking.get("marketLink", "")
    if link:
        path = urlparse(link).path.strip("/").split("/")
        if len(path) >= 2 and path[0] == "event":
            return path[1]
        if path and path[-1]:
            return path[-1]
    # Construct slug from title when marketLink is missing
    title = tracking.get("title", "")
    match = re.search(r"posts\s+(.+?)(?:,\s*\d{4})?\s*\??\s*$", title, re.I)
    if match:
        date_part = match.group(1).strip().lower()
        date_part = date_part.replace(" - ", "-").replace(" ", "-")
        return f"donald-trump-of-truth-social-posts-{date_part}"
    return None


async def fetch_bracket_tokens(slug: str) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
        res.raise_for_status()
        events = res.json()
        if not isinstance(events, list) or not events:
            return {}
        tokens = {}
        for m in events[0].get("markets", []):
            bracket = m.get("groupItemTitle", m.get("question", ""))
            token_ids = m.get("clobTokenIds", "[]")
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if token_ids and bracket:
                tokens[bracket] = token_ids[0]
        return tokens


async def fetch_price_history(token_id: str, start_ts: int, end_ts: int) -> list[dict]:
    """Fetch hourly prices for a token in a time window."""
    async with httpx.AsyncClient(timeout=30) as client:
        params = {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "fidelity": 60,
        }
        res = await client.get(f"{CLOB_BASE}/prices-history", params=params)
        if res.status_code != 200:
            return []
        data = res.json()
        return data.get("history", [])


async def fetch_chunked_prices(token_id: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Fetch prices in CHUNK_DAYS-day windows to work around resolved market limits."""
    all_points = []
    current = start_dt
    while current < end_dt:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS), end_dt)
        start_ts = int(current.timestamp())
        end_ts = int(chunk_end.timestamp())
        points = await fetch_price_history(token_id, start_ts, end_ts)
        all_points.extend(points)
        await asyncio.sleep(RATE_DELAY)
        current = chunk_end
    return all_points


def get_supabase():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    return create_client(url, key)


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=0, help="Only backfill last N weeks (0=all)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--handle", default="realDonaldTrump")
    args = parser.parse_args()

    print("Fetching trackings...")
    trackings = await fetch_all_trackings(args.handle)
    print(f"  Found {len(trackings)} Trump Truth Social trackings")

    if args.weeks > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(weeks=args.weeks)
        trackings = [t for t in trackings if t.get("startDate", "")[:10] >= cutoff.strftime("%Y-%m-%d")]
        print(f"  Filtered to {len(trackings)} (last {args.weeks} weeks)")

    if not trackings:
        print("No trackings found.")
        return

    sb = None if args.dry_run else get_supabase()

    # Get module_id from Supabase
    module_id = None
    if sb:
        mod = sb.table("modules").select("id").ilike("name", "%truth social%").limit(1).execute()
        if mod.data:
            module_id = mod.data[0]["id"]
            print(f"  Module ID: {module_id}")
        else:
            print("  ERROR: No Truth Social module found in Supabase")
            return

    total_snapshots = 0
    slugs_seen = set()

    for tracking in trackings:
        title = tracking.get("title", "")[:60]
        start_str = tracking.get("startDate", "")[:10]
        end_str = tracking.get("endDate", "")[:10]
        tracking_id = str(tracking.get("id") or tracking.get("trackingId") or "")

        slug = extract_slug(tracking)
        if not slug or slug in slugs_seen:
            continue
        slugs_seen.add(slug)

        print(f"\n--- {title}")
        print(f"    Period: {start_str} -> {end_str}, Slug: {slug}")

        # Get token IDs for each bracket
        tokens = await fetch_bracket_tokens(slug)
        if not tokens:
            print(f"    SKIP: No token IDs found for slug '{slug}'")
            continue
        print(f"    Brackets: {len(tokens)} — {list(tokens.keys())[:5]}...")

        start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)

        # Calculate elapsed_days relative to auction start
        auction_rows = []

        for bracket, token_id in tokens.items():
            prices = await fetch_chunked_prices(token_id, start_dt, end_dt)
            if not prices:
                print(f"    {bracket}: 0 price points")
                continue

            for point in prices:
                ts = point.get("t", 0)
                price = point.get("p", 0)
                if not ts or not price:
                    continue
                try:
                    price = float(price)
                except (ValueError, TypeError):
                    continue
                if price <= 0 or price >= 1:
                    continue

                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                snapshot_hour = dt.replace(minute=0, second=0, microsecond=0)
                elapsed = (dt - start_dt).total_seconds() / 86400

                auction_rows.append({
                    "module_id": module_id,
                    "bracket": bracket,
                    "price": round(price, 6),
                    "snapshot_hour": snapshot_hour.isoformat(),
                    "dow": dt.weekday(),
                    "hour_of_day": dt.hour,
                    "elapsed_days": round(elapsed, 2),
                    "tracking_id": tracking_id,
                })

            print(f"    {bracket}: {len(prices)} price points")
            await asyncio.sleep(RATE_DELAY)

        if auction_rows:
            print(f"    Total rows: {len(auction_rows)}")
            if args.dry_run:
                print(f"    DRY RUN — would insert {len(auction_rows)} rows")
            else:
                # Batch insert in chunks of 500
                for i in range(0, len(auction_rows), 500):
                    batch = auction_rows[i:i+500]
                    try:
                        sb.table("price_snapshots").upsert(
                            batch, on_conflict="module_id,bracket,snapshot_hour"
                        ).execute()
                    except Exception as e:
                        print(f"    ERROR inserting batch {i}: {e}")
                print(f"    Inserted {len(auction_rows)} rows")
            total_snapshots += len(auction_rows)

    print(f"\n=== Done: {total_snapshots} total price snapshots across {len(slugs_seen)} auctions ===")


if __name__ == "__main__":
    asyncio.run(main())
