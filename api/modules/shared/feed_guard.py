"""Feed / price validation (BUILD_SPEC speed hardening; tweet-thread Part 1).

A raw feed delivers stale snapshots, duplicate ticks, and the occasional bad
print. Acting on those quietly degrades a strategy with no error. FeedGuard is a
reusable gate: drop the first (often cached) tick per source, dedupe by id,
reject stale ticks, and reject a price that jumped more than `max_delta` from the
last known-good value. Used as a sanity gate before acting on a book snapshot and
by the L2 recorder; ready for the speed lane's streams.
"""
import time
from collections import deque


class FeedGuard:
    def __init__(
        self,
        max_delta: float = 0.15,
        stale_s: float = 10.0,
        drop_first: bool = True,
        dedup_window: int = 4096,
    ):
        self.max_delta = max_delta
        self.stale_s = stale_s
        self._drop_first = drop_first
        self._first_dropped = False
        self._last_good: float | None = None
        self._seen: set = set()
        self._order: deque = deque(maxlen=dedup_window)  # bounded LRU of ids

    def accept(
        self,
        price: float | None = None,
        tick_id=None,
        ts: float | None = None,
    ) -> tuple[bool, str]:
        """Validate the tick you are about to act on. Returns (ok, reason).
        `ts` is a UNIX-seconds timestamp for staleness; None skips that check."""
        if self._drop_first and not self._first_dropped:
            self._first_dropped = True
            return False, "first_tick_dropped"
        if tick_id is not None:
            if tick_id in self._seen:
                return False, "duplicate"
            if len(self._order) == self._order.maxlen:
                self._seen.discard(self._order[0])
            self._order.append(tick_id)
            self._seen.add(tick_id)
        if ts is not None and self.stale_s and (time.time() - ts) > self.stale_s:
            return False, "stale"
        if price is not None:
            if (
                self._last_good is not None
                and abs(price - self._last_good) > self.max_delta
            ):
                return False, "delta_jump"
            self._last_good = price
        return True, "ok"

    def reset(self) -> None:
        """Call when a source reconnects or a new window opens."""
        self._first_dropped = False
        self._last_good = None
