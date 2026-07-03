"""Delete Posts_History tab and add a description banner row at top of every other tab.

Inserts a NEW row 1 with a one-line description. Existing data shifts down by 1 row.
Banner formatted: dark grey background, gold text, bold, merged across used columns.

Re-runnable: if the existing row 1 already starts with 'ℹ' (the banner marker),
it's overwritten instead of inserting a new row.
"""
from __future__ import annotations

from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"
MARKER = "ℹ "

DESCRIPTIONS = {
    "Inventory": "Historical inventory of 113 pre-canonical data sources (pre-2026-05-28). Frozen reference. Backtests do NOT read from these paths anymore.",
    "Elon_Posts": "2 random Elon posts per (year, month) from canonical/posts/elonmusk. Spot-check the backtest data. Range: May 2024 → present.",
    "Elon_Auctions_Inventory": "All 244 Elon tweet-count auctions in canonical — bracket lists, winners, confidence, OHLC of winning bracket.",
    "Elon_Prices": "Sample of every trade for one large Elon auction. Each row = one trade with bucket, price, side, hours_in.",
    "Canonical_Posts_Elon": "100 random posts from canonical/posts/elonmusk (the backtest layer). Used to verify is_reply/is_repost/counts_for_auction logic.",
    "Trump_Posts": "2 random Trump posts per (year, month) from canonical/posts/realDonaldTrump. Range: Aug 2024 → present.",
    "Trump_Auctions_Inventory": "All 56 Trump tweet-count auctions in canonical — duration_type, winning_bucket, OHLC.",
    "Trump_Prices": "Sample of every trade for one large Trump auction.",
    "Canonical_Posts_Trump": "100 random posts from canonical/posts/realDonaldTrump.",
    "Canonical_Auctions": "All 300 auctions (244 Elon + 56 Trump) combined. Master backtest universe.",
    "Canonical_Prices": "500 hourly OHLC rows from one Elon auction. Shows per-bucket condition_id + derived spread/depth proxies.",
    "Canonical_Schema": "Schema reference doc — column meanings for posts/auctions/prices + backtest rules.",
    "Backtest_Spike_Ladder": "DEPRECATED — v1 backtest run on bad old bad data data. Results NOT trustworthy. Archived for history.",
    "Backtest_Spike_v2": "DEPRECATED — v2 backtest on old bad data. Will be re-run on clean Gamma-sourced data after recovery completes.",
    "QA_Log": "Auto-appended row per canonical_data load. Shows sample size, pass rate, blocked status. Updated by load_with_qa() at every backtest invocation.",
    "QA_Audit": "Manual audit of 20 random rows each (auctions / prices / posts) cross-checked against ground truth (Gamma / raw trades).",
    "Data_Consistency_Test": "Latest run of 8 structural checks × 2 handles. PASS/FAIL/WARN verdicts.",
    "Data_Coverage": "Coverage matrix — rows, date range, months, gaps per (handle, table).",
    "Data_Summary": "EXACT counts of what we have by source/type/handle. Use this as the master 'what data do we have' reference.",
}


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()
    tab_by_title = {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}

    # 1) Delete Posts_History
    if "Posts_History" in tab_by_title:
        sid = tab_by_title["Posts_History"]["sheetId"]
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=SS,
            body={"requests": [{"deleteSheet": {"sheetId": sid}}]},
        ).execute()
        print(f"  deleted Posts_History (id={sid})")
    else:
        print("  Posts_History not present, skip delete")

    # 2) For each remaining tab in DESCRIPTIONS, add banner
    # Re-fetch meta after delete
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()
    tab_by_title = {s["properties"]["title"]: s["properties"] for s in meta["sheets"]}

    for title, desc in DESCRIPTIONS.items():
        if title not in tab_by_title:
            print(f"  SKIP {title}: not in sheet")
            continue
        sid = tab_by_title[title]["sheetId"]

        # Check if row 1 already has marker
        r1 = sheets.spreadsheets().values().get(
            spreadsheetId=SS, range=f"{title}!A1:A1"
        ).execute()
        cur = ""
        if r1.get("values") and r1["values"][0]:
            cur = str(r1["values"][0][0])

        if cur.startswith(MARKER):
            # Overwrite the existing banner cell
            sheets.spreadsheets().values().update(
                spreadsheetId=SS,
                range=f"{title}!A1",
                valueInputOption="RAW",
                body={"values": [[MARKER + desc]]},
            ).execute()
            print(f"  updated banner: {title}")
        else:
            # Insert new row above row 1, then write banner
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SS,
                body={"requests": [{"insertDimension": {
                    "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                    "inheritFromBefore": False,
                }}]},
            ).execute()
            sheets.spreadsheets().values().update(
                spreadsheetId=SS,
                range=f"{title}!A1",
                valueInputOption="RAW",
                body={"values": [[MARKER + desc]]},
            ).execute()
            print(f"  inserted banner: {title}")

        # Format the banner row: dark grey bg, gold bold text, merged across cols A:N
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=SS,
            body={"requests": [
                {"mergeCells": {
                    "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                              "startColumnIndex": 0, "endColumnIndex": 20},
                    "mergeType": "MERGE_ALL",
                }},
                {"repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.17, "green": 0.17, "blue": 0.17},
                        "textFormat": {
                            "foregroundColor": {"red": 0.83, "green": 0.69, "blue": 0.22},
                            "bold": True, "fontSize": 11,
                        },
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                    }},
                    "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)",
                }},
                {"updateDimensionProperties": {
                    "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                    "properties": {"pixelSize": 36},
                    "fields": "pixelSize",
                }},
                {"updateSheetProperties": {
                    "properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 2}},
                    "fields": "gridProperties.frozenRowCount",
                }},
            ]},
        ).execute()

    print(f"\nDone. https://docs.google.com/spreadsheets/d/{SS}/edit")


if __name__ == "__main__":
    main()
