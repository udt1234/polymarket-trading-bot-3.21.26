"""One-shot rename tab pass: drop 'Sample'/'Samples'/'Sampled' suffix."""
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"

RENAMES = {
    "Elon_Posts_Sample": "Elon_Posts",
    "Elon_Prices_Sample": "Elon_Prices",
    "Trump_Posts_Sample": "Trump_Posts",
    "Trump_Prices_Sample": "Trump_Prices",
    "Canonical_Prices_Sample": "Canonical_Prices",
    "QA_Sample_Audit": "QA_Audit",
    "Posts_History_Samples": "Posts_History",
}


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()
    requests = []
    skipped = []
    for s in meta["sheets"]:
        old = s["properties"]["title"]
        if old not in RENAMES:
            continue
        new = RENAMES[old]
        # check collision
        if any(x["properties"]["title"] == new for x in meta["sheets"] if x["properties"]["title"] != old):
            skipped.append((old, new, "target already exists"))
            continue
        requests.append({"updateSheetProperties": {
            "properties": {"sheetId": s["properties"]["sheetId"], "title": new},
            "fields": "title",
        }})
        print(f"  rename: {old} -> {new}")
    if requests:
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": requests}).execute()
    if skipped:
        print("Skipped:", skipped)
    print(f"\nDone. Renamed {len(requests)} tabs.")


if __name__ == "__main__":
    main()
