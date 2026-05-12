"""One-shot backfill: positions.token_id for paper-era rows.

Existing open positions were written before migration 015 added the
token_id column. Without it, live exits will refuse to submit (the
LiveExecutor guard rejects signals with token_id=None).

Usage:
    python scripts/backfill_position_token_ids.py            # dry-run
    python scripts/backfill_position_token_ids.py --apply    # write

Idempotent — only touches rows where token_id IS NULL. Run from the
project root with the Supabase env vars set (same as the API service).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Make `api` importable when run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from api.dependencies import get_supabase  # noqa: E402

GAMMA_BASE = "https://gamma-api.polymarket.com"


def _normalize_bracket(label: str) -> str:
    return (label or "").strip().lower()


async def _fetch_token_for_market(market_id: str, bracket: str) -> str | None:
    """Resolve the ERC-1155 token ID for a (market_id, bracket) pair.

    `market_id` here is the Gamma market `id` (integer string). We query
    Gamma directly for that market and pull clobTokenIds[0]. Falls back
    to None when nothing matches.
    """
    if not market_id:
        return None
    # Numeric market IDs use the path-style endpoint /markets/{id}.
    # Slug-style market IDs (e.g. legacy Trump rows storing the event slug)
    # fall through to _fetch_token_via_event() at the bottom of this function.
    m = None
    if market_id.isdigit():
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.get(f"{GAMMA_BASE}/markets/{market_id}")
                r.raise_for_status()
                m = r.json()
            except Exception as e:
                print(f"  ! gamma /markets/{market_id} failed: {e}")
    else:
        # market_id looks like a slug — go straight to the event lookup.
        return await _fetch_token_via_event(market_id, bracket)
    if not isinstance(m, dict) or not m:
        return None
    raw = m.get("groupItemTitle") or m.get("question") or ""
    if _normalize_bracket(raw) != _normalize_bracket(bracket):
        # market_id alone may not pin down the bracket — try the parent event.
        slug = m.get("eventSlug") or m.get("slug")
        if slug:
            return await _fetch_token_via_event(slug, bracket)
    raw_ids = m.get("clobTokenIds")
    if isinstance(raw_ids, str):
        try:
            raw_ids = json.loads(raw_ids)
        except Exception:
            raw_ids = []
    if isinstance(raw_ids, list) and raw_ids:
        return str(raw_ids[0])
    return None


async def _fetch_token_via_event(slug: str, bracket: str) -> str | None:
    target = _normalize_bracket(bracket)
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(f"{GAMMA_BASE}/events", params={"slug": slug})
            r.raise_for_status()
            events = r.json()
        except Exception as e:
            print(f"  ! gamma event fetch failed for slug={slug}: {e}")
            return None
    if not isinstance(events, list) or not events:
        return None
    for m in events[0].get("markets", []):
        if _normalize_bracket(m.get("groupItemTitle") or m.get("question") or "") != target:
            continue
        raw_ids = m.get("clobTokenIds")
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except Exception:
                raw_ids = []
        if isinstance(raw_ids, list) and raw_ids:
            return str(raw_ids[0])
    return None


async def main(apply_changes: bool):
    sb = get_supabase()
    res = (
        sb.table("positions")
        .select("id,module_id,market_id,bracket,status,token_id")
        .is_("token_id", "null")
        .execute()
    )
    rows = res.data or []
    print(f"Found {len(rows)} positions with NULL token_id")
    if not rows:
        return

    resolved = 0
    failed = 0
    for r in rows:
        token = await _fetch_token_for_market(r.get("market_id") or "", r.get("bracket") or "")
        status_tag = r.get("status") or "?"
        if not token:
            failed += 1
            print(f"  FAIL  {r['id'][:8]} [{status_tag}] market={r.get('market_id')} bracket={r.get('bracket')}")
            continue
        resolved += 1
        action = "WOULD" if not apply_changes else "WRITE"
        print(f"  {action} {r['id'][:8]} [{status_tag}] market={r.get('market_id')} bracket={r.get('bracket')} -> token={token[:16]}...")
        if apply_changes:
            try:
                sb.table("positions").update({"token_id": token}).eq("id", r["id"]).execute()
            except Exception as e:
                failed += 1
                resolved -= 1
                print(f"  ! update failed for {r['id']}: {e}")

    print(f"\nDone. resolved={resolved} failed={failed} applied={apply_changes}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes (otherwise dry-run)")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
