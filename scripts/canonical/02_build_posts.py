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
ELON_OSINT_ARCHIVE = Path(r"C:/Users/darwi/OneDrive/Desktop/Claude Code/OSINT/elon-tweets-archive/elonmusk-ALL-2025-12-10.json")
ELON_SCWEET_DIR = Path(r"C:/Users/darwi/OneDrive/Desktop/Claude Code/OSINT/scweet/scweet_results")
OUT_DIR = ROOT / "_DataMetricPulls" / "canonical" / "posts"
ET = ZoneInfo("America/New_York")
ELON_OSINT_CUTOFF = pd.Timestamp("2020-12-10", tz="UTC")  # last 5 years only


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


def fetch_osint_archive() -> pd.DataFrame:
    """Load OSINT scrape archive (real Twitter snowflake IDs + content)."""
    import json as _json
    if not ELON_OSINT_ARCHIVE.exists():
        return pd.DataFrame()
    data = _json.loads(ELON_OSINT_ARCHIVE.read_text(encoding="utf-8"))
    if not data:
        return pd.DataFrame()
    # parse Twitter date format: "Wed Dec 10 22:06:36 +0000 2025"
    df = pd.DataFrame(data)
    df["ts_utc"] = pd.to_datetime(df["created_at"], format="%a %b %d %H:%M:%S %z %Y", errors="coerce")
    df = df.dropna(subset=["ts_utc"])
    df["ts_utc"] = df["ts_utc"].dt.tz_convert("UTC")
    # Apply 5-year cutoff
    before = len(df)
    df = df[df["ts_utc"] >= ELON_OSINT_CUTOFF]
    print(f"  OSINT archive: {before:,} rows total, {len(df):,} after 5-year cutoff ({ELON_OSINT_CUTOFF.date()}+)")
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

    # Step 2b: OSINT archive (15-year history scrape, trimmed to 5yr)
    print("  reading OSINT archive...")
    osint_df = fetch_osint_archive()
    if len(osint_df):
        osint_out = pd.DataFrame({
            "handle": "elonmusk",
            "post_id": osint_df["id"].astype(str),  # real Twitter snowflake
            "ts_utc": osint_df["ts_utc"],
            "ts_et": osint_df["ts_utc"].dt.tz_convert(ET),
            "content_text": osint_df["text"].astype(str),
            "content_html": osint_df["text"].astype(str),
            "is_reply": False,  # OSINT scrape filtered out replies/RTs at collection time
            "is_repost": False,
            "is_quote": False,
            "is_community_repost": False,
            "source": "osint_scrape_2025-12-10",
            "_supabase_url": osint_df["url"].astype(str),  # real twitter.com URL
        })
    else:
        osint_out = pd.DataFrame()
    print(f"  OSINT rows ready: {len(osint_out):,}")

    # Step 3: merge - priority order Supabase > OSINT > xTracker (by recency of source)
    # All three use real Twitter snowflakes as post_id, so post_id dedup works.
    frames = []
    if len(sb_out): frames.append(sb_out)
    if len(osint_out): frames.append(osint_out)
    if len(xt_out): frames.append(xt_out)
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    # keep='first' = priority winner. Order above ensures Supabase wins, then OSINT, then xTracker.
    merged = merged.drop_duplicates(subset=["post_id"], keep="first")

    # Step 4: enrich type tags from Scweet CSVs (explicit Original/Retweet/Quote labels
    # vs vAI's regex heuristics). For any post_id present in a Scweet scrape, override
    # is_repost/is_quote based on Scweet's `type` column.
    scweet_csvs = sorted(ELON_SCWEET_DIR.glob("elonmusk_*.csv")) if ELON_SCWEET_DIR.exists() else []
    if scweet_csvs:
        scweet_rows = []
        for csv_path in scweet_csvs:
            try:
                sw = pd.read_csv(csv_path)
                scweet_rows.append(sw[["tweet_id", "type"]])
            except Exception:
                continue
        if scweet_rows:
            sw_all = pd.concat(scweet_rows, ignore_index=True).drop_duplicates(subset=["tweet_id"])
            sw_all["tweet_id"] = sw_all["tweet_id"].astype(str)
            type_map = dict(zip(sw_all["tweet_id"], sw_all["type"]))
            print(f"  Scweet type-enrichment available for {len(type_map):,} unique tweet_ids")
            n_overrides = 0
            for idx, row in merged.iterrows():
                t = type_map.get(str(row["post_id"]))
                if not t:
                    continue
                # Reset all three to derive from Scweet's explicit label
                new_repost = "retweet" in t.lower() or "repost" in t.lower()
                new_quote = "quote" in t.lower()
                new_reply = "reply" in t.lower()
                if (new_repost != row["is_repost"]) or (new_quote != row["is_quote"]) or (new_reply != row["is_reply"]):
                    n_overrides += 1
                    merged.at[idx, "is_repost"] = new_repost
                    merged.at[idx, "is_quote"] = new_quote
                    merged.at[idx, "is_reply"] = new_reply
            print(f"  Scweet overrides applied: {n_overrides:,}")
    else:
        print(f"  Scweet directory not found, skipping type enrichment")

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
