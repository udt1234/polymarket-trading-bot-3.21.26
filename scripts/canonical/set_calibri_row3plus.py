"""Set font to Calibri for row 3 onward on every tab."""
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

    # Batch tabs in groups to respect 60 writes/min quota
    batch_size = 8
    all_tabs = meta["sheets"]
    for batch_start in range(0, len(all_tabs), batch_size):
        batch = all_tabs[batch_start:batch_start + batch_size]
        requests = []
        for s in batch:
            sid = s["properties"]["sheetId"]
            title = s["properties"]["title"]
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sid, "startRowIndex": 2},  # row 3 onward (0-indexed = 2)
                    "cell": {"userEnteredFormat": {"textFormat": {"fontFamily": "Calibri"}}},
                    "fields": "userEnteredFormat.textFormat.fontFamily",
                }
            })
            print(f"  queued: {title}")
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": requests}).execute()
        print(f"  batch sent ({len(batch)} tabs)")
        if batch_start + batch_size < len(all_tabs):
            time.sleep(15)  # spread out the writes

    print(f"\nDone. https://docs.google.com/spreadsheets/d/{SS}/edit")


if __name__ == "__main__":
    main()
