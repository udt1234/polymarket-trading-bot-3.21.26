"""
Build canonical/posts_history/{handle}/{YYYY-MM}.parquet — for ML experiments.

Different from canonical/posts/:
  - NO auction-window trim (keeps all 5 years of OSINT data)
  - Adds `era` column for regime-aware ML (pre_acquisition, transition, current_x)
  - Uses identical row schema to canonical/posts so ML can join easily

Currently Elon-only (Trump has clean Supabase coverage already in canonical/posts).
Elon-specific because:
  - 5yr OSINT archive at OSINT/elon-tweets-archive/ holds historical scrape
  - Auction-window trim was throwing away Dec 2020 → May 2024 posts

Output schema matches canonical/posts/ + adds:
  era (str): 'pre_acquisition' | 'transition' | 'current_x'
"""
from __future__ import annotations

import json
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

ELON_OSINT_ARCHIVE = Path(r"C:/Users/darwi/OneDrive/Desktop/Claude Code/OSINT/elon-tweets-archive/elonmusk-ALL-2025-12-10.json")
ELON_OSINT_2ND = Path(r"C:/Users/darwi/OneDrive/Desktop/Claude Code/OSINT/elon-tweets-archive/elonmusk_tweets_2025-11-02T01-12-31-543Z.json")
ELON_SCWEET_DIR = Path(r"C:/Users/darwi/OneDrive/Desktop/Claude Code/OSINT/scweet/scweet_results")
ELON_XTRACKER = ROOT / "_DataMetricPulls" / "elon_posts_raw.parquet"
OUT_DIR = ROOT / "_DataMetricPulls" / "canonical" / "posts_history"
ET = ZoneInfo("America/New_York")

# 5-year cutoff for ML training
FIVE_YEAR_CUTOFF = pd.Timestamp("2020-12-10", tz="UTC")

# Era boundaries — Elon's behavioral regimes
ELON_ACQUISITION_DATE = pd.Timestamp("2022-10-27", tz="UTC")     # Twitter purchase closed
ELON_X_REBRAND_DATE = pd.Timestamp("2023-07-23", tz="UTC")       # rebranded Twitter to X


def strip_html(s) -> str:
    if not isinstance(s, str): return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def assign_era(ts: pd.Timestamp) -> str:
    if ts < ELON_ACQUISITION_DATE: return "pre_acquisition"
    if ts < ELON_X_REBRAND_DATE: return "transition"
    return "current_x"


