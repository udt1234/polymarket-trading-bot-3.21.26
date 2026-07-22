"""Two speed lanes (BUILD_SPEC B6, E7).

BACKGROUND PREP (PreSignLoop): between tweets, continuously pre-compute the
target bid ladder for the current count and the next 1-2 plausible counts,
build + SIGN the orders, hold them in memory. V2 bakes a ms timestamp at
signing and rejects stale orders, so the pool refreshes every REFRESH_S
(well inside the ~30s clock-drift horizon; benchmark the exact window on
the VPS, J3).

HOT PATH (on a streamed tweet): exactly two things - (1) one batch
cancel-all-in-market for the stale quotes, (2) POST the pre-signed set for
the new count. No fair-value compute, no signing, no JSON building, no
logging inside the timed section.
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

REFRESH_S = 20          # re-sign horizon (< ~30s V2 staleness, J3)
PLAUSIBLE_AHEAD = 2     # pre-sign ladders for count, count+1, count+2


class PreSignedPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_count: dict[int, dict] = {}  # count -> {signed, order_type, condition_id, signed_at}

    def put(self, count: int, entry: dict) -> None:
        with self._lock:
            self._by_count[count] = entry

    def take(self, count: int) -> dict | None:
        with self._lock:
            e = self._by_count.get(count)
            if e and time.time() - e["signed_at"] <= REFRESH_S + 8:
                return e
            return None


class PreSignLoop:
    """Runs in the API process, OFF the hot path. Requires the live client
    (dual guard) - dormant in paper mode (paper has no signing to prepare)."""

    def __init__(self, module_id: str, build_ladder):
        # build_ladder(count) -> list[(token_id, price, size)] + condition_id.
        # Injected by the live module wiring; pure compute, no I/O.
        self.module_id = module_id
        self.build_ladder = build_ladder
        self.pool = PreSignedPool()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current_count: int | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="presign-loop", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        from api.services.clob import create_signed_post_only
        while not self._stop.wait(REFRESH_S):
            base = self.current_count
            if base is None:
                continue
            for count in range(base, base + PLAUSIBLE_AHEAD + 1):
                try:
                    ladder = self.build_ladder(count)
                    if not ladder:
                        continue
                    signed = [create_signed_post_only(token_id, "BUY", price, size,
                                                      tick=ladder.get("tick", 0.01))
                              for token_id, price, size in ladder["orders"]]
                    self.pool.put(count, {"signed": signed,
                                          "condition_id": ladder["condition_id"],
                                          "signed_at": time.time()})
                except Exception:
                    log.exception("presign failed for count=%d", count)


class HotPath:
    """fire(new_count): batch-cancel stale quotes + submit the ready set.
    Everything here must already be built - clone and send, nothing else."""

    def __init__(self, presign: PreSignLoop):
        self.presign = presign
        self.last_latency_ms: float | None = None

    def fire(self, new_count: int) -> bool:
        # SAFETY GATE (risk-audit 2026-07-22): the hot path posts PRE-SIGNED orders
        # with NO per-order risk_manager.check() anywhere in the lane, and
        # PreSignLoop currently signs whatever build_ladder() returns without a risk
        # pass. Until that gap is closed this lane must never fire live. Two backstops
        # here: (a) the dual live guard, (b) the circuit breaker.
        # ⚠️ BEFORE WIRING THIS LANE LIVE: add risk_manager.check() (or a fast
        #    exposure/duplicate/breaker snapshot) inside PreSignLoop._run before
        #    create_signed_post_only, so only risk-approved ladders ever get signed.
        #    This gate alone does NOT enforce exposure/loss/duplicate/depth limits.
        from api.config import get_settings
        s = get_settings()
        live = s.environment == "production" and not s.paper_mode and s.allow_live_trading
        if not live:
            log.warning("HOT PATH suppressed: dual live guard not satisfied "
                        "(paper/dev) - refusing to post pre-signed orders")
            return False
        from api.services.breaker import is_tripped
        if is_tripped():
            log.warning("HOT PATH suppressed: circuit breaker tripped")
            return False

        from api.services import clob
        entry = self.presign.pool.take(new_count)
        if entry is None:
            self.presign.current_count = new_count
            return False  # pool miss - slow path will requote next cycle
        t0 = time.perf_counter()
        clob.cancel_market(market=entry["condition_id"])
        clob.post_signed(entry["signed"])
        self.last_latency_ms = (time.perf_counter() - t0) * 1000
        self.presign.current_count = new_count
        log.info("HOT PATH fired count=%d in %.1f ms", new_count, self.last_latency_ms)
        return True
