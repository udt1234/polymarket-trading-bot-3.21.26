"""Push the spike_ladder_vs_floor backtest result CSV to a Google Sheet tab."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "_DataMetricPulls" / "canonical" / "_backtests" / "spike_ladder_vs_floor.csv"
SPREADSHEET_ID = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA_KEY = Path.home() / ".claude" / "google-service-account.json"
SUBJECT = "darwin@xagency.com"


def main() -> int:
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject=SUBJECT,
    )
    sheets = build("sheets", "v4", credentials=creds)
    df = pd.read_csv(CSV).fillna("")
    df = df.sort_values("start_et")
    values = [list(df.columns)] + df.astype(str).values.tolist()

    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    title = "Backtest_Spike_Ladder"
    if title in sheet_id_map:
        sid = sheet_id_map[title]
    else:
        res = sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        sid = res["replies"][0]["addSheet"]["properties"]["sheetId"]

    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"{title}!A:Z"
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{title}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85},
                    "textFormat": {"bold": True},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }},
            {"updateSheetProperties": {
                "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 300},
                "fields": "pixelSize",
            }},
        ]},
    ).execute()
    print(f"Pushed {len(df)} rows to {title}")
    print(f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
