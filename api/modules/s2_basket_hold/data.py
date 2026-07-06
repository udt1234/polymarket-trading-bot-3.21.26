"""S2-specific data assembly (BUILD_SPEC B3): the live auction snapshot the
decision layer consumes. Generic fetchers live in shared/."""
import logging

from api.modules.shared import discovery, tweet_count, windows

log = logging.getLogger(__name__)


def live_auction_snapshot(duration: str) -> dict | None:
    """Freshest live Elon auction of the configured duration, with the
    current in-window count attached. None when anything is missing
    (fail closed - never model without a count)."""
    auctions = discovery.fetch_tweet_auctions(slug_contains="elon-musk-of-tweets")
    auction = discovery.freshest_auction(auctions, duration=duration)
    if not auction:
        return None
    tracking = tweet_count.fetch_tracking_for_slug(auction["slug"])
    if not tracking:
        log.warning("no xTracker tracking for %s", auction["slug"])
        return None
    count = tweet_count.current_count(tracking["id"])
    if count is None:
        return None
    auction["count"] = count
    auction["elapsed"] = windows.elapsed_fraction(auction["window_start"],
                                                  auction["window_end"])
    return auction
