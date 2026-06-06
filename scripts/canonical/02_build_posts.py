"""
Phase 2 — Build canonical/posts/{handle}/{YYYY-MM}.parquet

INPUTS
  Trump:
    Supabase truth_social_posts (32,880 rows; primary truth, Feb 2022 -> Apr 2026)
    -> dumped to _DataMetricPulls/trump_posts_raw.parquet
  Elon (MERGED, primary key = createdAt rounded to second):
    Supabase elon_tweets (1,282 rows, May 2-29 2026)
       - real Twitter snowflake IDs + URLs, proper is_reply/is_retweet/is_quote
    _DataMetricPulls/elon_posts_raw.parquet (9,105 rows, Oct 2025 -> May 2026)
       - xTracker dump with full content history
       - WARNING: ids are xTracker CUIDs, not Twitter snowflakes (URLs won't link)

OUTPUT SCHEMA
  handle              str   realDonaldTrump | elonmusk
  post_id             str   platform post id (snowflake for Supabase rows, CUID for xTracker rows)
  ts_utc              tz    timestamp UTC
  ts_et               tz    timestamp America/New_York (DST-correct)
  content_text        str   plain text (HTML stripped, RT prefix preserved)
  content_html        str   raw HTML/text
  is_reply            bool  true if reply  (Trump: from supabase col; Elon: prefer supabase, fallback content-detect)
  is_repost           bool  true if reblog (Trump) or RT (Elon)
  is_quote            bool  true if quote post (Elon supabase only)
  is_community_repost bool  Elon-only; True if content marker says so (always False for Trump)
  counts_for_auction  bool  xTracker rule:
                              Trump: NOT pure reply
                              Elon:  NOT pure reply AND NOT community repost
  source              str   supabase_truth_social_posts | supabase_elon_tweets | xtracker_elon_posts
  url                 str   live URL (broken for xtracker CUID rows)

Partitioning: handle/YYYY-MM
"""
from __future__ import annotations

import os
import re
import sys
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
TRUMP_RAW = ROOT / "_DataMetricPulls" / "trump_posts_raw.parquet"
ELON_XTRACKER = ROOT / "_DataMetricPulls" / "elon_posts_raw.parquet"
OUT_DIR = ROOT / "_DataMetricPulls" / "canonical" / "posts"
ET = ZoneInfo("America/New_York")


def strip_html(s) -> str:
    if not isinstance(s, str):
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ---------- TRUMP ----------
def build_trump() -> pd.DataFrame:
    df = pd.read_parquet(TRUMP_RAW)
    df["ts_utc"] = pd.to_datetime(df["dt_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_utc"])

    out = pd.DataFrame({
        "handle": "realDonaldTrump",
        "post_id": df["id"].astype(str),
        "ts_utc": df["ts_utc"],
        "ts_et": df["ts_utc"].dt.tz_convert(ET),
        "content_text": df["content"].apply(strip_html),
        "content_html": df["content"].astype(str),
        "is_reply": df["is_reply"].astype(bool),  # actual Supabase col, validated 0 for Trump
        "is_repost": df["is_reblog"].astype(bool),
        "is_quote": False,
        "is_community_repost": False,
        "source": "supabase_truth_social_posts",
    })
    # Trump xTracker rule: replies don't count (but Trump has 0 replies, so all count)
    out["counts_for_auction"] = ~out["is_reply"]
    out["url"] = out["post_id"].apply(lambda pid: f"https://truthsocial.com/@realDonaldTrump/posts/{pid}")
    return out


# ---------- ELON ----------
def fetch_supabase_elon() -> pd.DataFrame:
    """Pull all elon_tweets from Supabase (~1,282 rows)."""
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    rows = []
    offset = 0
    PAGE = 1000
    while True:
        r = sb.table("elon_tweets").select(
            "id,created_at,url,text,is_reply,is_retweet,is_quote,raw,source"
        ).range(offset, offset + PAGE - 1).execute()
        batch = r.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    df = pd.DataFrame(rows)
    if len(df) == 0:
        return df
    df["ts_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_utc"])
    return df


