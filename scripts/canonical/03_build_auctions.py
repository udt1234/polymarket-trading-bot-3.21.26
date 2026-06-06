"""
Phase 2 — Build canonical/auctions/{handle}/{YYYY-MM}.parquet

One row per auction. Derived from canonical/_raw_imports/whale_analysis/.

Output schema:
  handle               str  realDonaldTrump | elonmusk
  auction_slug         str  e.g. elon-musk-of-tweets-may-9-16
  source_file          str  whale_analysis filename
  duration_type        str  2-day | 7-day | monthly | point | unknown
  window_days          float
  start_utc            tz
  end_utc              tz
  start_et             tz
  end_et               tz
  n_trades             int
  n_unique_traders     int
  total_volume_usd     float
  n_buckets            int
  all_buckets          str   (comma-separated)
  winning_bucket       str
  resolution_status    str  resolved_yes | inferred_close_ge_95 | unresolved | ambiguous_N
  winner_open_price    float
  winner_close_price   float
  winner_peak_price    float
  winner_low_price     float
  winner_condition_id  str    PER-BUCKET conditionId for the WINNING bracket (the tradeable market that resolved YES)
  winner_asset_yes_token_id  str
  winner_asset_no_token_id   str
  bracket_condition_ids  str  JSON dict {bracket_label: condition_id} for ALL brackets in the auction
  bracket_yes_token_ids  str  JSON dict {bracket_label: yes_token_id}
  bracket_no_token_ids   str  JSON dict {bracket_label: no_token_id}
  title                str
  confidence           str   high | medium | low   (high = resolved_yes, medium = inferred, low = ambiguous/unresolved)

Partitioning: handle/YYYY-MM (by start_utc).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "_DataMetricPulls" / "canonical" / "_raw_imports" / "api_trades_v2"
OUT_DIR = ROOT / "_DataMetricPulls" / "canonical" / "auctions"
ET = ZoneInfo("America/New_York")

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_window(slug: str, fallback_year: int) -> tuple[str, float | None]:
    s = slug.lower()
    m_month = re.search(r"-([a-z]+)-(\d{4})$", s)
    if m_month and m_month.group(1) in MONTH_MAP:
        return ("monthly", 30.0)
    if re.search(r"-in-[a-z]+$", s):
        return ("monthly", 30.0)
    m_a = re.search(r"-([a-z]+)-(\d{1,2})-([a-z]+)-(\d{1,2})(?:[-.]|$)", s)
    if m_a:
        mon1 = MONTH_MAP.get(m_a.group(1)); mon2 = MONTH_MAP.get(m_a.group(3))
        if mon1 and mon2:
            try:
                y1 = fallback_year
                y2 = fallback_year if mon2 >= mon1 else fallback_year + 1
                d = (datetime(y2, mon2, int(m_a.group(4))) - datetime(y1, mon1, int(m_a.group(2)))).total_seconds() / 86400
                if 0.5 <= d <= 3.5: return ("2-day", d)
                if 5 <= d <= 9: return ("7-day", d)
                if 25 <= d <= 35: return ("monthly", d)
                return (f"other_{int(d)}d", d)
            except ValueError:
                pass
    m_b = re.search(r"-([a-z]+)-(\d{1,2})-(\d{1,2})(?:[-.]|$)", s)
    if m_b:
        mon = MONTH_MAP.get(m_b.group(1))
        d1, d2 = int(m_b.group(2)), int(m_b.group(3))
        if mon and d2 > d1:
            d = float(d2 - d1)
            if 0.5 <= d <= 3.5: return ("2-day", d)
            if 5 <= d <= 9: return ("7-day", d)
            return (f"other_{int(d)}d", d)
    if re.search(r"-on-([a-z]+)-(\d{1,2})(?:[-.]|$)", s):
        return ("point", 0.0)
    return ("unknown", None)


def winning_bucket(df: pd.DataFrame) -> tuple[str, str]:
    if "_bucket" not in df.columns:
        return ("", "no_bucket_col")
    # method 1: _outcome_resolved == ["1","0"]
    if "_outcome_resolved" in df.columns:
        winners = []
        for b, g in df.groupby("_bucket"):
            o = g["_outcome_resolved"].dropna()
            if len(o) == 0: continue
            try:
                parsed = json.loads(o.iloc[-1]) if isinstance(o.iloc[-1], str) else o.iloc[-1]
                if parsed == ["1", "0"] or parsed == [1, 0]:
                    winners.append(str(b))
            except Exception: continue
        if len(winners) == 1:
            return (winners[0], "resolved_yes")
        if len(winners) > 1:
            return (", ".join(winners), f"multi_winner_{len(winners)}")
    # method 2: bucket where last Yes trade >= 0.95
    if "price" in df.columns and "outcome" in df.columns:
        cands = []
        for b, g in df.groupby("_bucket"):
            g = g.sort_values("ts")
            yes = g[g["outcome"] == "Yes"]
            if len(yes) and yes.iloc[-1]["price"] >= 0.95:
                cands.append((str(b), float(yes.iloc[-1]["price"])))
        if len(cands) == 1:
            return (cands[0][0], "inferred_close_ge_95")
        if len(cands) > 1:
            best = max(cands, key=lambda x: x[1])
            return (best[0], f"ambiguous_{len(cands)}")
    return ("", "unresolved")


def detect_handle(slug: str) -> str:
    s = slug.lower()
    if "elon-musk" in s or "elonmusk" in s:
        return "elonmusk"
    if "trump" in s or "president-trump" in s:
        return "realDonaldTrump"
    return ""


def confidence_from_status(status: str) -> str:
    if status == "resolved_yes":
        return "high"
    if status == "inferred_close_ge_95":
        return "medium"
    return "low"


def build_auctions() -> pd.DataFrame:
    rows = []
    files = sorted(RAW_DIR.glob("*.parquet"))
    for f in files:
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) == 0:
            continue
        slug = str(df["eventSlug"].iloc[0]) if "eventSlug" in df.columns else f.name
        handle = detect_handle(slug)
        if not handle:
            continue  # skip non-tweet markets (btc, eth, fed, etc.)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"]).sort_values("ts")
        if len(df) == 0:
            continue
        first_utc = df["ts"].min()
        last_utc = df["ts"].max()
        first_et = first_utc.tz_convert(ET)
        last_et = last_utc.tz_convert(ET)
        dur_type, win_days = parse_window(slug, last_et.year)
        wb, status = winning_bucket(df)

        # Per-bucket Polymarket identifiers (each bracket = own market)
        bracket_cids = {}
        bracket_yes = {}
        bracket_no = {}
        if "_bucket" in df.columns and "conditionId" in df.columns:
            for b, g in df.groupby("_bucket"):
                b = str(b)
                bracket_cids[b] = str(g["conditionId"].iloc[0])
                yes = g[g["outcome"] == "Yes"]["asset"]
                no = g[g["outcome"] == "No"]["asset"]
                bracket_yes[b] = str(yes.iloc[0]) if len(yes) else ""
                bracket_no[b] = str(no.iloc[0]) if len(no) else ""

        # Winner OHLC: match canonical winning_bucket against raw _bucket
        # The Gamma backfill may have normalized winning_bucket label; try a
        # case-insensitive lookup so '<40' matches '<40', '40-49' matches '40-49 ', etc.
        win_open = win_close = win_peak = win_low = None
        winner_cid = winner_yes = winner_no = ""
        if wb and "," not in wb and "price" in df.columns:
            wb_norm = wb.strip().lower()
            raw_bucket_map = {str(b).strip().lower(): str(b) for b in df["_bucket"].dropna().unique()}
            raw_bucket = raw_bucket_map.get(wb_norm)
            if raw_bucket is not None:
                sub = df[df["_bucket"] == raw_bucket].sort_values("ts")
                if len(sub):
                    win_open = float(sub.iloc[0]["price"])
                    win_close = float(sub.iloc[-1]["price"])
                    win_peak = float(sub["price"].max())
                    win_low = float(sub["price"].min())
                    winner_cid = bracket_cids.get(raw_bucket, "")
                    winner_yes = bracket_yes.get(raw_bucket, "")
                    winner_no = bracket_no.get(raw_bucket, "")

        buckets = sorted(df["_bucket"].dropna().unique().tolist(), key=str) if "_bucket" in df.columns else []
        rows.append({
            "handle": handle,
            "auction_slug": slug,
            "source_file": f.name,
            "duration_type": dur_type,
            "window_days": win_days,
            "start_utc": first_utc,
            "end_utc": last_utc,
            "start_et": first_et,
            "end_et": last_et,
            "n_trades": len(df),
            "n_unique_traders": int(df["proxyWallet"].nunique()) if "proxyWallet" in df.columns else 0,
            "total_volume_usd": float(df["notional"].sum()) if "notional" in df.columns else 0.0,
            "n_buckets": len(buckets),
            "all_buckets": ", ".join(str(b) for b in buckets),
            "winning_bucket": wb,
            "resolution_status": status,
            "winner_open_price": win_open,
            "winner_close_price": win_close,
            "winner_peak_price": win_peak,
            "winner_low_price": win_low,
            "winner_condition_id": winner_cid,
            "winner_asset_yes_token_id": winner_yes,
            "winner_asset_no_token_id": winner_no,
            "bracket_condition_ids": json.dumps(bracket_cids),
            "bracket_yes_token_ids": json.dumps(bracket_yes),
            "bracket_no_token_ids": json.dumps(bracket_no),
            "title": str(df["title"].iloc[0])[:200] if "title" in df.columns else "",
            "confidence": confidence_from_status(status),
        })
    return pd.DataFrame(rows)


def write_partitions(df: pd.DataFrame):
    if OUT_DIR.exists():
        for p in OUT_DIR.rglob("*.parquet"):
            p.unlink()
    df = df.sort_values(["handle", "start_utc"])
    df["_part"] = df["start_utc"].dt.strftime("%Y-%m")
    n = 0
    for (handle, part), sub in df.groupby(["handle", "_part"]):
        out = OUT_DIR / handle / f"{part}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        sub.drop(columns=["_part"]).to_parquet(out, index=False)
        n += 1
        print(f"  wrote {out.relative_to(ROOT)}: {len(sub):,} auctions")
    return n


def main() -> int:
    print("[auctions] scanning whale_analysis raw imports...")
    df = build_auctions()
    print(f"[auctions] total auctions: {len(df):,}")
    print(f"  by handle: {df['handle'].value_counts().to_dict()}")
    print(f"  by duration: {df['duration_type'].value_counts().to_dict()}")
    print(f"  by confidence: {df['confidence'].value_counts().to_dict()}")
    write_partitions(df)
    print(f"[auctions] DONE. Output: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
