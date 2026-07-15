"""One-time TwitterAPI.io filter-rule setup (BUILD_SPEC C4, Step 5).

Registers the `from:elonmusk` rule that feeds the hot-path WebSocket.
Needs TWITTERAPI_IO_KEY in the environment (buy at twitterapi.io).

  python scripts/setup_tweet_rule.py            # list rules
  python scripts/setup_tweet_rule.py --add      # add from:elonmusk
"""
import os
import sys

import httpx

BASE = "https://api.twitterapi.io/oapi/tweet_filter"


def main() -> None:
    key = os.getenv("TWITTERAPI_IO_KEY", "")
    if not key:
        raise SystemExit("TWITTERAPI_IO_KEY unset")
    headers = {"x-api-key": key}
    if "--add" in sys.argv:
        r = httpx.post(f"{BASE}/add_rule", headers=headers, json={
            "tag": "elon_tweets_hotpath",
            "value": "from:elonmusk",
            "interval_seconds": 0.1,   # min allowed 0.05; 100ms is noise vs the ~300-500ms X floor
        }, timeout=30)
        print(r.status_code, r.text[:400])
    r = httpx.get(f"{BASE}/get_rules", headers=headers, timeout=30)
    print(r.status_code, r.text[:800])


if __name__ == "__main__":
    main()
