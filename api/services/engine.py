import asyncio
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from api.services.risk_manager import RiskManager
from api.services.executor import PaperExecutor, LiveExecutor, MultiExecutor
from api.services.exit_manager import check_exits, execute_exits
from api.services.walk_forward import run_walk_forward_check
from api.services.resolution_tracker import check_resolutions
from api.modules import ModuleRegistry
from api.config import get_settings
from api.dependencies import get_supabase
import logging

log = logging.getLogger(__name__)

STALE_DATA_THRESHOLD_HOURS = 2


class TradingEngine:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.risk_manager = RiskManager()
        self.registry = ModuleRegistry()
        self._running = False
        self._cycle_count = 0
        self._multi_mode = False
        self._stale_data = False

    def start(self, interval: int = 300):
        if self._running:
            return
        settings = get_settings()

        if settings.paper_mode:
            self.executor = PaperExecutor()
            self._multi_mode = False
        else:
            from api.services.profiles import get_multi_exec_profiles
            multi_profiles = get_multi_exec_profiles()
            if len(multi_profiles) > 1:
                self.executor = MultiExecutor(multi_profiles)
                self._multi_mode = True
                log.info(f"Multi-account mode: broadcasting to {[p['name'] for p in multi_profiles]}")
            else:
                self.executor = LiveExecutor()
                self._multi_mode = False

        self.shadow_executor = PaperExecutor() if settings.shadow_mode else None
        self.registry.discover()
        self.scheduler.add_job(self._run_cycle, "interval", seconds=interval, max_instances=1)
        self.scheduler.add_job(self._run_walk_forward, "interval", hours=6, max_instances=1)
        self.scheduler.add_job(self._run_resolutions, "interval", minutes=30, max_instances=1)
        self.scheduler.start()
        self._running = True
        log.info(f"Engine started: interval={interval}s, paper={settings.paper_mode}, shadow={settings.shadow_mode}, multi={self._multi_mode}")

    def stop(self):
        if not self._running:
            return
        self.scheduler.shutdown(wait=False)
        self._running = False
        log.info(f"Engine stopped after {self._cycle_count} cycles")

    def reload_executors(self):
        settings = get_settings()
        if settings.paper_mode:
            return

        from api.services.profiles import get_multi_exec_profiles
        multi_profiles = get_multi_exec_profiles()
        if len(multi_profiles) > 1:
            self.executor = MultiExecutor(multi_profiles)
            self._multi_mode = True
            log.info(f"Reloaded multi-account: {[p['name'] for p in multi_profiles]}")
        else:
            self.executor = LiveExecutor()
            self._multi_mode = False
            log.info("Reloaded single-account executor")

    def _check_data_freshness(self) -> bool:
        try:
            sb = get_supabase()
            result = sb.table("signals").select("created_at").order("created_at", desc=True).limit(1).execute()
            if not result.data:
                self._stale_data = True
                return False
            last_ts = result.data[0]["created_at"]
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            self._stale_data = age_hours > STALE_DATA_THRESHOLD_HOURS
            return not self._stale_data
        except Exception:
            self._stale_data = True
            return False

    def _run_exits(self):
        try:
            sb = get_supabase()
            positions = sb.table("positions").select("*").eq("status", "open").execute()
            if not positions.data:
                return
            exits = check_exits(positions.data)
            if exits:
                positions_by_id = {p["id"]: p for p in positions.data}
                results = execute_exits(exits, positions_by_id, self.executor)
                for r in results:
                    log.info(f"Exit executed: {r['reason']} pnl={r.get('pnl', 0):.4f}")
        except Exception as e:
            log.error(f"Exit check error: {e}")

    def _run_cycle(self):
        self._cycle_count += 1
        if self.risk_manager.circuit_breaker_tripped:
            log.warning("Circuit breaker tripped — skipping cycle")
            return

        if not self._check_data_freshness():
            log.warning(f"Stale data detected (>{STALE_DATA_THRESHOLD_HOURS}h) — skipping cycle")
            return

        self._sync_risk_state()
        self._run_exits()

        for module in self.registry.active_modules():
            try:
                signals = module.evaluate()
                for signal in signals:
                    approved, reason = self.risk_manager.check(signal)
                    if approved:
                        result = self.executor.execute(signal)
                        if self.shadow_executor:
                            self.shadow_executor.execute(signal)

                        self._log_execution(signal, result)
                    else:
                        log.info(f"Signal rejected: {reason}")
                        self._log_rejection(signal, reason)
            except Exception as e:
                log.error(f"Module {module.name} error: {e}")
                self._log_error(module.name, str(e))

    def _run_resolutions(self):
        try:
            check_resolutions(risk_manager=self.risk_manager)
        except Exception as e:
            log.error(f"Resolution check error: {e}")

    def _run_walk_forward(self):
        sb = get_supabase()
        modules = sb.table("modules").select("id").eq("status", "active").execute()
        for m in modules.data:
            try:
                result = run_walk_forward_check(m["id"])
                if not result["valid"] and result.get("kelly_multiplier"):
                    log.warning(f"Walk-forward: reducing kelly for module {m['id']}")
            except Exception as e:
                log.error(f"Walk-forward error for {m['id']}: {e}")

    def _sync_risk_state(self):
        try:
            sb = get_supabase()
            pnl_rows = sb.table("daily_pnl").select("portfolio_value,daily_return,total_pnl").order("date", desc=True).limit(7).execute()
            if pnl_rows.data:
                latest = pnl_rows.data[0]
                daily = latest.get("daily_return", 0) * latest.get("portfolio_value", 1000)
                weekly = sum(r.get("daily_return", 0) * r.get("portfolio_value", 1000) for r in pnl_rows.data)
                values = [r["portfolio_value"] for r in pnl_rows.data]
                peak = max(values) if values else 1000
                current = values[0] if values else 1000
                self.risk_manager.update_pnl(daily, weekly, peak, current)
        except Exception as e:
            log.error(f"Risk state sync failed — loss limits may be stale: {e}")

    def _log_execution(self, signal, result):
        try:
            sb = get_supabase()
            metadata = {"edge": signal.edge, "kelly": signal.kelly_pct}
            if isinstance(result, dict) and result.get("multi"):
                metadata["multi_exec"] = True
                metadata["succeeded"] = result["succeeded"]
                metadata["failed"] = result["failed"]
                metadata["profiles"] = list(result["results"].keys())
            else:
                metadata["order_id"] = result.get("id") if isinstance(result, dict) else None

            msg = f"Executed {signal.side} {signal.bracket} @ {signal.market_price:.4f}"
            if isinstance(result, dict) and result.get("multi"):
                msg += f" (multi: {result['succeeded']}/{result['total']} ok)"

            sb.table("logs").insert({
                "log_type": "execution",
                "severity": "info",
                "module_id": signal.module_id,
                "message": msg,
                "metadata": metadata,
            }).execute()
        except Exception:
            pass

    def _log_rejection(self, signal, reason):
        try:
            sb = get_supabase()
            sb.table("logs").insert({
                "log_type": "risk",
                "severity": "info",
                "module_id": signal.module_id,
                "message": f"Rejected {signal.side} {signal.bracket}: {reason}",
                "metadata": {"edge": signal.edge, "kelly": signal.kelly_pct, "reason": reason},
            }).execute()
        except Exception:
            pass

    def _log_error(self, module_name, error_msg):
        try:
            sb = get_supabase()
            sb.table("logs").insert({
                "log_type": "system",
                "severity": "error",
                "message": f"Module {module_name} error: {error_msg}",
            }).execute()
        except Exception:
            pass

    @property
    def status(self):
        s = {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "active_modules": len(self.registry.active_modules()),
            "circuit_breaker": self.risk_manager.circuit_breaker_tripped,
            "multi_account": self._multi_mode,
            "stale_data": self._stale_data,
        }
        if self._multi_mode and isinstance(self.executor, MultiExecutor):
            s["multi_profiles"] = self.executor.profile_names
        return s


engine = TradingEngine()
