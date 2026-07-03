"""Row 1: black Calibri text on white (transparent) background.
   Row 3 onward: wrap text.
"""
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
import time

SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()

    batch_size = 6
    all_tabs = meta["sheets"]
    for batch_start in range(0, len(all_tabs), batch_size):
        batch = all_tabs[batch_start:batch_start + batch_size]
        requests = []
        for s in batch:
            sid = s["properties"]["sheetId"]
            title = s["properties"]["title"]
            # Row 1: black Calibri, white bg, keep bold (descriptions look better bold), wrap
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                    "textFormat": {
                        "fontFamily": "Calibri",
                        "foregroundColor": {"red": 0, "green": 0, "blue": 0},
                        "bold": True,
                        "fontSize": 11,
                    },
                    "wrapStrategy": "WRAP",
                    "verticalAlignment": "MIDDLE",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)",
            }})
            # Row 3+: wrap text (Calibri already applied previously, keep that)
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 2},
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }})
            print(f"  queued: {title}")
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": requests}).execute()
        print(f"  batch sent ({len(batch)} tabs, {len(requests)} requests)")
        if batch_start + batch_size < len(all_tabs):
            time.sleep(20)

    print(f"\nDone. https://docs.google.com/spreadsheets/d/{SS}/edit")


if __name__ == "__main__":
    main()
