"""
Verify Truth Social post counts directly against truthsocial.com.

Use this to cross-check xTracker counts before placing a bet, or to settle
post-mortem disputes after a market resolves differently than xTracker reported.

Usage:
  python scripts/verify_post_count.py --start 2026-04-17T16:00:00Z --end 2026-04-24T16:00:00Z
  python scripts/verify_post_count.py --start 2026-04-17T16:00:00Z --end 2026-04-24T16:00:00Z --handle realDonaldTrump
  python scripts/verify_post_count.py --start 2026-04-17T16:00:00Z --end 2026-04-24T16:00:00Z --xtracker 198

Note: Polymarket's "noon ET" boundary is 16:00 UTC (during EDT) or 17:00 UTC (during EST).
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.modules.truth_social.truthsocial_direct import count_posts_in_window, lookup_account_id


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="ISO8601 start (e.g. 2026-04-17T16:00:00Z)")
    p.add_argument("--end", required=True, help="ISO8601 end (e.g. 2026-04-24T16:00:00Z)")
    p.add_argument("--handle", default="realDonaldTrump")
    p.add_argument("--xtracker", type=int, help="Optional xTracker count to compare against")
    args = p.parse_args()

    w_start = parse_iso(args.start)
    w_end = parse_iso(args.end)

    print(f"Handle: @{args.handle}")
    print(f"Window: {w_start.isoformat()}  to  {w_end.isoformat()}")
    print(f"Span:   {(w_end - w_start).total_seconds() / 86400:.2f} days")
    print()
    print("Fetching from truthsocial.com/api/v1 ...")

    if args.handle != "realDonaldTrump":
        aid = await lookup_account_id(args.handle)
        print(f"Looked up account_id: {aid}")
    else:
        aid = None

    result = await count_posts_in_window(w_start, w_end, handle=args.handle, account_id=aid)

    print()
    print("=" * 50)
    print(f"  Truth Social direct count: {result['count']}")
    if result.get("latest_post_at"):
        print(f"  Latest post in window:     {result['latest_post_at']}")
    if result.get("account_id"):
        print(f"  Account ID:                {result['account_id']}")
    if result.get("sample_ids"):
        print(f"  Sample status IDs:         {result['sample_ids']}")
    if result.get("error"):
        print(f"  Error: {result['error']}")
    print("=" * 50)

    if args.xtracker is not None and isinstance(result.get("count"), int):
        diff = result["count"] - args.xtracker
        print()
        print(f"  xTracker count: {args.xtracker}")
        print(f"  Direct count:   {result['count']}")
        print(f"  Difference:     {diff:+d}  ({'direct higher' if diff > 0 else 'xTracker higher' if diff < 0 else 'match'})")


if __name__ == "__main__":
    asyncio.run(main())
