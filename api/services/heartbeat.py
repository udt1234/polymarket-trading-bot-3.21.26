"""Heartbeat daemon (BUILD_SPEC E4) - DORMANT pending SDK verification.

The heartbeat-or-cancel feature is OPT-IN: the exchange only cancels all
orders when heartbeats were STARTED and then stop (old SDK docstring).
The archived py_clob_client exposed POST /heartbeat; the new unified
polymarket-client SDK has no such method (its heartbeats are WS ping/pong).
Until the endpoint story is verified against current docs, DO NOT start
this daemon - accidentally starting-then-missing heartbeats would cancel
the whole book. Not sending any is the safe default. Revisit at Step 7.
"""
import logging
import threading

log = logging.getLogger(__name__)

INTERVAL_S = 2.5


class HeartbeatDaemon:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat_id: str = ""  # empty string on first send (E4)
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
        # DORMANT: the unified polymarket-client SDK exposes no exchange
        # heartbeat method. Once heartbeats START, missing one cancels ALL
        # orders, so never start them half-supported. See module docstring.
        log.warning("Heartbeat daemon is dormant (no SDK endpoint) - not sending heartbeats")
        self._stop.wait()


heartbeat_daemon = HeartbeatDaemon()
