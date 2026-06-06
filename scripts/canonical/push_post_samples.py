"""
Push 100 random Trump posts + 100 random Elon posts to the canonical sheet.

Creates/replaces tabs:
  - Trump_Posts_Sample  (100 random rows from trump_posts_raw.parquet)
  - Elon_Posts_Sample   (100 random rows from elon_posts_raw.parquet)
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

TRUMP_PARQUET = ROOT / "_DataMetricPulls" / "trump_posts_raw.parquet"
ELON_PARQUET = ROOT / "_DataMetricPulls" / "elon_posts_raw.parquet"


def clean_html(s: str) -> str:
    if not isinstance(s, str):
        return ""
    # strip HTML tags
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def prep_trump(n: int = 100) -> list[list[str]]:
    df = pd.read_parquet(TRUMP_PARQUET)
    sample = df.sample(n=min(n, len(df)), random_state=42).sort_values("dt_utc")
    rows = [["dt_utc", "id", "content", "is_reply", "is_reblog", "metrics_likes", "metrics_reblogs", "metrics_replies", "url"]]
    for _, r in sample.iterrows():
        m = r.get("metrics") or {}
        rows.append([
            str(r["dt_utc"])[:19],
            str(r["id"]),
            clean_html(str(r.get("content", "")))[:500],
            str(bool(r.get("is_reply"))),
            str(bool(r.get("is_reblog"))),
            str(m.get("favourites_count", "")) if isinstance(m, dict) else "",
            str(m.get("reblogs_count", "")) if isinstance(m, dict) else "",
            str(m.get("replies_count", "")) if isinstance(m, dict) else "",
            f"https://truthsocial.com/@realDonaldTrump/posts/{r['id']}",
        ])
    return rows


def prep_elon(n: int = 100) -> list[list[str]]:
    df = pd.read_parquet(ELON_PARQUET)
    sample = df.sample(n=min(n, len(df)), random_state=42).sort_values("dt_utc")
    rows = [["dt_utc", "id", "content", "platformId", "metrics_json", "url"]]
    for _, r in sample.iterrows():
        m = r.get("metrics")
        m_str = json.dumps(m)[:200] if isinstance(m, dict) else str(m)[:200]
        rows.append([
            str(r["dt_utc"])[:19],
            str(r["id"]),
            clean_html(str(r.get("content", "")))[:500],
            str(r.get("platformId", "")),
            m_str,
            f"https://twitter.com/elonmusk/status/{r['id']}",
        ])
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
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{title}!A:Z"
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{title}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    # format
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
            # widen content column (col C = index 2)
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 600},
                "fields": "pixelSize",
            }},
            # wrap text in content
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }},
        ]},
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

    for title, prep in [("Trump_Posts_Sample", prep_trump), ("Elon_Posts_Sample", prep_elon)]:
        print(f"[push] preparing {title}...")
        values = prep(100)
        sid = ensure_tab(sheets, sheet_id_map, title)
        push_tab(sheets, sid, title, values)
        print(f"[push] wrote {len(values)-1} rows to {title}")

    print(f"\nSheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
