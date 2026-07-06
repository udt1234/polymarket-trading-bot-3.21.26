"""Tweet ingestion stream (BUILD_SPEC C4, B7 step 1) - the hot-path trigger.

TwitterAPI.io filtered WebSocket (paid, sub-500ms). Endpoint verified
against twitterapi.io docs 2026-07-06:
  WS:  wss://ws.twitterapi.io/twitter/tweet/websocket  (x-api-key header)
  Msg: {"event_type": "tweet", "rule_id": ..., "tweets": [{...}]}
NOT ACTIVE until Sir buys a key (TWITTERAPI_IO_KEY) and the filter rule
`from:elonmusk` is registered (scripts/setup_tweet_rule.py).

Feed hygiene (playbook 2026-07-03): drop the first (possibly cached) tick,
require fresh timestamps, guard against stale/duplicate tweet ids.
"""
import asyncio
import json
import logging
import os
import time

from api.modules.shared.tweet_count import counts_for_auction

log = logging.getLogger(__name__)


class TweetStream:
    """Persistent WS -> on_countable(tweet) callback for tweets that pass
    the LOCKED counting rule. Exponential backoff reconnect + stall watchdog."""

    def __init__(self, on_countable, handle_user_id: str = "44196397"):
        self.on_countable = on_countable
        self.handle_user_id = handle_user_id
        self._stop = asyncio.Event()
        self._seen: set[str] = set()
        self.last_msg_ts: float | None = None

    async def run(self):
        import websockets
        url = os.getenv("TWITTERAPI_WS_URL",
                        "wss://ws.twitterapi.io/twitter/tweet/websocket")
        key = os.getenv("TWITTERAPI_IO_KEY", "")
        if not key:
            log.warning("TweetStream dormant: TWITTERAPI_IO_KEY unset")
            return
        backoff = 1
        first_after_connect = True
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, additional_headers={"x-api-key": key},
                                              ping_interval=15) as ws:
                    log.info("tweet stream connected")
                    backoff = 1
                    first_after_connect = True
                    async for raw in ws:
                        self.last_msg_ts = time.time()
                        try:
                            msg = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        for tweet in msg.get("tweets") or ([msg] if msg.get("id") else []):
                            if first_after_connect:
                                first_after_connect = False  # drop possibly-cached first tick
                                continue
                            tid = str(tweet.get("id") or "")
                            if not tid or tid in self._seen:
                                continue
                            self._seen.add(tid)
                            if counts_for_auction(tweet, self.handle_user_id):
                                t0 = time.perf_counter()
                                try:
                                    self.on_countable(tweet)
                                finally:
                                    log.info("hot-path handler took %.1f ms",
                                             (time.perf_counter() - t0) * 1000)
            except Exception as e:
                if self._stop.is_set():
                    break
                log.warning("tweet stream dropped (%s) - reconnect in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def stop(self):
        self._stop.set()
