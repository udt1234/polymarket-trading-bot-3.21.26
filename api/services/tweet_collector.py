"""Listen-only tweet-latency collector (Step 0 diagnostic, 2026-07-14).

Runs the TweetStream against the live TwitterAPI.io feed purely to COLLECT the
per-tweet detection-latency distribution (TweetStream logs each measurement to
Supabase itself, off the hot path). It does NOT trade - the consumer is a no-op.
Its only job is to answer, before we spend a dollar on a faster feed:
  is our ~500ms X's own server floor (snow_delay_ms), or the vendor->us network
  hop (network_ms)?
Safe in paper OR live: it never places an order. Gated by enable_tweet_collector
and the presence of a TwitterAPI.io key (TweetStream self-guards on the key too).
"""
import asyncio
import logging

from api.services.tweet_stream import TweetStream

log = logging.getLogger(__name__)

_stream: TweetStream | None = None
_task: "asyncio.Task | None" = None


def _on_countable(tweet: dict, meta: dict) -> None:
    # Listen-only: TweetStream already recorded the latency off the hot path.
    # No order is placed. Explicit hook for the future reaction module to fill in
    # (it will honor meta["fast_enough"] before shorting the near-money bracket).
    return None


def start() -> None:
    global _stream, _task
    from api.config import get_settings
    s = get_settings()
    if not getattr(s, "enable_tweet_collector", True):
        log.info("tweet collector disabled by config")
        return
    if not (s.twitterapi_io_key or ""):
        log.info("tweet collector dormant: twitterapi_io_key unset")
        return
    _stream = TweetStream(_on_countable)
    _task = asyncio.create_task(_stream.run(), name="tweet-collector")
    log.info("tweet collector started (listen-only latency diagnostic)")


def stop() -> None:
    global _stream, _task
    if _stream is not None:
        _stream.stop()
    if _task is not None:
        _task.cancel()
    _stream = _task = None
