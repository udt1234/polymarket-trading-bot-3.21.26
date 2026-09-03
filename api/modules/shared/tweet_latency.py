"""Tweet detection-latency instrument + selective-fire gate (Step 0/1, 2026-07-14).

The tweet-reaction edge (SHORT the plummeting near-money bracket) is +EV only when
we DETECT the tweet fast: backtested ROI/$100 = +4.4 @0-150ms, +0.8 @250ms,
break-even ~300ms, NEGATIVE beyond ~400ms. Sub-200ms is not cheaply buyable (X's
own publish->deliver floor bleeds through every feed), so instead of buying speed
we MEASURE per-tweet detection latency and only fire on tweets that happened to
arrive fast. The same measurement diagnoses whether our ~500ms is X's server floor
(unfixable, no spend helps) or the vendor->us network hop (geography-fixable).

Truth source for X-publish time = the tweet's SNOWFLAKE ID (the timestamp is baked
into the id; the vendor cannot fudge it), NOT the vendor's created_at string.
Requires an NTP-synced local clock (the Dublin VPS is).
"""
import logging

log = logging.getLogger(__name__)

TWITTER_EPOCH_MS = 1288834974657   # snowflake epoch (2010-11-04 01:42:54.657 UTC)
DEFAULT_GATE_MS = 250.0            # fire only if detection <= this (edge curve: +0.8 @250, ~0 @300)


def snowflake_ms(tweet_id) -> int | None:
    """X publish time (unix ms) decoded from the snowflake tweet id."""
    try:
        tid = int(tweet_id)
    except (TypeError, ValueError):
        return None
    if tid <= 0:
        return None
    return (tid >> 22) + TWITTER_EPOCH_MS


def _snow_delay(tweet: dict):
    """Vendor's own X->their-server delay (ms), if the feed provides it."""
    for k in ("snow_delay_ms", "snowDelayMs", "snow_delay"):
        v = tweet.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def measure(tweet: dict, recv_wall_ms: float) -> dict:
    """Per-tweet latency breakdown at the instant WE became aware of the tweet.

    detection_ms = X publish -> our receive  (the number the edge curve consumes)
    snow_delay_ms = X -> vendor server        (vendor field; the unfixable-floor probe)
    network_ms  = vendor -> us                (detection - snow_delay; geography-fixable)
    """
    x_ms = snowflake_ms(tweet.get("id") or tweet.get("id_str"))
    detection_ms = (recv_wall_ms - x_ms) if x_ms else None
    snow = _snow_delay(tweet)
    network_ms = (detection_ms - snow) if (detection_ms is not None and snow is not None) else None
    if detection_ms is not None and detection_ms < -50:
        # implausible: our clock is behind X's -> NTP drift, measurement suspect
        log.warning("tweet %s detection_ms=%.0f (<0) - check VPS clock sync",
                    tweet.get("id"), detection_ms)
    return {"detection_ms": None if detection_ms is None else round(detection_ms, 1),
            "snow_delay_ms": None if snow is None else round(snow, 1),
            "network_ms": None if network_ms is None else round(network_ms, 1),
            "x_publish_ms": x_ms}


def should_trade(detection_ms, gate_ms: float = DEFAULT_GATE_MS) -> tuple[bool, str]:
    """Selective-fire gate: only trade tweets that arrived inside the +EV latency
    band. A missing measurement FAILS CLOSED - never trade a tweet we cannot time."""
    if detection_ms is None:
        return False, "no_latency_measure"
    if detection_ms > gate_ms:
        return False, f"too_slow_{int(detection_ms)}ms>gate_{int(gate_ms)}ms"
    return True, f"ok_{int(detection_ms)}ms"
