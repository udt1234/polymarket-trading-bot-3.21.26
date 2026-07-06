"""Heartbeat daemon (BUILD_SPEC E4) - mandatory whenever real orders rest.

The CLOB cancels ALL open orders if no valid heartbeat arrives within 10s
(+5s buffer). We send every 2.5s from an isolated lightweight thread so a
busy engine loop can never starve it. That aggressive cadence leaves ~4
consecutive misses of headroom instead of one.

This is also our dead-man switch: if this process dies, the exchange
flattens our resting quotes for us.
"""
import logging
import threading

log = logging.getLogger(__name__)

INTERVAL_S = 2.5


class HeartbeatDaemon:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat_id: str | None = None  # empty on first send (E4)
        self.last_ok_ts: float | None = None
        self.consecutive_failures = 0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="clob-heartbeat", daemon=True)
        self._thread.start()
        log.info("Heartbeat daemon started (every %.1fs)", INTERVAL_S)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Heartbeat daemon stopped")

    def _run(self):
        import time
        from api.services.clob import get_clob_client
        client = get_clob_client()
        while not self._stop.wait(INTERVAL_S):
            try:
                resp = client.post_heartbeat(self._heartbeat_id)
                if isinstance(resp, dict) and resp.get("heartbeat_id"):
                    self._heartbeat_id = resp["heartbeat_id"]
                self.last_ok_ts = time.time()
                self.consecutive_failures = 0
            except Exception as e:
                # Do NOT reset _heartbeat_id on failure - the server may still
                # consider the old id valid. Keep firing; a 15s gap means the
                # exchange already cancelled everything (fail-closed for us).
                self.consecutive_failures += 1
                log.error("Heartbeat failed (%d in a row): %s", self.consecutive_failures, e)


heartbeat_daemon = HeartbeatDaemon()