def build_elon() -> pd.DataFrame:
    # Step 1: Supabase rows (primary truth where available)
    print("  fetching Supabase elon_tweets...")
    sb_df = fetch_supabase_elon()
    print(f"  Supabase rows: {len(sb_df):,}")

    # supabase rows: `id` IS the Twitter snowflake AND `url` is pre-built (use it)
    sb_out = pd.DataFrame({
        "handle": "elonmusk",
        "post_id": sb_df["id"].astype(str),  # Twitter snowflake
        "ts_utc": sb_df["ts_utc"],
        "ts_et": sb_df["ts_utc"].dt.tz_convert(ET),
        "content_text": sb_df["text"].apply(strip_html),
        "content_html": sb_df["text"].astype(str),
        "is_reply": sb_df["is_reply"].astype(bool),
        "is_repost": sb_df["is_retweet"].astype(bool),
        "is_quote": sb_df["is_quote"].astype(bool),
        "is_community_repost": False,
        "source": "supabase_elon_tweets",
        "_supabase_url": sb_df["url"].astype(str),  # use this directly downstream
    }) if len(sb_df) else pd.DataFrame()

    # Step 2: xTracker rows (historical, fill gaps)
    print("  reading xTracker elon_posts_raw.parquet...")
    xt_df = pd.read_parquet(ELON_XTRACKER)
    xt_df["ts_utc"] = pd.to_datetime(xt_df["dt_utc"], utc=True, errors="coerce")
    xt_df = xt_df.dropna(subset=["ts_utc"])
    print(f"  xTracker rows: {len(xt_df):,}")

    # detect retweets + replies from content
    def _is_rt(s):
        s = str(s) if s is not None else ""
        return s.startswith("RT @") or s.startswith("<p>RT @")
    def _is_reply_text(s):
        s = strip_html(str(s) if s is not None else "")
        return bool(re.match(r"^@\w+", s))
    def _is_community(s):
        s = str(s) if s is not None else ""
        return "community" in s.lower() and "repost" in s.lower()

    # xtracker rows: `id` is xtracker CUID (broken for URLs), but `platformId` IS
    # the real Twitter snowflake. Use platformId as post_id so URLs link.
    xt_out = pd.DataFrame({
        "handle": "elonmusk",
        "post_id": xt_df["platformId"].astype(str),  # real Twitter snowflake (was using broken CUID before)
        "ts_utc": xt_df["ts_utc"],
        "ts_et": xt_df["ts_utc"].dt.tz_convert(ET),
        "content_text": xt_df["content"].apply(strip_html),
        "content_html": xt_df["content"].astype(str),
        "is_reply": xt_df["content"].apply(_is_reply_text),
        "is_repost": xt_df["content"].apply(_is_rt),
        "is_quote": False,
        "is_community_repost": xt_df["content"].apply(_is_community),
        "source": "xtracker_elon_posts",
        "_supabase_url": "",  # not from supabase
    })

    # Step 3: merge - prefer Supabase for overlapping post_ids
    # Both Supabase and xTracker use the Twitter snowflake as post_id (xTracker
    # via platformId), so we can dedupe on post_id directly. Supabase wins ties.
    if len(sb_out):
        sb_ids = set(sb_out["post_id"])
        xt_out = xt_out[~xt_out["post_id"].isin(sb_ids)]
        merged = pd.concat([sb_out, xt_out], ignore_index=True)
        # final safety: kill any remaining duplicates within merged
        merged = merged.drop_duplicates(subset=["post_id"], keep="first")
    else:
        merged = xt_out.drop_duplicates(subset=["post_id"], keep="first")

    print(f"  merged rows: {len(merged):,} (Supabase {len(sb_out):,} + xTracker after dedup {len(xt_out):,})")

    # Elon xTracker rule: replies and community reposts don't count
    merged["counts_for_auction"] = ~merged["is_reply"] & ~merged["is_community_repost"]
    # URL construction:
    #   supabase rows: use the pre-built `url` field directly (real twitter.com URL)
    #   xtracker rows: construct from post_id (which is now platformId = real snowflake)
    def _make_url(row):
        if row["source"] == "supabase_elon_tweets" and row.get("_supabase_url"):
            return row["_supabase_url"]
        return f"https://twitter.com/elonmusk/status/{row['post_id']}"
    merged["url"] = merged.apply(_make_url, axis=1)
    merged = merged.drop(columns=["_supabase_url"])
    return merged


def _auction_start_min(handle: str) -> pd.Timestamp | None:
    """Earliest auction start_utc for this handle. None if no auctions yet."""
    auc_dir = ROOT / "_DataMetricPulls" / "canonical" / "auctions" / handle
    files = sorted(auc_dir.glob("*.parquet"))
    if not files:
        return None
    starts = []
    for f in files:
        df = pd.read_parquet(f, columns=["start_utc"])
        starts.append(pd.to_datetime(df["start_utc"], utc=True).min())
    return min(starts) if starts else None


def write_partitions(df: pd.DataFrame, handle: str):
    # Trim to auction coverage window: drop posts before the first auction for
    # this handle. Raw parquets remain untouched for any historical baseline work.
    floor = _auction_start_min(handle)
    if floor is not None:
        n_before = len(df)
        df = df[df["ts_utc"] >= floor]
        print(f"  trimmed to auction coverage: kept {len(df):,}/{n_before:,} (floor={floor})")
    out_dir = OUT_DIR / handle
    out_dir.mkdir(parents=True, exist_ok=True)
    # clear old partitions
    for p in out_dir.glob("*.parquet"):
        p.unlink()
    df = df.sort_values("ts_utc")
    df["_partition"] = df["ts_utc"].dt.strftime("%Y-%m")
    n = 0
    for partition, sub in df.groupby("_partition"):
        sub = sub.drop(columns=["_partition"])
        out_path = out_dir / f"{partition}.parquet"
        sub.to_parquet(out_path, index=False)
        n += 1
    print(f"  wrote {n} partitions to {out_dir.relative_to(ROOT)}")


def main() -> int:
    print("[posts] Trump...")
    trump = build_trump()
    print(f"  total: {len(trump):,}, counts_for_auction True: {trump['counts_for_auction'].sum():,}")
    print(f"  is_reply: {trump['is_reply'].sum():,}, is_repost: {trump['is_repost'].sum():,}")
    write_partitions(trump, "realDonaldTrump")

    print()
    print("[posts] Elon...")
    elon = build_elon()
    print(f"  total: {len(elon):,}, counts_for_auction True: {elon['counts_for_auction'].sum():,}")
    print(f"  is_reply: {elon['is_reply'].sum():,}, is_repost: {elon['is_repost'].sum():,}, is_quote: {elon['is_quote'].sum():,}, is_community_repost: {elon['is_community_repost'].sum():,}")
    print(f"  source breakdown: {elon['source'].value_counts().to_dict()}")
    write_partitions(elon, "elonmusk")

    print()
    print(f"[posts] DONE. Output: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
