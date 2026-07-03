"""Unmerge row 2 across every tab, then restore proper headers."""
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
import time

SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"

HEADERS = {
    "Elon_Posts": ["year_month", "ts_utc", "ts_et", "post_id", "is_reply", "is_repost", "is_quote",
                    "is_community_repost", "counts_for_auction", "source", "content_text", "url"],
    "Trump_Posts": ["year_month", "ts_utc", "ts_et", "post_id", "is_reply", "is_repost", "is_quote",
                     "is_community_repost", "counts_for_auction", "source", "content_text", "url"],
    "Elon_Prices": ["auction_slug", "auction_title", "ts_et", "ts_utc", "hours_in", "side", "outcome",
                     "bucket", "is_winning_bucket", "bracket_market_title", "price", "size_shares",
                     "notional_usd", "trader_name", "trader_wallet", "tx_hash"],
    "Trump_Prices": ["auction_slug", "auction_title", "ts_et", "ts_utc", "hours_in", "side", "outcome",
                      "bucket", "is_winning_bucket", "bracket_market_title", "price", "size_shares",
                      "notional_usd", "trader_name", "trader_wallet", "tx_hash"],
    "Elon_Auctions_Inventory": ["file", "auction_slug", "duration_type", "window_days", "n_trades",
                                  "n_unique_traders", "first_trade_et", "last_trade_et", "trade_span_hours",
                                  "unique_buckets", "all_buckets", "winning_bucket", "resolution_status",
                                  "winner_close_price", "winner_open_price", "winner_peak_price",
                                  "winner_low_price", "total_volume_usd", "title", "condition_id"],
    "Trump_Auctions_Inventory": ["file", "auction_slug", "duration_type", "window_days", "n_trades",
                                   "n_unique_traders", "first_trade_et", "last_trade_et", "trade_span_hours",
                                   "unique_buckets", "all_buckets", "winning_bucket", "resolution_status",
                                   "winner_close_price", "winner_open_price", "winner_peak_price",
                                   "winner_low_price", "total_volume_usd", "title", "condition_id"],
}


def main():
    creds = service_account.Credentials.from_service_account_file(
        str(SA), scopes=["https://www.googleapis.com/auth/spreadsheets"],
        subject="darwin@xagency.com",
    )
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = sheets.spreadsheets().get(spreadsheetId=SS).execute()

    # Find all merges in row 2 across every tab and unmerge them
    # ALSO unmerge row 1 cleanly + re-merge ONLY row 1 (not row 2)
    BATCH_SIZE = 6
    all_sheets = meta["sheets"]
    for i in range(0, len(all_sheets), BATCH_SIZE):
        batch = all_sheets[i:i + BATCH_SIZE]
        requests = []
        for s in batch:
            sid = s["properties"]["sheetId"]
            title = s["properties"]["title"]
            # Unmerge ALL row 0-1 and row 1-2 spans
            requests.append({"unmergeCells": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 2,
                          "startColumnIndex": 0, "endColumnIndex": 26},
            }})
            # Re-merge ONLY row 1 (banner) across A:Z
            requests.append({"mergeCells": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 26},
                "mergeType": "MERGE_ALL",
            }})
            print(f"  unmerged row 2 + re-merged row 1 only: {title}")
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": requests}).execute()
        print(f"  batch sent ({len(batch)} tabs)")
        if i + BATCH_SIZE < len(all_sheets):
            time.sleep(15)

    # Now write the headers to row 2 on the 6 affected tabs
    print()
    for title, header in HEADERS.items():
        sheets.spreadsheets().values().update(
            spreadsheetId=SS,
            range=f"{title}!A2",
            valueInputOption="RAW",
            body={"values": [header]},
        ).execute()
        print(f"  wrote row-2 headers: {title} ({len(header)} cols)")
        time.sleep(1.5)

    print(f"\nDone. https://docs.google.com/spreadsheets/d/{SS}/edit")


if __name__ == "__main__":
    main()
