"""
Push canonical tables sample tabs to the Google Sheet.

Adds/replaces:
  Canonical_Posts_Trump        - 100 random Trump canonical posts
  Canonical_Posts_Elon         - 100 random Elon canonical posts
  Canonical_Auctions           - all 304 auctions (both handles)
  Canonical_Prices      - 500 hourly OHLC rows from one big auction
  Canonical_Schema             - schema doc for backtest reference
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "_DataMetricPulls" / "canonical"
SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
SUBJECT = "darwin@xagency.com"


def load_posts(handle: str) -> pd.DataFrame:
    files = sorted((CANON / "posts" / handle).glob("*.parquet"))
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)


def load_auctions() -> pd.DataFrame:
    files = sorted((CANON / "auctions").rglob("*.parquet"))
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)


def load_prices(handle: str) -> pd.DataFrame:
    files = sorted((CANON / "prices" / handle).glob("*.parquet"))
    return pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)


def df_to_rows(df: pd.DataFrame, max_rows: int = None) -> list[list[str]]:
    if max_rows and len(df) > max_rows:
        df = df.sample(n=max_rows, random_state=42)
    df = df.copy()
    for c in df.columns:
        df[c] = df[c].astype(str)
    return [list(df.columns)] + df.values.tolist()


def ensure_tab(sheets, sheet_id_map, title):
    if title in sheet_id_map:
        return sheet_id_map[title]
    res = sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def push(sheets, sheet_id, title, values, wide=None):
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
    for col in (wide or []):
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
            "properties": {"pixelSize": 300},
            "fields": "pixelSize",
        }})
    sheets.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": requests}).execute()


SCHEMA_DOC = [
    ["Canonical Data Layer — Schema Reference (2026-05-28)"],
    [""],
    ["Path", "Description", "Row count", "Date range"],
    ["canonical/posts/realDonaldTrump/YYYY-MM.parquet", "One row per Truth Social post", "32,837", "Feb 2022 → Apr 2026"],
    ["canonical/posts/elonmusk/YYYY-MM.parquet", "One row per X tweet", "9,105", "Oct 2025 → May 2026"],
    ["canonical/auctions/{handle}/YYYY-MM.parquet", "One row per resolved auction", "304", "mid-2024 → May 2026"],
    ["canonical/prices/{handle}/YYYY-MM.parquet", "Hourly OHLC per (auction, bucket)", "320k+", "mid-2024 → May 2026"],
    [""],
    ["POSTS columns"],
    ["handle", "realDonaldTrump | elonmusk"],
    ["post_id", "platform post ID"],
    ["ts_utc", "timestamp UTC (tz-aware)"],
    ["ts_et", "timestamp America/New_York (DST-correct)"],
    ["content_text", "HTML-stripped plain text"],
    ["content_html", "raw HTML/text"],
    ["is_reply", "true if reply"],
    ["is_repost", "true if reblog (Trump) or RT (Elon)"],
    ["is_quote", "true if quote post"],
    ["is_community_repost", "Elon-only; always False for Trump"],
    ["counts_for_auction", "true if post counts toward xTracker auction total"],
    ["source", "supabase_truth_social_posts | supabase_elon_tweets"],
    ["url", "live URL to the post"],
    [""],
    ["AUCTIONS columns"],
    ["handle, auction_slug, source_file", "identifiers"],
    ["duration_type", "2-day | 7-day | monthly | point | unknown"],
    ["window_days", "exact days from parsed filename"],
    ["start_utc, end_utc, start_et, end_et", "first → last trade timestamps"],
    ["n_trades, n_unique_traders, total_volume_usd", "auction activity"],
    ["n_buckets, all_buckets", "bracket count + list"],
    ["winning_bucket", "the bracket that resolved YES"],
    ["resolution_status", "resolved_yes | inferred_close_ge_95 | unresolved | ambiguous_N"],
    ["winner_open/close/peak/low_price", "OHLC of winning bucket"],
    ["confidence", "high (resolved_yes) | medium (inferred) | low (ambiguous/unresolved)"],
    [""],
    ["PRICES columns"],
    ["handle, auction_slug, condition_id, bucket", "identifiers"],
    ["hour_utc, hour_et", "hourly bucket timestamps"],
    ["open, high, low, close", "hourly OHLC of YES price for this bucket"],
    ["n_trades, vol_usd, vol_shares, unique_traders", "activity within the hour"],
    ["derived_spread", "high - low (proxy for bid-ask)"],
    ["derived_fill_minutes", "unique minutes with trades (out of 60)"],
    ["derived_depth_buy_low", "shares traded at price <= 0.05 (Spike entry tier)"],
    ["derived_depth_sell_high", "shares traded at price >= 0.30 (Spike exit tier)"],
    [""],
    ["BACKTEST RULES"],
    ["1.", "Read canonical/ only. Don't read raw _raw_imports/ or _posts_raw.parquet directly."],
    ["2.", "Always use ts_et when applying xTracker auction windows (Fri 12 PM ET → Fri 12 PM ET)."],
    ["3.", "Filter counts_for_auction=True on posts before counting toward auction."],
    ["4.", "Filter confidence in ('high','medium') on auctions to skip unresolved/ambiguous."],
]


def main() -> int:
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject=SUBJECT,
    )
    sheets = build("sheets", "v4", credentials=creds)
    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    print("[canonical] Canonical_Posts_Trump...")
    df = load_posts("realDonaldTrump")
    rows = df_to_rows(df.sample(100, random_state=42).sort_values("ts_utc"))
    sid = ensure_tab(sheets, sheet_id_map, "Canonical_Posts_Trump")
    push(sheets, sid, "Canonical_Posts_Trump", rows, wide=[4, 5, 11])

    print("[canonical] Canonical_Posts_Elon...")
    df = load_posts("elonmusk")
    rows = df_to_rows(df.sample(100, random_state=42).sort_values("ts_utc"))
    sid = ensure_tab(sheets, sheet_id_map, "Canonical_Posts_Elon")
    push(sheets, sid, "Canonical_Posts_Elon", rows, wide=[4, 5, 12])

    print("[canonical] Canonical_Auctions (all 304)...")
    df = load_auctions().sort_values(["handle", "start_utc"])
    rows = df_to_rows(df)
    sid = ensure_tab(sheets, sheet_id_map, "Canonical_Auctions")
    push(sheets, sid, "Canonical_Auctions", rows, wide=[1, 14, 21])

    print("[canonical] Canonical_Prices (one big auction)...")
    df = load_prices("elonmusk")
    # pick the auction with the most rows
    top_slug = df.groupby("auction_slug").size().idxmax()
    sub = df[df["auction_slug"] == top_slug].sort_values(["bucket", "hour_utc"]).head(500)
    rows = df_to_rows(sub)
    sid = ensure_tab(sheets, sheet_id_map, "Canonical_Prices")
    push(sheets, sid, "Canonical_Prices", rows, wide=[1])

    print("[canonical] Canonical_Schema...")
    sid = ensure_tab(sheets, sheet_id_map, "Canonical_Schema")
    push(sheets, sid, "Canonical_Schema", SCHEMA_DOC, wide=[0, 1])

    print(f"\nSheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
