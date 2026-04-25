"""
Full-history backfill of Truth Social posts into Supabase.

Walks back from the oldest post we already have (or today if empty) using
max_id pagination until we hit the user's first post or 200 consecutive
empty/error pages. Idempotent: safe to re-run, picks up where it left off.

Usage:
  # local one-shot (will run for hours due to rate limits — leave it on)
  python scripts/backfill_truth_social.py --handle realDonaldTrump

  # set max wall-clock minutes (Railway cron-friendly)
  python scripts/backfill_truth_social.py --handle realDonaldTrump --max-minutes 60

  # forward-fill mode (only new posts since the newest one in DB)
  python scripts/backfill_truth_social.py --handle realDonaldTrump --forward

Env vars:
  SUPABASE_URL, SUPABASE_SERVICE_KEY  — required, for DB writes
  TS_PROXY                            — optional residential proxy URL
"""
import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.modules.truth_social.truthsocial_direct import (
    DEFAULT_ACCOUNT_ID,
    DEFAULT_HANDLE,
    fetch_statuses_page,
    lookup_account_id,
    _parse_iso,
)
from api.dependencies import get_supabase

PAGE_SLEEP_SUCCESS = 2.0
PAGE_SLEEP_ERROR = 60.0
MAX_CONSECUTIVE_ERRORS = 8


def _row_from_status(s: dict, handle: str, account_id: str) -> dict:
    return {
        "id": s["id"],
        "account_id": account_id,
        "handle": handle,
        "created_at": s.get("created_at"),
        "is_reply": s.get("in_reply_to_id") is not None,
        "is_reblog": s.get("reblog") is not None,
        "in_reply_to_id": s.get("in_reply_to_id"),
        "reblog_of_id": (s.get("reblog") or {}).get("id") if s.get("reblog") else None,
        "raw": s,
    }


def _checkpoint_load(sb, handle: str) -> dict | None:
    res = sb.table("backfill_progress").select("*").eq("handle", handle).execute()
    return res.data[0] if res.data else None


def _checkpoint_save(sb, handle: str, **fields):
    fields["handle"] = handle
    fields["source"] = "truthsocial_direct"
    fields["last_run_at"] = datetime.now(timezone.utc).isoformat()
    sb.table("backfill_progress").upsert(fields, on_conflict="handle").execute()


def _get_db_oldest_id(sb, handle: str) -> str | None:
    res = sb.table("truth_social_posts").select("id,created_at").eq("handle", handle) \
        .order("created_at", desc=False).limit(1).execute()
    if res.data:
        return res.data[0]["id"]
    return None


def _get_db_newest_id(sb, handle: str) -> str | None:
    res = sb.table("truth_social_posts").select("id,created_at").eq("handle", handle) \
        .order("created_at", desc=True).limit(1).execute()
    if res.data:
        return res.data[0]["id"]
    return None


