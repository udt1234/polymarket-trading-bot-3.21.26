"""
Push price/auction sample tabs to the canonical sheet.

Tabs created/replaced:
  - Trump_Auctions_Inventory  (every Trump auction with duration_type, brackets, winner, OHLC)
  - Elon_Auctions_Inventory   (every Elon auction)
  - Trump_Prices       (sample auction, every trade, ET+UTC)
  - Elon_Prices        (sample auction, every trade, ET+UTC)

Source: _DataMetricPulls/canonical/_raw_imports/api_trades_v2/

Fixes applied in this version:
  Bug 1: duration_type now uses the AUCTION window parsed from filename
         (not hours_in max, which includes early-bird trades before auction open)
  Bug 2: resolved_outcome now correctly parses '["1","0"]' as YES-WIN, '["0","1"]' as NO
  Bug 3: winning_bucket now finds the SINGLE bucket where _outcome_resolved == ["1","0"]
         (fallback: bucket whose final price >= 0.95 AND outcome=Yes)

All timestamps converted UTC -> America/New_York via zoneinfo (DST-correct).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
SUBJECT = "darwin@xagency.com"

RAW_TRADES_DIR = ROOT / "_DataMetricPulls" / "canonical" / "_raw_imports" / "api_trades_v2"
CANON_AUCTIONS = ROOT / "_DataMetricPulls" / "canonical" / "auctions"
ET = ZoneInfo("America/New_York")


def _load_canonical_auction_meta() -> dict[str, dict]:
    """Load auction_slug -> {title, duration_type} map from canonical/auctions/."""
    meta = {}
    for handle in ["elonmusk", "realDonaldTrump"]:
        for p in (CANON_AUCTIONS / handle).glob("*.parquet"):
            df = pd.read_parquet(p, columns=["auction_slug", "title", "duration_type"])
            for _, r in df.iterrows():
                meta[str(r["auction_slug"])] = {
                    "title": str(r["title"]),
                    "duration_type": str(r["duration_type"]),
                }
    return meta

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def parse_window_from_slug(slug: str, fallback_year: int) -> tuple[str, float | None]:
    """
    Parse an auction window from the eventSlug or filename, returning
    (duration_type, window_days). Window_days is exact when parseable.

    Examples:
      'donald-trump-of-truth-social-posts-april-10-april-17' -> (7-day, 7.0)
      'elon-musk-of-tweets-may-9-16'                          -> (7-day, 7.0)
      'elon-musk-of-tweets-april-2026'                        -> (monthly, 30.0)
      'donald-trump-of-truth-social-posts-feb-28-mar-7'       -> (7-day, 7.0)
      'elon-musk-of-tweets-may-4-may-6'                       -> (2-day, 2.0)
      'bitcoin-price-on-april-25'                             -> (point, 0)
    """
    s = slug.lower()

    # monthly: ends with '-<month>-YYYY'
    m_month = re.search(r"-([a-z]+)-(\d{4})$", s)
    if m_month and m_month.group(1) in MONTH_MAP:
        return ("monthly", 30.0)

    # 'in-<month>' (e.g. elon-musk-of-tweets-in-september)
    if re.search(r"-in-[a-z]+$", s):
        return ("monthly", 30.0)

    # Pattern A: 'mon1-d1-mon2-d2'  e.g. april-10-april-17 OR feb-28-mar-7
    m_a = re.search(r"-([a-z]+)-(\d{1,2})-([a-z]+)-(\d{1,2})(?:[-.]|$)", s)
    if m_a:
        mon1 = MONTH_MAP.get(m_a.group(1))
        d1 = int(m_a.group(2))
        mon2 = MONTH_MAP.get(m_a.group(3))
        d2 = int(m_a.group(4))
        if mon1 and mon2:
            try:
                y1 = fallback_year
                y2 = fallback_year if mon2 >= mon1 else fallback_year + 1
                start = datetime(y1, mon1, d1)
                end = datetime(y2, mon2, d2)
                days = (end - start).total_seconds() / 86400
                if 0.5 <= days <= 3.5: return ("2-day", days)
                if 5 <= days <= 9: return ("7-day", days)
                if 25 <= days <= 35: return ("monthly", days)
                return (f"other_{int(days)}d", days)
            except ValueError:
                pass

    # Pattern B: 'mon-d1-d2' compact same-month  e.g. may-9-16 or mar-7-14
    m_b = re.search(r"-([a-z]+)-(\d{1,2})-(\d{1,2})(?:[-.]|$)", s)
    if m_b:
        mon = MONTH_MAP.get(m_b.group(1))
        d1 = int(m_b.group(2))
        d2 = int(m_b.group(3))
        if mon and d2 > d1:
            days = d2 - d1
            if 0.5 <= days <= 3.5: return ("2-day", float(days))
            if 5 <= days <= 9: return ("7-day", float(days))
            return (f"other_{days}d", float(days))

    # Pattern C: 'mon-d-mon-d' but parses as 'on-mon-d' (single-day point market)
    m_c = re.search(r"-on-([a-z]+)-(\d{1,2})(?:[-.]|$)", s)
    if m_c and MONTH_MAP.get(m_c.group(1)):
        return ("point", 0.0)

    return ("unknown", None)


def winning_bucket_from_data(df: pd.DataFrame) -> tuple[str, str]:
    """
    Returns (winning_bucket, resolution_status).
    Logic:
      1) If '_outcome_resolved' exists and any bucket has ["1","0"], that bucket is the winner.
      2) Otherwise: bucket whose final close >= 0.95 AND outcome=Yes (or final close <= 0.05 AND outcome=No).
      3) Otherwise: 'unresolved'
    """
    if "_bucket" not in df.columns:
        return ("", "no_bucket_col")

    # Method 1: _outcome_resolved == ["1","0"]
    if "_outcome_resolved" in df.columns:
        winners = []
        for b, g in df.groupby("_bucket"):
            ores = g["_outcome_resolved"].dropna()
            if len(ores) == 0:
                continue
            val = ores.iloc[-1]
            try:
                parsed = json.loads(val) if isinstance(val, str) else val
                if parsed == ["1", "0"] or parsed == [1, 0]:
                    winners.append(str(b))
            except Exception:
                continue
        if len(winners) == 1:
            return (winners[0], "resolved_yes")
        if len(winners) > 1:
            return (", ".join(winners), f"multi_winner_{len(winners)}")

    # Method 2: bucket where last YES trade closes at >= 0.95
    if "price" in df.columns and "outcome" in df.columns and "ts" in df.columns:
        candidates = []
        for b, g in df.groupby("_bucket"):
            g = g.sort_values("ts")
            yes = g[g["outcome"] == "Yes"]
            if len(yes) == 0:
                continue
            last_yes_price = yes.iloc[-1]["price"]
            if last_yes_price >= 0.95:
                candidates.append((str(b), float(last_yes_price)))
        if len(candidates) == 1:
            return (candidates[0][0], "inferred_close_ge_95")
        if len(candidates) > 1:
            best = max(candidates, key=lambda x: x[1])
            return (best[0], f"ambiguous_{len(candidates)}")

    return ("", "unresolved")


def inventory(handle_filter: str) -> list[list[str]]:
    files = sorted(RAW_TRADES_DIR.glob("*.parquet"))
    rows = [[
        "file",
        "auction_slug",
        "duration_type",
        "window_days",
        "n_trades",
        "n_unique_traders",
        "first_trade_et",
        "last_trade_et",
        "trade_span_hours",
        "unique_buckets",
        "all_buckets",
        "winning_bucket",
        "resolution_status",
        "winner_close_price",
        "winner_open_price",
        "winner_peak_price",
        "winner_low_price",
        "total_volume_usd",
        "title",
        "condition_id",
    ]]
    for f in files:
        name = f.name.lower()
        if handle_filter == "trump":
            if not ("trump" in name or "president-trump" in name):
                continue
        elif handle_filter == "elon":
            if "elon-musk" not in name:
                continue
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if len(df) == 0:
            continue
        df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts"]).sort_values("ts")
        if len(df) == 0:
            continue

        first_et = df["ts"].min().tz_convert(ET)
        last_et = df["ts"].max().tz_convert(ET)
        trade_span_h = (df["ts"].max() - df["ts"].min()).total_seconds() / 3600.0

        slug = str(df["eventSlug"].iloc[0]) if "eventSlug" in df.columns else f.name
        # Use the year of LAST trade as fallback year for parsing
        fallback_year = last_et.year
        duration_type, window_days = parse_window_from_slug(slug, fallback_year)

        winning_bucket, resolution_status = winning_bucket_from_data(df)

        # OHLC of winning bucket
        win_open = win_close = win_peak = win_low = ""
        if winning_bucket and "," not in winning_bucket and "price" in df.columns:
            sub = df[df["_bucket"] == winning_bucket].sort_values("ts")
            if len(sub):
                win_open = f"{sub.iloc[0]['price']:.4f}"
                win_close = f"{sub.iloc[-1]['price']:.4f}"
                win_peak = f"{sub['price'].max():.4f}"
                win_low = f"{sub['price'].min():.4f}"

        buckets = []
        if "_bucket" in df.columns:
            buckets = sorted(df["_bucket"].dropna().unique().tolist(), key=str)

        total_vol = df["notional"].sum() if "notional" in df.columns else 0
        title = str(df["title"].iloc[0])[:100] if "title" in df.columns else ""
        cid = (str(df["conditionId"].iloc[0])[:20] + "...") if "conditionId" in df.columns else ""

        rows.append([
            f.name,
            slug,
            duration_type,
            f"{window_days:.1f}" if window_days is not None else "",
            str(len(df)),
            str(df["proxyWallet"].nunique() if "proxyWallet" in df.columns else 0),
            first_et.strftime("%Y-%m-%d %H:%M ET"),
            last_et.strftime("%Y-%m-%d %H:%M ET"),
            f"{trade_span_h:.1f}",
            str(len(buckets)),
            ", ".join(str(b) for b in buckets)[:200],
            winning_bucket,
            resolution_status,
            win_close,
            win_open,
            win_peak,
            win_low,
            f"{total_vol:.0f}",
            title,
            cid,
        ])
    return rows


def sample_auction(handle_filter: str, max_trades: int = 500) -> tuple[str, list[list[str]]]:
    files = sorted(RAW_TRADES_DIR.glob("*.parquet"))
    candidates = []
    for f in files:
        name = f.name.lower()
        if handle_filter == "trump":
            if not ("trump" in name or "president-trump" in name):
                continue
        elif handle_filter == "elon":
            if "elon-musk" not in name:
                continue
        try:
            n = len(pd.read_parquet(f, columns=["ts"]))
        except Exception:
            continue
        candidates.append((n, f))
    if not candidates:
        return ("", [["no auctions found"]])
    candidates.sort(reverse=True)
    _, pick = candidates[0]
    df = pd.read_parquet(pick)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    df = df.sort_values("ts")

    winning_bucket, _status = winning_bucket_from_data(df)

    if len(df) > max_trades:
        idx = list(range(0, len(df), len(df) // max_trades))[:max_trades]
        df = df.iloc[idx]

    # Look up parent auction title + duration_type from canonical
    auction_slug = pick.stem  # api_trades_v2/{slug}.parquet
    canonical_meta = _load_canonical_auction_meta()
    auction_meta = canonical_meta.get(auction_slug, {})
    auction_title = auction_meta.get("title", "")
    auction_duration = auction_meta.get("duration_type", "")

    rows = [[
        "auction_slug",
        "auction_title",
        "duration_type",
        "ts_et",
        "ts_utc",
        "hours_in",
        "side",
        "outcome",
        "bucket",
        "is_winning_bucket",
        "bracket_market_title",
        "price",
        "size_shares",
        "notional_usd",
        "trader_name",
        "trader_wallet",
        "tx_hash",
    ]]
    for _, r in df.iterrows():
        ts_utc = r["ts"]
        ts_et = ts_utc.tz_convert(ET) if pd.notna(ts_utc) else None
        bucket = str(r.get("_bucket", ""))
        is_winner = "YES" if (winning_bucket and bucket == winning_bucket) else ""
        rows.append([
            auction_slug,
            auction_title,
            auction_duration,
            ts_et.strftime("%Y-%m-%d %H:%M:%S ET") if ts_et else "",
            ts_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if pd.notna(ts_utc) else "",
            f"{r.get('hours_in', 0):.2f}",
            str(r.get("side", "")),
            str(r.get("outcome", "")),
            bucket,
            is_winner,
            str(r.get("title", "")),
            f"{r.get('price', 0):.4f}",
            f"{r.get('size', 0):.2f}",
            f"{r.get('notional', 0):.2f}",
            str(r.get("name", ""))[:30],
            str(r.get("proxyWallet", ""))[:20] + "...",
            str(r.get("transactionHash", ""))[:20] + "...",
        ])
    return (pick.name, rows)


def ensure_tab(sheets, sheet_id_map: dict, title: str) -> int:
    if title in sheet_id_map:
        return sheet_id_map[title]
    res = sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def push_tab(sheets, sheet_id: int, title: str, values: list[list[str]], wide_cols: list[int] = None):
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{title}!A:Z"
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{title}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    requests = [
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85},
                "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]
    for col_idx in (wide_cols or []):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col_idx, "endIndex": col_idx + 1},
            "properties": {"pixelSize": 250},
            "fields": "pixelSize",
        }})
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()


def main() -> int:
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject=SUBJECT,
    )
    sheets = build("sheets", "v4", credentials=creds)
    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    for handle, title in [("trump", "Trump_Auctions_Inventory"), ("elon", "Elon_Auctions_Inventory")]:
        print(f"[push] building {title}...")
        rows = inventory(handle)
        sid = ensure_tab(sheets, sheet_id_map, title)
        push_tab(sheets, sid, title, rows, wide_cols=[0, 1, 10, 18])
        print(f"[push] wrote {len(rows)-1} auctions to {title}")
        # quick sanity print
        if len(rows) > 1:
            from collections import Counter
            dur_counts = Counter(r[2] for r in rows[1:])
            print(f"        duration_type counts: {dict(dur_counts)}")
            res_counts = Counter(r[12] for r in rows[1:])
            print(f"        resolution_status counts: {dict(res_counts)}")

    for handle, title in [("trump", "Trump_Prices"), ("elon", "Elon_Prices")]:
        print(f"[push] building {title}...")
        fname, rows = sample_auction(handle, max_trades=500)
        sid = ensure_tab(sheets, sheet_id_map, title)
        push_tab(sheets, sid, title, rows, wide_cols=[13])
        print(f"[push] wrote {len(rows)-1} trades from {fname} to {title}")

    print(f"\nSheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
