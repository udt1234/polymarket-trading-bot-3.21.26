"""Repair: restore row-2 headers + clear gray bg on every data row."""
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
import time

SS = "1bXBnXz4a1Nn44ZLORNo2cNqZx6pnqER3rcoTUZMC1Q8"
SA = Path.home() / ".claude" / "google-service-account.json"

# Per-tab header row 2 schemas (matches pusher scripts)
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
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}

    # PART 1: Restore row-2 headers on affected tabs
    for title, header in HEADERS.items():
        if title not in tabs:
            print(f"  SKIP {title}: not in sheet")
            continue
        # Write the proper header to row 2
        sheets.spreadsheets().values().update(
            spreadsheetId=SS,
            range=f"{title}!A2",
            valueInputOption="RAW",
            body={"values": [header]},
        ).execute()
        print(f"  restored row-2 headers: {title} ({len(header)} cols)")
        time.sleep(1)

    # PART 2: For EVERY tab in the sheet, clear background color on row 3+ AND
    # apply light grey header style only to row 2 (not row 3+)
    print("\n  clearing row 3+ backgrounds across all tabs...")
    all_titles = list(tabs.keys())
    BATCH_SIZE = 6
    for i in range(0, len(all_titles), BATCH_SIZE):
        batch = all_titles[i:i + BATCH_SIZE]
        requests = []
        for title in batch:
            sid = tabs[title]
            # Row 2: light gray bg, bold (proper header style)
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.93, "green": 0.93, "blue": 0.93},
                    "textFormat": {"fontFamily": "Calibri", "bold": True, "fontSize": 10,
                                    "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                    "wrapStrategy": "WRAP",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)",
            }})
            # Row 3+: WHITE bg, Calibri, normal weight, wrap
            requests.append({"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 2},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                    "textFormat": {"fontFamily": "Calibri", "bold": False, "fontSize": 10,
                                    "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                    "wrapStrategy": "WRAP",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,wrapStrategy)",
            }})
            print(f"    queued: {title}")
        sheets.spreadsheets().batchUpdate(spreadsheetId=SS, body={"requests": requests}).execute()
        print(f"    batch sent ({len(batch)} tabs)")
        if i + BATCH_SIZE < len(all_titles):
            time.sleep(15)

    print(f"\nDone. https://docs.google.com/spreadsheets/d/{SS}/edit")


if __name__ == "__main__":
    main()
