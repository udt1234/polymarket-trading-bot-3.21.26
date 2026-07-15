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

from api.modules.shared import tweet_latency
from api.modules.shared.tweet_count import counts_for_auction

log = logging.getLogger(__name__)


class TweetStream:
    """Persistent WS -> on_countable(tweet, meta) callback for tweets that pass
    the LOCKED counting rule. Exponential backoff reconnect + stall watchdog.

    Every countable tweet is instrumented for DETECTION LATENCY (X-publish ->
    our-receive, decoded from the snowflake id) and passed a `meta` dict:
      {detection_ms, snow_delay_ms, network_ms, x_publish_ms, fast_enough, gate_reason}
    The consumer MUST honor meta["fast_enough"] before placing a trade - the
    tweet-reaction edge is only +EV inside the gate_ms latency band. Counting is
    NOT gated (a slow tweet still counts toward the auction; we just don't trade
    its reaction). Latency is logged to Supabase OFF the hot path for the
    X-floor-vs-network diagnostic."""

    def __init__(self, on_countable, handle_user_id: str = "44196397",
                 gate_ms: float = tweet_latency.DEFAULT_GATE_MS):
        self.on_countable = on_countable
        self.handle_user_id = handle_user_id
        self.gate_ms = gate_ms
        self._stop = asyncio.Event()
        self._seen: set[str] = set()
        self.last_msg_ts: float | None = None
        self._bg: set = set()

    async def run(self):
        import websockets
        from api.config import get_settings
        s = get_settings()
        # read the key from settings (loads .env) with an os.environ fallback -
        # pydantic reads .env into the Settings object, not os.environ.
        url = os.getenv("TWITTERAPI_WS_URL",
                        "wss://ws.twitterapi.io/twitter/tweet/websocket")
        key = s.twitterapi_io_key or os.getenv("TWITTERAPI_IO_KEY", "")
        if not key:
            log.warning("TweetStream dormant: twitterapi_io_key unset")
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
                        recv_ms = self.last_msg_ts * 1000.0  # earliest we can timestamp arrival
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
                                meta = tweet_latency.measure(tweet, recv_ms)
                                fire, reason = tweet_latency.should_trade(
                                    meta["detection_ms"], self.gate_ms)
                                meta["fast_enough"] = fire
                                meta["gate_reason"] = reason
                                t0 = time.perf_counter()
                                try:
                                    self.on_countable(tweet, meta)
                                finally:
                                    handler_ms = (time.perf_counter() - t0) * 1000
                                    log.info(
                                        "hot-path handler %.1fms | detection=%sms snow=%sms "
                                        "net=%sms fire=%s (%s)", handler_ms,
                                        meta["detection_ms"], meta["snow_delay_ms"],
                                        meta["network_ms"], fire, reason)
                                    self._record_latency(tweet, meta, handler_ms)
            except Exception as e:
                if self._stop.is_set():
                    break
                log.warning("tweet stream dropped (%s) - reconnect in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _record_latency(self, tweet, meta, handler_ms):
        """Persist the per-tweet latency for the X-floor-vs-network diagnostic.
        Runs the sync Supabase insert in a thread so it never blocks reading the
        next tweet (already off the timed hot section - on_countable has returned)."""
        try:
            task = asyncio.create_task(
                asyncio.to_thread(self._insert_latency, str(tweet.get("id")), meta, handler_ms))
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
        except RuntimeError:
            pass  # no running loop (not reachable from run())

    @staticmethod
    def _insert_latency(tweet_id, meta, handler_ms):
        try:
            from api.dependencies import get_supabase
            get_supabase().table("logs").insert({
                "log_type": "tweet_latency",
                "severity": "info" if meta.get("fast_enough") else "warning",
                "message": (f"tweet {tweet_id} detection={meta['detection_ms']}ms "
                            f"fire={meta.get('fast_enough')} ({meta.get('gate_reason')})"),
                "metadata": {**meta, "tweet_id": tweet_id, "handler_ms": round(handler_ms, 1)},
            }).execute()
        except Exception:
            log.exception("tweet_latency log write failed")

    def stop(self):
        self._stop.set()