async def backfill_backward(handle: str, account_id: str, max_minutes: int | None) -> int:
    """Walk back from oldest post we have (or now) until we hit the start of time."""
    sb = get_supabase()
    started_at = time.time()
    deadline = started_at + (max_minutes * 60) if max_minutes else None

    checkpoint = _checkpoint_load(sb, handle) or {}
    if checkpoint.get("is_complete"):
        print(f"Backfill already marked complete for @{handle}. Use --forward for new posts.")
        return 0

    max_id = checkpoint.get("oldest_fetched_id") or _get_db_oldest_id(sb, handle)
    pages_done = checkpoint.get("total_pages_fetched", 0)
    posts_stored = checkpoint.get("total_posts_stored", 0)
    consecutive_errors = 0

    print(f"Starting backward backfill for @{handle} (account_id={account_id})")
    print(f"  Resuming from max_id={max_id or 'NEWEST'}")
    print(f"  Pages already fetched: {pages_done}, posts stored: {posts_stored}")

    while True:
        if deadline and time.time() > deadline:
            print(f"Hit max-minutes deadline. Stopping cleanly.")
            break

        page, code = await fetch_statuses_page(account_id, max_id=max_id, aggressive=True)

        if not page:
            consecutive_errors += 1
            print(f"  empty/error page (status={code}, consecutive={consecutive_errors})")
            _checkpoint_save(sb, handle,
                             oldest_fetched_id=max_id,
                             total_pages_fetched=pages_done,
                             total_posts_stored=posts_stored,
                             last_error=f"page returned None (status={code})")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"Too many consecutive errors. Exiting.")
                break
            await asyncio.sleep(PAGE_SLEEP_ERROR)
            continue

        consecutive_errors = 0
        rows = [_row_from_status(s, handle, account_id) for s in page]
        try:
            sb.table("truth_social_posts").upsert(rows, on_conflict="id").execute()
            posts_stored += len(rows)
        except Exception as e:
            print(f"  DB upsert error: {e}")
            _checkpoint_save(sb, handle, last_error=f"db: {str(e)[:200]}")
            await asyncio.sleep(10)
            continue

        pages_done += 1
        oldest_in_page = min(_parse_iso(s.get("created_at", "")) for s in page if s.get("created_at"))
        next_max_id = page[-1].get("id")

        print(f"  page {pages_done}: stored {len(rows)} (total {posts_stored}), oldest_in_page={oldest_in_page.date() if oldest_in_page else '?'}, next_max_id={next_max_id}")

        if not next_max_id or next_max_id == max_id:
            print(f"Reached end of timeline for @{handle}.")
            _checkpoint_save(sb, handle,
                             oldest_fetched_id=max_id,
                             oldest_fetched_at=oldest_in_page.isoformat() if oldest_in_page else None,
                             total_pages_fetched=pages_done,
                             total_posts_stored=posts_stored,
                             is_complete=True,
                             last_error=None)
            break

        max_id = next_max_id

        if pages_done % 5 == 0:
            _checkpoint_save(sb, handle,
                             oldest_fetched_id=max_id,
                             oldest_fetched_at=oldest_in_page.isoformat() if oldest_in_page else None,
                             total_pages_fetched=pages_done,
                             total_posts_stored=posts_stored,
                             last_error=None)

        await asyncio.sleep(PAGE_SLEEP_SUCCESS)

    elapsed = time.time() - started_at
    print(f"\nBackward backfill exited after {elapsed/60:.1f} min")
    print(f"  Pages this session: ?  Total posts stored: {posts_stored}")
    return posts_stored


async def backfill_forward(handle: str, account_id: str) -> int:
    """Pull only posts newer than the newest one in DB."""
    sb = get_supabase()
    since_id = _get_db_newest_id(sb, handle)

    if not since_id:
        print(f"No existing posts for @{handle} — running backward backfill instead.")
        return await backfill_backward(handle, account_id, max_minutes=None)

    print(f"Forward-fill from since_id={since_id}")
    page, code = await fetch_statuses_page(account_id, since_id=since_id, aggressive=True)
    if not page:
        print(f"No new posts (status={code}).")
        return 0

    rows = [_row_from_status(s, handle, account_id) for s in page]
    sb.table("truth_social_posts").upsert(rows, on_conflict="id").execute()
    print(f"Stored {len(rows)} new posts.")
    return len(rows)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--handle", default=DEFAULT_HANDLE)
    p.add_argument("--account-id", default=None)
    p.add_argument("--forward", action="store_true", help="Only fetch posts newer than newest in DB")
    p.add_argument("--max-minutes", type=int, default=None, help="Stop after N minutes of wall clock")
    args = p.parse_args()

    if not (os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY"))):
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY) must be set in env")
        sys.exit(2)

    aid = args.account_id
    if not aid:
        if args.handle == DEFAULT_HANDLE:
            aid = DEFAULT_ACCOUNT_ID
        else:
            aid = await lookup_account_id(args.handle)
            if not aid:
                print(f"Could not look up account_id for @{args.handle}")
                sys.exit(3)

    if args.forward:
        await backfill_forward(args.handle, aid)
    else:
        await backfill_backward(args.handle, aid, args.max_minutes)


if __name__ == "__main__":
    asyncio.run(main())
