"""
Push source_inventory.csv to the canonical Google Sheet.

Reads _DataMetricPulls/canonical/_audit/source_inventory.csv and writes
to the sheet in 'Inventory' tab. Adds basic formatting + sort order.

Spreadsheet ID is hardcoded once (created 2026-05-28).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "_DataMetricPulls" / "canonical" / "_audit" / "source_inventory.csv"

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

    df = pd.read_csv(CSV_PATH)
    print(f"[push] loaded {len(df)} rows from {CSV_PATH.name}")

    # sort by n_rows desc so biggest sources are first
    df = df.sort_values("n_rows", ascending=False, na_position="last")
    df = df.fillna("")

    # convert all to str (sheet API wants strings); cap columns_json to 500 chars
    df["columns_json"] = df["columns_json"].astype(str).str.slice(0, 500)
    df["sha256"] = df["sha256"].astype(str).str.slice(0, 16)  # short hash for readability

    header = list(df.columns)
    values = [header] + df.astype(str).values.tolist()

    # write to Inventory tab (rename default Sheet1 to Inventory first)
    meta = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    first_sheet = meta["sheets"][0]["properties"]
    sheet_id = first_sheet["sheetId"]
    if first_sheet["title"] != "Inventory":
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "title": "Inventory"},
                "fields": "title",
            }}]},
        ).execute()
        print("[push] renamed Sheet1 -> Inventory")

    # clear + write
    sheets.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range="Inventory!A:Z"
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="Inventory!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()
    print(f"[push] wrote {len(values)} rows (incl header) to Inventory tab")

    # formatting: header bold + grey bg, freeze row 1, autosize-ish (set wider columns)
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
        # path column wider
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 480},
            "fields": "pixelSize",
        }},
        # columns_json wider
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 11, "endIndex": 12},
            "properties": {"pixelSize": 400},
            "fields": "pixelSize",
        }},
        # n_rows right-aligned + format
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 4, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "RIGHT",
                "numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
            }},
            "fields": "userEnteredFormat(horizontalAlignment,numberFormat)",
        }},
    ]
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": requests},
    ).execute()
    print("[push] applied formatting")

    print(f"\nSheet ready:")
    print(f"  https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
