"""The main loop (BUILD_SPEC B6 slow path).

Every cycle (default 5 min): paper-fill sweep, exits FIRST (E8), then each
non-inactive module row evaluates -> risk gate -> executor. All state in
Supabase; one module failing never blocks another (per-module try/except).
Hot path (Step 5) lives beside this, not inside it.
"""
import logging
from datetime import datetime, timedelta, timezone

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
        from api.services.notifications import daily_heartbeat
        self._scheduler.add_job(lambda: daily_heartbeat(self), "cron",
                                hour="9,17", minute=0,
                                timezone="America/New_York",
                                id="daily-heartbeat")
        from api.services.resolution import run_resolution_sweep
        self._scheduler.add_job(run_resolution_sweep, "interval", minutes=30,
                                id="resolution-sweep")
        from api.services.retention import run_retention_cleanup
        self._scheduler.add_job(run_retention_cleanup, "cron",
                                hour=3, minute=30, timezone="UTC",
                                id="retention-cleanup")
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

        # 2a. Expire stale resting orders, BOTH sides. Maker quotes (bids AND
        #     inventory offers) are re-quoted fresh each cycle, so anything older
        #     than STALE_ORDER_HOURS is a ghost. Unfilled BUYs eat the exposure
        #     cap forever (froze the bench for 6 days, 2026-07); unfilled SELLs
        #     were never swept at all and 8,448 of them piled up over 53 days,
        #     pointing at positions that had long since closed (2026-09-01).
        #     Cancel paper ghosts here; a live GTD order self-expires on the
        #     exchange, so only sweep paper.
        try:
            self._expire_stale_orders(sb)
        except Exception:
            log.exception("stale-order sweep failed")

        # 2b. Hourly price snapshots (dashboard charts + model history).
        try:
            self._write_price_snapshots()
        except Exception:
            log.exception("price snapshot write failed")

        breaker = self._breaker_tripped(sb)
        # Global manual halt: block ALL new entries (exits still run so positions
        # can close). Same shape as the breaker - it pauses entries, never exits.
        try:
            from api.services.halt import is_halted
            if is_halted():
                breaker = True
        except Exception:
            log.exception("halt check failed - treating as halted (fail safe)")
            breaker = True

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
                    # risk_manager itself lets exits through before the
                    # breaker check (E8) - no engine-side special case.
                    verdict = risk_manager.check(sig, breaker_tripped=breaker)
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
    def _expire_stale_orders(self, sb) -> int:
        """Cancel unfilled resting orders older than STALE_ORDER_HOURS so they
        stop counting toward the exposure cap and stop referencing positions
        that have already closed. Both sides. Paper only: live GTD
        orders self-expire on the exchange. Returns the count cancelled."""
        s = get_settings()
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(hours=s.stale_order_hours)).isoformat()
        rows = (sb.table("orders").select("id")
                .eq("executor", "paper")
                .in_("status", ["submitted", "open", "partially_filled"])
                .lt("created_at", cutoff).execute().data) or []
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        for i in range(0, len(ids), 50):
            (sb.table("orders")
             .update({"status": "cancelled",
                      "metadata": {"cancel_reason": "stale_ttl"}})
             .in_("id", ids[i:i + 50]).execute())
        log.info("expired %d stale paper order(s) older than %dh",
                 len(ids), s.stale_order_hours)
        if len(ids) > 200:
            try:
                sb.table("logs").insert({
                    "log_type": "system", "severity": "warning",
                    "message": f"stale-order sweep cancelled {len(ids)} orders",
                    "metadata": {"cancelled": len(ids),
                                 "ttl_hours": s.stale_order_hours}}).execute()
            except Exception:
                log.exception("stale-order sweep log failed")
        return len(ids)

    def _live_quotes(self) -> dict[str, dict]:
        """token_id -> {best_bid, best_ask} for every live market the active
        modules trade (tweet brackets + sports game sides), so the paper fill
        simulator can fill any module's resting orders (C2)."""
        from api.modules.shared import discovery
        quotes: dict[str, dict] = {}
        try:
            for a in discovery.fetch_tweet_auctions():
                for b in a["brackets"]:
                    quotes[b["yes_token"]] = {"best_bid": b["best_bid"],
                                              "best_ask": b["best_ask"]}
        except Exception:
            log.exception("tweet quote fetch failed")
        # sports game sides (union of every active sports_sweep module's series)
        try:
            series = self._active_sports_series()
            if series:
                from api.modules.sports_sweep import data as sports_data
                for g in sports_data.live_games(series):
                    for s in g["sides"]:
                        quotes[s["token"]] = {"best_bid": s["best_bid"],
                                              "best_ask": s["best_ask"]}
        except Exception:
            log.exception("sports quote fetch failed")
        # GENERIC coverage (2026-07-24): any resting paper order whose token is NOT
        # already covered above - NO-token fades (elon_reversion), complement-pair
        # legs (elon_late_arb), arbitrary market tokens (copytrader/mirror). Without
        # this the paper fill sim has NO price for those orders and they can NEVER
        # fill. Fetch the live CLOB book per uncovered token so EVERY module's orders
        # can actually fill. The engine stays module-agnostic - it fills whatever is
        # resting, not a hardcoded token list.
        try:
            sb = get_supabase()
            rows = (sb.table("orders").select("token_id").eq("executor", "paper")
                    .in_("status", ["open", "partially_filled"]).execute().data) or []
            need = {r["token_id"] for r in rows
                    if r.get("token_id") and r["token_id"] not in quotes}
            for tok in need:
                top = self._clob_top(tok)
                if top:
                    quotes[tok] = top
        except Exception:
            log.exception("open-order quote fetch failed")
        return quotes

    @staticmethod
    def _clob_top(token_id: str) -> dict | None:
        """Live top-of-book {best_bid, best_ask} for one token from the CLOB."""
        import httpx
        from api.services.polymarket_proxy import clob_base, proxy_headers
        try:
            r = httpx.get(f"{clob_base()}/book", params={"token_id": token_id},
                          headers=proxy_headers(), timeout=10)
            r.raise_for_status()
            b = r.json() or {}
            bids = b.get("bids") or []; asks = b.get("asks") or []
            bb = max((float(x["price"]) for x in bids), default=None)
            ba = min((float(x["price"]) for x in asks), default=None)
            if bb is None and ba is None:
                return None
            return {"best_bid": bb, "best_ask": ba}
        except Exception:
            return None

    def _active_sports_series(self) -> list[int]:
        """Union of series_ids configured on any non-inactive sports_sweep
        module row (so paper fills cover exactly what it trades)."""
        mod = self.registry.get("sports_sweep")
        if mod is None:
            return []
        sb = get_supabase()
        rows = (sb.table("modules").select("id,status").eq("strategy", "sports_sweep")
                .neq("status", "inactive").execute().data) or []
        series: set[int] = set()
        for r in rows:
            try:
                cfg = mod.get_config(r["id"])
                series.update(int(s) for s in cfg.get("series_ids", []))
            except Exception:
                pass
        return sorted(series)

    def _write_price_snapshots(self) -> None:
        """One mid-price row per live bracket per hour (upsert on the
        unique (module_id, bracket, snapshot_hour) index; module_id NULL =
        market-level snapshot shared by all modules)."""
        from api.modules.shared import discovery
        sb = get_supabase()
        hour = datetime.now(timezone.utc).replace(minute=0, second=0,
                                                  microsecond=0)
        rows = []
        for a in discovery.fetch_tweet_auctions():
            for b in a["brackets"]:
                bid, ask = b["best_bid"], b["best_ask"]
                if bid is None and ask is None:
                    continue
                mid = (bid + ask) / 2 if bid is not None and ask is not None else (bid or ask)
                rows.append({
                    "module_id": None,
                    "bracket": f"{a['slug']}|{b['label']}",
                    "price": round(mid, 4),
                    "snapshot_hour": hour.isoformat(),
                    "dow": hour.weekday(),
                    "hour_of_day": hour.hour,
                })
        if rows:
            sb.table("price_snapshots").upsert(
                rows, on_conflict="module_id,bracket,snapshot_hour",
                ignore_duplicates=True).execute()

    def _breaker_tripped(self, sb) -> bool:
        s = get_settings()
        if not s.circuit_breaker_enabled:
            return False
        from api.services.breaker import is_tripped
        return is_tripped()