def fetch_supabase_elon() -> pd.DataFrame:
    """Pull all elon_tweets from Supabase."""
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    rows, offset, PAGE = [], 0, 1000
    while True:
        r = sb.table("elon_tweets").select(
            "id,created_at,url,text,is_reply,is_retweet,is_quote,raw,source"
        ).range(offset, offset + PAGE - 1).execute()
        batch = r.data or []
        if not batch: break
        rows.extend(batch)
        if len(batch) < PAGE: break
        offset += PAGE
    df = pd.DataFrame(rows)
    if not len(df): return df
    df["ts_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
    return df.dropna(subset=["ts_utc"])


def load_osint() -> pd.DataFrame:
    """Both OSINT JSON files merged."""
    frames = []
    for f in [ELON_OSINT_ARCHIVE, ELON_OSINT_2ND]:
        if not f.exists(): continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if not data: continue
        df = pd.DataFrame(data)
        # File 1 has 'created_at' (Twitter format), File 2 has 'createdAt'
        ts_col = "created_at" if "created_at" in df.columns else "createdAt"
        df["ts_utc"] = pd.to_datetime(df[ts_col], format="%a %b %d %H:%M:%S %z %Y", errors="coerce")
        df = df.dropna(subset=["ts_utc"])
        df["ts_utc"] = df["ts_utc"].dt.tz_convert("UTC")
        # Normalize text + url columns
        if "text" not in df.columns and "tweet_text" in df.columns: df["text"] = df["tweet_text"]
        if "url" not in df.columns:
            df["url"] = df["id"].apply(lambda i: f"https://x.com/elonmusk/status/{i}")
        df["source_file"] = f.name
        frames.append(df[["id", "ts_utc", "text", "url", "source_file"]])
    if not frames: return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_xtracker() -> pd.DataFrame:
    if not ELON_XTRACKER.exists(): return pd.DataFrame()
    df = pd.read_parquet(ELON_XTRACKER)
    df["ts_utc"] = pd.to_datetime(df["dt_utc"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_utc"])
    # platformId is the real Twitter snowflake (vAI confirmed earlier)
    df["post_id"] = df["platformId"].astype(str)
    df["url"] = df["post_id"].apply(lambda i: f"https://twitter.com/elonmusk/status/{i}")
    return df[["post_id", "ts_utc", "content", "url"]].rename(columns={"content": "text"})


def load_scweet_types() -> dict:
    """Build tweet_id -> type map from any Scweet CSV in the directory."""
    if not ELON_SCWEET_DIR.exists(): return {}
    out = {}
    for csv in ELON_SCWEET_DIR.glob("elonmusk_*.csv"):
        try:
            sw = pd.read_csv(csv)
            for _, r in sw.iterrows():
                out[str(r["tweet_id"])] = r["type"]
        except Exception:
            continue
    return out


def build_elon_history() -> pd.DataFrame:
    print("[posts_history] loading sources for Elon...")
    sb = fetch_supabase_elon()
    print(f"  Supabase: {len(sb):,}")
    osint = load_osint()
    print(f"  OSINT (both files): {len(osint):,}")
    xt = load_xtracker()
    print(f"  xTracker: {len(xt):,}")
    scweet_types = load_scweet_types()
    print(f"  Scweet type-map keys: {len(scweet_types):,}")

    # Build unified frame — column-aligned
    frames = []
    if len(sb):
        sb_clean = pd.DataFrame({
            "post_id": sb["id"].astype(str),
            "ts_utc": sb["ts_utc"],
            "content_text": sb["text"].apply(strip_html),
            "is_reply_raw": sb["is_reply"].astype(bool),
            "is_retweet_raw": sb["is_retweet"].astype(bool),
            "is_quote_raw": sb["is_quote"].astype(bool),
            "url": sb["url"].astype(str),
            "source": "supabase_elon_tweets",
        })
        frames.append(sb_clean)
    if len(osint):
        osint_clean = pd.DataFrame({
            "post_id": osint["id"].astype(str),
            "ts_utc": osint["ts_utc"],
            "content_text": osint["text"].apply(strip_html),
            "is_reply_raw": False,  # OSINT filtered replies out
            "is_retweet_raw": False,
            "is_quote_raw": False,
            "url": osint["url"].astype(str),
            "source": "osint_archive",
        })
        frames.append(osint_clean)
    if len(xt):
        def _rt(s): return isinstance(s, str) and (s.startswith("RT @") or s.startswith("<p>RT @"))
        def _r(s):  return isinstance(s, str) and bool(re.match(r"^@\w+", strip_html(s)))
        xt_clean = pd.DataFrame({
            "post_id": xt["post_id"],
            "ts_utc": xt["ts_utc"],
            "content_text": xt["text"].apply(strip_html),
            "is_reply_raw": xt["text"].apply(_r),
            "is_retweet_raw": xt["text"].apply(_rt),
            "is_quote_raw": False,
            "url": xt["url"].astype(str),
            "source": "xtracker_elon_posts",
        })
        frames.append(xt_clean)

    merged = pd.concat(frames, ignore_index=True)
    # priority dedup: supabase > osint > xtracker (in concat order)
    merged = merged.drop_duplicates(subset=["post_id"], keep="first")

    # Apply Scweet enrichment (explicit type labels override heuristics)
    if scweet_types:
        n_overrides = 0
        for idx, row in merged.iterrows():
            t = scweet_types.get(str(row["post_id"]))
            if not t: continue
            new_rt = "retweet" in t.lower() or "repost" in t.lower()
            new_q = "quote" in t.lower()
            new_r = "reply" in t.lower()
            if (new_rt != row["is_retweet_raw"]) or (new_q != row["is_quote_raw"]) or (new_r != row["is_reply_raw"]):
                merged.at[idx, "is_retweet_raw"] = new_rt
                merged.at[idx, "is_quote_raw"] = new_q
                merged.at[idx, "is_reply_raw"] = new_r
                n_overrides += 1
        print(f"  Scweet overrides applied: {n_overrides}")

    # Apply 5yr cutoff for ML purposes (keep everything Dec 2020+)
    before = len(merged)
    merged = merged[merged["ts_utc"] >= FIVE_YEAR_CUTOFF]
    print(f"  After 5yr cutoff (>={FIVE_YEAR_CUTOFF.date()}): {len(merged):,} (dropped {before-len(merged):,} pre-2020 rows)")

    # Final schema with era + ts_et
    merged["ts_et"] = merged["ts_utc"].dt.tz_convert(ET)
    merged["era"] = merged["ts_utc"].apply(assign_era)
    merged["handle"] = "elonmusk"
    merged["is_reply"] = merged["is_reply_raw"]
    merged["is_repost"] = merged["is_retweet_raw"]
    merged["is_quote"] = merged["is_quote_raw"]
    merged["is_community_repost"] = False
    merged["content_html"] = merged["content_text"]  # OSINT/Scweet pass plain text
    merged["counts_for_auction"] = ~merged["is_reply"] & ~merged["is_community_repost"]

    final_cols = [
        "handle", "post_id", "ts_utc", "ts_et", "era",
        "content_text", "content_html",
        "is_reply", "is_repost", "is_quote", "is_community_repost",
        "counts_for_auction", "source", "url",
    ]
    return merged[final_cols].sort_values("ts_utc").reset_index(drop=True)


def write_partitions(df: pd.DataFrame, handle: str):
    out_dir = OUT_DIR / handle
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("*.parquet"):
        p.unlink()
    df = df.copy()
    df["_part"] = df["ts_utc"].dt.strftime("%Y-%m")
    for part, sub in df.groupby("_part"):
        sub.drop(columns=["_part"]).to_parquet(out_dir / f"{part}.parquet", index=False)
    print(f"  wrote {df['_part'].nunique()} monthly partitions to {out_dir.relative_to(ROOT)}")


def main():
    print("[posts_history] === Elon Musk 5-year history for ML ===")
    df = build_elon_history()
    print()
    print(f"Final: {len(df):,} rows from {df['ts_utc'].min()} to {df['ts_utc'].max()}")
    print(f"  source breakdown: {df['source'].value_counts().to_dict()}")
    print(f"  era breakdown: {df['era'].value_counts().to_dict()}")
    print(f"  per-year:")
    for year, n in df.groupby(df['ts_utc'].dt.year).size().items():
        print(f"    {year}: {n:,}")
    write_partitions(df, "elonmusk")
    print()
    print(f"DONE. Read via:")
    print(f"  pd.concat([pd.read_parquet(p) for p in Path('{OUT_DIR.relative_to(ROOT)}/elonmusk').glob('*.parquet')])")


if __name__ == "__main__":
    main()
