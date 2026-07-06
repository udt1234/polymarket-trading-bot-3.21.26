"""The main loop (BUILD_SPEC B6 slow path).

Every cycle (default 5 min): paper-fill sweep, exits FIRST (E8), then each
non-inactive module row evaluates -> risk gate -> executor. All state in
Supabase; one module failing never blocks another (per-module try/except).
Hot path (Step 5) lives beside this, not inside it.
"""
import logging
from datetime import datetime, timezone

from api.config import get_settings
from api.dependencies import get_supabase
from api.modules import ModuleRegistry
from api.services import risk_manager
from api.services.executor import PaperExecutor, _record_signal, executor_for
from api.services.risk_manager import Signal

log = logging.getLogger(__name__)


class Engine:
    def __init__(self, registry: ModuleRegistry):
        self.registry = registry
        self.paper = PaperExecutor()
        self._scheduler = None
        self.last_cycle_at: str | None = None
        self.cycles = 0

    # ---- scheduling ----
    def start(self):
        from apscheduler.schedulers.background import BackgroundScheduler
        s = get_settings()
        self._scheduler = BackgroundScheduler(job_defaults={
            "coalesce": True, "max_instances": 1, "misfire_grace_time": 60})
        self._scheduler.add_job(self.cycle, "interval",
                                seconds=s.default_interval, id="engine-cycle")
        self._scheduler.start()
        log.info("engine scheduler started (every %ss)", s.default_interval)

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)

    # ---- one slow-path cycle ----
    def cycle(self) -> dict:
        sb = get_supabase()
        summary = {"modules": 0, "signals": 0, "approved": 0, "paper_fills": 0,
                   "errors": 0}
        try:
            rows = (sb.table("modules").select("*")
                    .neq("status", "inactive").execute().data) or []
        except Exception:
            log.exception("cycle: modules query failed")
            return summary

        # 1. Sweep paper fills against live top-of-book.
        try:
            summary["paper_fills"] = self.paper.check_fills(self._live_quotes())
        except Exception:
            log.exception("paper fill sweep failed")
            summary["errors"] += 1

        # 2. Sweep positions stuck in 'closing'.
        try:
            from api.services.position_manager import sweep_stuck_closing
            sweep_stuck_closing()
        except Exception:
            log.exception("stuck-closing sweep failed")

        breaker = self._breaker_tripped(sb)

        # 3. Per-module evaluate -> risk -> executor. Exits run within each
        #    module's signal batch FIRST (E8) and bypass entry gates.
        for row in rows:
            module = self.registry.for_db_row(row)
            if module is None:
                continue
            summary["modules"] += 1
            try:
                signals: list[Signal] = module.evaluate(row["id"]) or []
                signals.sort(key=lambda x: not x.is_exit)  # exits first (E8)
                for sig in signals:
                    summary["signals"] += 1
                    verdict = risk_manager.check(sig, breaker_tripped=breaker and not sig.is_exit)
                    _record_signal(sb, sig, verdict.approved, verdict.reason)
                    if not verdict.approved:
                        log.info("REJECT %s %s: %s", sig.side, sig.bracket, verdict.reason)
                        continue
                    summary["approved"] += 1
                    executor = executor_for(row.get("status") or "paper")
                    executor.execute(sig)
            except Exception:
                log.exception("module %s cycle failed", row.get("name"))
                summary["errors"] += 1

        self.cycles += 1
        self.last_cycle_at = datetime.now(timezone.utc).isoformat()
        try:
            sb.table("logs").insert({
                "log_type": "system", "severity": "info",
                "message": f"Cycle: {summary}",
                "metadata": summary}).execute()
        except Exception:
            log.exception("cycle log write failed")
        log.info("cycle done: %s", summary)
        return summary

    # ---- helpers ----
    def _live_quotes(self) -> dict[str, dict]:
        """token_id -> {best_bid, best_ask} for every live tweet bracket
        (Gamma, C2). Used by the paper fill simulator."""
        from api.modules.shared import discovery
        quotes: dict[str, dict] = {}
        try:
            for a in discovery.fetch_tweet_auctions():
                for b in a["brackets"]:
                    quotes[b["yes_token"]] = {"best_bid": b["best_bid"],
                                              "best_ask": b["best_ask"]}
        except Exception:
            log.exception("live quote fetch failed")
        return quotes

    def _breaker_tripped(self, sb) -> bool:
        """Circuit-breaker state persisted in settings (G2). Fail closed:
        an unreadable breaker BLOCKS new entries."""
        s = get_settings()
        if not s.circuit_breaker_enabled:
            return False
        try:
            res = (sb.table("settings").select("value")
                   .eq("key", "circuit_breaker").limit(1).execute())
            if not res.data:
                return False  # never tripped yet - absence is a real state
            v = res.data[0].get("value") or {}
            until = v.get("cooldown_until") or ""
            return bool(until) and until > datetime.now(timezone.utc).isoformat()
        except Exception:
            log.exception("breaker read failed - failing CLOSED")
            return True
