"""
Push post samples to the canonical sheet.

Creates/replaces tabs:
  - Trump_Posts  (2 random posts per month, full canonical Trump range)
  - Elon_Posts   (2 random posts per month, full canonical/posts_history 5yr range)

Both source from canonical now (not raw parquet) so type tags / counts_for_auction
match what backtests see.
"""
from __future__ import annotations

import json
import re
import sys
from html import unescape
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
SUBJECT = "darwin@xagency.com"

CANON = ROOT / "_DataMetricPulls" / "canonical"


def clean(s: str) -> str:
    if not isinstance(s, str): return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def load_canonical_posts(handle: str, use_history: bool = False) -> pd.DataFrame:
    """Load from canonical/posts (auction-window trimmed) or canonical/posts_history (full 5yr)."""
    table = "posts_history" if use_history else "posts"
    files = sorted((CANON / table / handle).glob("*.parquet"))
    if not files: return pd.DataFrame()
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    return df.sort_values("ts_utc").reset_index(drop=True)


def sample_two_per_month(df: pd.DataFrame, handle: str) -> list[list[str]]:
    """For each (year, month), pick 2 random posts. Returns sheet rows."""
    if not len(df):
        return [["no data"]]
    df = df.copy()
    df["year_month"] = df["ts_utc"].dt.strftime("%Y-%m")

    samples = []
    for ym, sub in df.groupby("year_month"):
        n = min(2, len(sub))
        samples.append(sub.sample(n=n, random_state=42))
    out_df = pd.concat(samples, ignore_index=True).sort_values("ts_utc")

    # Build header — include `era` only if it exists (posts_history has it)
    has_era = "era" in out_df.columns
    header = ["year_month", "ts_utc", "ts_et", "post_id"]
    if has_era: header.append("era")
    header.extend([
        "is_reply", "is_repost", "is_quote", "is_community_repost",
        "counts_for_auction", "source", "content_text", "url",
    ])
    rows = [header]
    for _, r in out_df.iterrows():
        row = [
            r["year_month"],
            str(r["ts_utc"])[:19],
            str(r["ts_et"])[:19],
            str(r["post_id"]),
        ]
        if has_era: row.append(str(r.get("era", "")))
        row.extend([
            str(bool(r.get("is_reply"))),
            str(bool(r.get("is_repost"))),
            str(bool(r.get("is_quote"))),
            str(bool(r.get("is_community_repost"))),
            str(bool(r.get("counts_for_auction"))),
            str(r.get("source", "")),
            clean(str(r.get("content_text", "")))[:300],
            str(r.get("url", "")),
        ])
        rows.append(row)
    return rows


def ensure_tab(sheets, sheet_id_map: dict, title: str) -> int:
    if title in sheet_id_map:
        return sheet_id_map[title]
    res = sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return res["replies"][0]["addSheet"]["properties"]["sheetId"]


def push_tab(sheets, sheet_id: int, title: str, values: list[list[str]]):
    sheets.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"{title}!A:Z").execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"{title}!A1",
        valueInputOption="RAW", body={"values": values},
    ).execute()
    # Find content column index dynamically
    header = values[0] if values else []
    content_idx = header.index("content_text") if "content_text" in header else 11
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [
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
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": content_idx, "endIndex": content_idx + 1},
                "properties": {"pixelSize": 480}, "fields": "pixelSize",
            }},
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1,
                          "startColumnIndex": content_idx, "endColumnIndex": content_idx + 1},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }},
        ]},
    ).execute()


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject=SUBJECT,
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)

    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    # Trump from canonical/posts (auction-overlap trimmed)
    print("[push] Trump_Posts (2/month from canonical)...")
    trump_df = load_canonical_posts("realDonaldTrump", use_history=False)
    trump_rows = sample_two_per_month(trump_df, "realDonaldTrump")
    sid = ensure_tab(sheets, sheet_id_map, "Trump_Posts")
    push_tab(sheets, sid, "Trump_Posts", trump_rows)
    print(f"  wrote {len(trump_rows)-1} rows from {trump_df['ts_utc'].min().strftime('%Y-%m')} to {trump_df['ts_utc'].max().strftime('%Y-%m')}")

    # Elon from canonical/posts (auction-overlap, May 2024+)
    print("[push] Elon_Posts (2/month from canonical/posts)...")
    elon_df = load_canonical_posts("elonmusk", use_history=False)
    elon_rows = sample_two_per_month(elon_df, "elonmusk")
    sid = ensure_tab(sheets, sheet_id_map, "Elon_Posts")
    push_tab(sheets, sid, "Elon_Posts", elon_rows)
    print(f"  wrote {len(elon_rows)-1} rows from {elon_df['ts_utc'].min().strftime('%Y-%m')} to {elon_df['ts_utc'].max().strftime('%Y-%m')}")

    print(f"\nSheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")


if __name__ == "__main__":
    main()
