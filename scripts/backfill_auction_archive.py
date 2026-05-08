"""Backfill auction_archive from SII-WANGZJ parquet for ALL Elon and Trump
tweet/post auctions. Run once. Idempotent (UPSERT on (handle, auction_slug)).

Usage:
    python scripts/backfill_auction_archive.py [--dry-run] [--handle elonmusk]

For each auction:
  - groups all bracket markets by event_slug
  - reads outcome_prices to determine winner (YES price > 0.5)
  - extracts window_days from auction date range
  - writes one row to auction_archive with bracket_outcomes JSONB
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "_DataMetricPulls"))

from duckdb_remote import connect  # noqa: E402
from supabase import create_client  # noqa: E402


HANDLES = {
    "elonmusk": {
        # Filter on event_slug to avoid basketball/other 'elon' matches.
        "event_slug_pattern": "elon-musk-of-tweets-",
        # Some early markets used a different slug shape; include them too.
        "event_slug_aliases": ["will-elon-tweet-", "will-elon-post-"],
        "platform": "x",
    },
    "realDonaldTrump": {
        "event_slug_pattern": "donald-trump-of-truth-social-posts-",
        "event_slug_aliases": [
            "donald-trump-of-truth-posts-",
            "what-will-trump-post-this-week-",
            "donald-trump-truth-social-posts-",
            "how-many-times-will-trump-post-",
        ],
        "platform": "truthsocial",
    },
}

# Bracket regex: matches strings like '0-19', '40-64', '<40', '200+', '1400+', etc.
BRACKET_RE = re.compile(r"(<\d+|\d+-\d+|\d+\+)")


def _load_supabase_creds() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not (url and key):
        env = REPO_ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("SUPABASE_URL=") and not url:
                    url = line.split("=", 1)[1].strip()
                if line.startswith("SUPABASE_SERVICE_KEY=") and not key:
                    key = line.split("=", 1)[1].strip()
    if not (url and key):
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
    return url, key


def _extract_bracket(question: str) -> str | None:
    """Pull the bracket label from a market question.
    Examples:
      'Will Elon Musk post 40-64 tweets...' -> '40-64'
      'Will Elon Musk tweet less than 20 times...' -> '<20'
      'Will Elon Musk post 1400+ tweets...' -> '1400+'
    """
    if not question:
        return None
    # 'less than N' -> '<N'
    m = re.search(r"less than (\d+)", question, re.IGNORECASE)
    if m:
        return f"<{m.group(1)}"
    m = BRACKET_RE.search(question)
    return m.group(1) if m else None


def fetch_auctions_for_handle(con, handle_meta: dict) -> list[dict]:
    """Return list of auction dicts for a handle.

    One dict per event_slug, with all bracket markets aggregated. Settlement
    price comes from the LAST trade per market in the quant parquet (not the
    snapshot mid-quote in markets.outcome_prices).
    """
    primary = handle_meta["event_slug_pattern"]
    aliases = handle_meta.get("event_slug_aliases", [])
    patterns = [primary] + aliases
    pattern_clause = " OR ".join(f"event_slug LIKE '{p}%'" for p in patterns)

    sql = f"""
    WITH handle_markets AS (
        SELECT id, question, slug, condition_id, token1, token2,
               outcome_prices, volume, event_id, event_slug, event_title,
               created_at, end_date, closed, active
        FROM markets
        WHERE event_slug IS NOT NULL
          AND ({pattern_clause})
          AND end_date IS NOT NULL
          AND end_date < NOW()
    )
    SELECT m.*, q.price AS settled_price
    FROM handle_markets m
    LEFT JOIN (
        SELECT market_id, price
        FROM quant
        QUALIFY ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY timestamp DESC) = 1
    ) q ON q.market_id = m.id
    ORDER BY m.end_date DESC
    """
    print(f"  Querying parquet (event_slug LIKE {primary}%)...")
    con.execute("SET enable_progress_bar = false")
    rows = con.execute(sql).fetchdf()
    print(f"  -> {len(rows):,} bracket markets")

    # Group by event_slug
    by_event: dict[str, list[dict]] = {}
    for _, r in rows.iterrows():
        es = r["event_slug"]
        if not es:
            continue
        by_event.setdefault(es, []).append(dict(r))

    auctions = []
    for event_slug, markets in by_event.items():
        # Resolve outcome
        bracket_outcomes: dict[str, bool] = {}
        bracket_end_prices: dict[str, float] = {}
        winning_bracket: str | None = None
        max_price = -1.0

        import math
        for m in markets:
            bracket = _extract_bracket(m.get("question", ""))
            if not bracket:
                continue
            sp = m.get("settled_price")
            try:
                yes_price = float(sp) if sp is not None else 0.0
                if math.isnan(yes_price) or math.isinf(yes_price):
                    yes_price = 0.0
            except Exception:
                yes_price = 0.0
            bracket_end_prices[bracket] = yes_price
            won = yes_price > 0.5
            bracket_outcomes[bracket] = won
            if won and yes_price > max_price:
                max_price = yes_price
                winning_bracket = bracket

        # Use earliest created_at as start, latest end_date
        created_dates = [m["created_at"] for m in markets if m.get("created_at") is not None]
        end_dates = [m["end_date"] for m in markets if m.get("end_date") is not None]
        if not created_dates or not end_dates:
            continue
        start_dt = min(created_dates)
        end_dt = max(end_dates)
        # Convert pandas Timestamp -> python datetime
        if hasattr(start_dt, "to_pydatetime"):
            start_dt = start_dt.to_pydatetime()
        if hasattr(end_dt, "to_pydatetime"):
            end_dt = end_dt.to_pydatetime()
        window_days = round((end_dt - start_dt).total_seconds() / 86400, 1)

        total_volume = 0.0
        for m in markets:
            v = m.get("volume")
            try:
                vf = float(v) if v is not None else 0.0
                if not (math.isnan(vf) or math.isinf(vf)):
                    total_volume += vf
            except Exception:
                pass

        auctions.append({
            "auction_slug": event_slug,
            "winning_bracket": winning_bracket,
            "bracket_outcomes": bracket_outcomes,
            "bracket_end_prices": bracket_end_prices,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
            "window_days": window_days,
            "total_volume": total_volume,
            "market_count": len(markets),
            "event_title": markets[0].get("event_title", ""),
        })
    return auctions


def upsert_to_supabase(sb, handle: str, platform: str, auctions: list[dict], dry_run: bool):
    rows = []
    for a in auctions:
        rows.append({
            "handle": handle,
            "platform": platform,
            "auction_slug": a["auction_slug"],
            "window_days": a["window_days"],
            "start_date": a["start_date"],
            "end_date": a["end_date"],
            "winning_bracket": a["winning_bracket"],
            "bracket_outcomes": a["bracket_outcomes"],
            "bracket_end_prices": a["bracket_end_prices"],
            "total_volume": a["total_volume"],
            "market_count": a["market_count"],
            "source": "parquet_backfill",
            "metrics": {"event_title": a.get("event_title", "")},
        })

    if dry_run:
        print(f"  DRY RUN: would upsert {len(rows)} rows for {handle}")
        if rows:
            print("  Sample row:")
            sample = dict(rows[0])
            sample["bracket_outcomes"] = f"<{len(sample['bracket_outcomes'])} brackets>"
            sample["bracket_end_prices"] = f"<{len(sample['bracket_end_prices'])} brackets>"
            for k, v in sample.items():
                print(f"    {k}: {v}")
        return

    # Batch upserts in chunks to stay under PostgREST payload limits
    batch_size = 100
    inserted = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        try:
            sb.table("auction_archive").upsert(
                chunk, on_conflict="handle,auction_slug"
            ).execute()
            inserted += len(chunk)
            print(f"  Upserted {inserted}/{len(rows)}...", end="\r")
        except Exception as e:
            print(f"\n  !! Batch starting at {i} failed: {e}")
            raise
    print(f"\n  Upserted {inserted} rows for {handle}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--handle", choices=list(HANDLES) + ["all"], default="all")
    args = ap.parse_args()

    url, key = _load_supabase_creds()
    sb = create_client(url, key)
    con = connect()

    handles = list(HANDLES) if args.handle == "all" else [args.handle]
    for handle in handles:
        meta = HANDLES[handle]
        print(f"\n=== {handle} ({meta['platform']}) ===")
        auctions = fetch_auctions_for_handle(con, meta)
        # Filter to closed auctions only (winning_bracket determined)
        with_winner = [a for a in auctions if a["winning_bracket"] is not None]
        print(f"  Parsed {len(auctions)} auctions; {len(with_winner)} have a winner")
        upsert_to_supabase(sb, handle, meta["platform"], with_winner, args.dry_run)


if __name__ == "__main__":
    main()
