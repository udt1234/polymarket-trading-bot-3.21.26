import asyncio
import time
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from api.services.risk_manager import RiskManager
from api.services.executor import PaperExecutor, LiveExecutor, MultiExecutor
from api.services.exit_manager import check_exits, execute_exits, release_stuck_closing_positions
from api.services.walk_forward import run_walk_forward_check
from api.services.resolution_tracker import check_resolutions
from api.modules import ModuleRegistry
from api.config import get_settings
from api.dependencies import get_supabase
import logging

log = logging.getLogger(__name__)

STALE_DATA_THRESHOLD_HOURS = 2


def _run_async(coro):
    """Run an async coroutine from a sync context (e.g. APScheduler thread).

    Python 3.12+ stopped auto-creating a default event loop in non-main threads,
    so the previous `asyncio.get_event_loop().run_until_complete(coro)` raised
    RuntimeError and silently broke every snapshot job. Use asyncio.run() which
    creates a fresh loop for this thread. BLOCKS the caller until coro finishes
    — only use when you actually need the result.
    """
    return asyncio.run(coro)


def _fire_and_forget_async(coro):
    """Run an async coroutine in a background daemon thread without blocking.

    Use this for notifications, alerts, and any side-effect-only async call
    where the engine cycle MUST NOT stall waiting on the result. Caught a
    real bug where a tripped circuit breaker fired notify_circuit_breaker
    + notify_bot_paused via _run_async, blocking the engine for up to 20s
    on slow Slack POSTs (each httpx call has a 10s timeout).
    """
    import threading
    def _runner():
        try:
            asyncio.run(coro)
        except Exception as e:
            log.warning(f"fire-and-forget async task failed: {e}")
    threading.Thread(target=_runner, daemon=True).start()


class TradingEngine:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.risk_manager = RiskManager()
        self.registry = ModuleRegistry()
        self._running = False
        self._cycle_count = 0
        self._multi_mode = False
        self._stale_data = False
        # Tracker state — initialized here so it always exists, even if a
        # tracker method is called before _run_cycle has run once. Prior
        # `if not hasattr(self, ...)` guards inside the methods could create
        # ambiguous list identities if called from different code paths.
        self._recent_rejections: list[dict] = []
        # (timestamp, module_name, signature, sample) — module_name lets the
        # dashboard show per-module health instead of painting every page red
        # when only one module's data feed is sick.
        self._recent_errors: list[tuple[float, str, str, str]] = []

    def start(self, interval: int = 300):
        if self._running:
            return
        settings = get_settings()

        if settings.paper_mode or settings.environment != "production":
            self.executor = PaperExecutor()
            self._multi_mode = False
            if not settings.paper_mode and settings.environment != "production":
                log.warning("PAPER_MODE=false but ENV != production — forcing paper mode")
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
        self.scheduler.add_job(self._run_auction_monitor, "interval", hours=1, max_instances=1)
        self.scheduler.add_job(self._run_order_ttl_sweep, "interval", minutes=5, max_instances=1)
        self.scheduler.add_job(self._run_order_book_snapshot, "interval", minutes=5, max_instances=1)
        self.scheduler.add_job(self._run_post_count_snapshot, "interval", minutes=5, max_instances=1)
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
                self._stale_data = False
                log.info("No signals yet — allowing cycle to bootstrap")
                return True
            last_ts = result.data[0]["created_at"]
            last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            self._stale_data = age_hours > STALE_DATA_THRESHOLD_HOURS
            if self._stale_data:
                log.info(f"Last signal {age_hours:.1f}h old — allowing cycle (stale flag set for dashboard)")
            return True
        except Exception:
            self._stale_data = True
            return False

    def _run_exits(self):
        try:
            # First: rescue any positions stuck in 'closing' from a prior
            # crashed exit cycle (claim succeeded, order placement died).
            release_stuck_closing_positions()

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

        # Exits run UNCONDITIONALLY — must fire even when the circuit breaker is
        # tripped or data is stale, otherwise an open losing position keeps
        # bleeding for the entire cooldown window (audit finding 2026-04-28).
        # Risk state sync also runs always so loss-cap math stays current.
        self._sync_risk_state()
        self._run_exits()

        if self.risk_manager.circuit_breaker_tripped:
            log.warning("Circuit breaker tripped — exits ran, skipping new entries this cycle")
            return

        if not self._check_data_freshness():
            log.warning(f"Stale data detected (>{STALE_DATA_THRESHOLD_HOURS}h) — exits ran, skipping new entries this cycle")
            # Fire stale-data alert. Cooldown inside notify_stale_data prevents
            # spam if it stays stale for hours.
            try:
                from api.services.alerts import notify_stale_data
                _fire_and_forget_async(notify_stale_data(handle="all", hours=STALE_DATA_THRESHOLD_HOURS, source="signals"))
            except Exception:
                pass
            return

        self._process_pending_signals()

        # _recent_rejections / _recent_errors are now initialized in __init__.
        for module in self.registry.active_modules():
            try:
                signals = module.evaluate()
                for signal in signals:
                    if self._maybe_defer_signal(module, signal):
                        continue
                    approved, reason = self.risk_manager.check(signal)
                    if approved:
                        # Reset rejection streak on a successful approval
                        self._recent_rejections = []
                        result = self.executor.execute(signal)
                        if result.get("status") == "rejected":
                            log.info(f"Executor rejected: {result.get('reason')}")
                            self._log_rejection(signal, result.get("reason", "executor_rejected"))
                            self._track_rejection(module.name, getattr(signal, "module_id", ""), result.get("reason", "executor_rejected"))
                            continue
                        if self.shadow_executor:
                            self.shadow_executor.execute(signal)

                        self._log_execution(signal, result)
                        try:
                            from api.services.notifications import notify_trade_executed
                            _fire_and_forget_async(
                                notify_trade_executed(signal.side, signal.bracket, result.get("size", 0), result.get("price", 0), result.get("executor", "paper"))
                            )
                        except Exception:
                            pass
                    else:
                        log.info(f"Signal rejected: {reason}")
                        self._log_rejection(signal, reason)
                        self._track_rejection(module.name, getattr(signal, "module_id", ""), reason)
            except Exception as e:
                log.error(f"Module {module.name} error: {e}")
                self._log_error(module.name, str(e))
                # Repeated-error alert: track unique error signatures.
                self._track_error(module.name, str(e))

    def _maybe_defer_signal(self, module, signal) -> bool:
        """Check if signal should be deferred based on historical price patterns."""
        try:
            from api.modules.shared.price_timing import should_defer_signal
            mod_cfg = self._get_module_cfg(module, signal.module_id)
            if not mod_cfg.get("wait_for_dip_enabled", False):
                return False
            meta = signal.metadata or {}
            elapsed_days = float(meta.get("elapsed_days", 0) or 0)
            total_days = float(meta.get("total_days", 7) or 7)
            if total_days <= 0:
                return False
            elapsed_hours = elapsed_days * 24.0
            total_hours = total_days * 24.0
            now = datetime.now(timezone.utc)
            defer = should_defer_signal(
                module_id=signal.module_id,
                bracket=signal.bracket,
                current_price=signal.market_price,
                elapsed_hours=elapsed_hours,
                total_hours=total_hours,
                dow=now.weekday(),
                hour_of_day=now.hour,
                slug=signal.market_id,
                min_drop_threshold=float(mod_cfg.get("wait_min_drop_threshold", 0.05)),
                max_wait_days=float(mod_cfg.get("wait_max_days", 3.0)),
            )
            if not defer:
                return False
            self._insert_pending_signal(signal, defer)
            log.info(f"Deferred {signal.side} {signal.bracket}: expected {defer['expected_drop_pct']*100:.1f}% drop in {defer['wait_hours']}h, target={defer['target_price']}")
            return True
        except Exception as e:
            log.error(f"Defer check failed for {signal.bracket}: {e}")
            return False

    def _get_module_cfg(self, module, module_id: str) -> dict:
        # Dispatch by the BaseModule.name field (canonical), not a name substring,
        # so a module with "spike" in its display name doesn't get misrouted.
        try:
            name = getattr(module, "name", "")
            if name == "spike_rider":
                from api.modules.spike_rider.module_config import get_module_config as get_spike_cfg
                return get_spike_cfg(module_id)
            if name == "elon_tweets":
                from api.modules.elon_tweets.module_config import get_module_config as get_elon_cfg
                return get_elon_cfg(module_id)
            if name == "truth_social":
                from api.modules.truth_social.module_config import get_module_config
                return get_module_config(module_id)
        except Exception:
            pass
        return {}

    def _insert_pending_signal(self, signal, defer: dict):
        try:
            sb = get_supabase()
            sb.table("pending_signals").insert({
                "module_id": signal.module_id,
                "market_id": signal.market_id,
                "bracket": signal.bracket,
                "side": signal.side,
                "original_price": signal.market_price,
                "target_price": defer["target_price"],
                "wait_until": defer["wait_until"],
                "abandon_if_price_above": defer["abandon_price"],
                "model_prob": signal.model_prob,
                "original_kelly_pct": signal.kelly_pct,
                "expected_drop_pct": defer["expected_drop_pct"],
                "analog_count": defer["analog_count"],
                "signal_metadata": signal.metadata or {},
                "status": "waiting",
            }).execute()
        except Exception as e:
            log.error(f"Failed to insert pending signal: {e}")

    def _process_pending_signals(self):
        """Check all waiting pending signals; execute, abandon, or keep waiting."""
        try:
            sb = get_supabase()
            res = sb.table("pending_signals").select("*").eq("status", "waiting").execute()
            pending = res.data or []
            if not pending:
                return

            from api.modules.shared.polymarket import fetch_market_prices
            from api.services.risk_manager import Signal

            now = datetime.now(timezone.utc)
            prices_cache: dict = {}

            for p in pending:
                slug = p.get("market_id")
                bracket = p.get("bracket")
                target = float(p.get("target_price") or 0)
                abandon = float(p.get("abandon_if_price_above") or 1)
                wait_until_str = p.get("wait_until") or ""
                try:
                    wait_until = datetime.fromisoformat(wait_until_str.replace("Z", "+00:00"))
                except Exception:
                    wait_until = now

                if slug not in prices_cache:
                    try:
                        prices_cache[slug] = _run_async(fetch_market_prices(slug))
                    except Exception as e:
                        log.warning(f"Failed to fetch prices for pending signal on {slug}: {e}")
                        continue
                prices = prices_cache.get(slug) or {}
                current_price = float(prices.get(bracket, 0) or 0)
                if current_price <= 0 or current_price >= 1:
                    continue

                if current_price >= abandon:
                    sb.table("pending_signals").update({
                        "status": "abandoned",
                        "resolved_at": now.isoformat(),
                    }).eq("id", p["id"]).execute()
                    log.info(f"Pending signal abandoned: {bracket} surged to {current_price:.4f} >= {abandon:.4f}")
                    continue

                price_hit_target = current_price <= target
                wait_expired = now >= wait_until

                if not price_hit_target and not wait_expired:
                    continue

                sig = Signal(
                    module_id=p["module_id"],
                    market_id=slug,
                    bracket=bracket,
                    side=p.get("side", "BUY"),
                    edge=float(p.get("model_prob") or 0) - current_price,
                    model_prob=float(p.get("model_prob") or 0),
                    market_price=current_price,
                    kelly_pct=float(p.get("original_kelly_pct") or 0),
                    metadata=p.get("signal_metadata") or {},
                )
                approved, reason = self.risk_manager.check(sig)
                new_status = "executed" if approved else "rejected_on_unlock"
                if approved:
                    try:
                        result = self.executor.execute(sig)
                        if result.get("status") == "rejected":
                            new_status = "rejected_on_unlock"
                        else:
                            self._log_execution(sig, result)
                            log.info(f"Pending signal executed: {bracket} @ {current_price:.4f} (reason: {'target_hit' if price_hit_target else 'expired'})")
                    except Exception as e:
                        log.error(f"Pending execution failed: {e}")
                        new_status = "rejected_on_unlock"
                else:
                    log.info(f"Pending signal rejected on unlock: {reason}")

                sb.table("pending_signals").update({
                    "status": new_status,
                    "resolved_at": now.isoformat(),
                }).eq("id", p["id"]).execute()
        except Exception as e:
            log.error(f"Pending signals processor error: {e}")

    def _run_order_book_snapshot(self):
        try:
            import asyncio as _asyncio
            from api.modules.shared.polymarket import fetch_order_books_for_brackets
            sb = get_supabase()
            modules = sb.table("modules").select("id,market_slug").in_("status", ["active", "paused"]).execute()
            now = datetime.now(timezone.utc).isoformat()
            total = 0
            for m in modules.data or []:
                slug = m.get("market_slug")
                if not slug:
                    continue
                bracket_set: set[str] = set()
                # Brackets where we hold open positions — must always have order book data
                open_pos = sb.table("positions").select("bracket").eq("module_id", m["id"]).eq("status", "open").execute()
                for p in (open_pos.data or []):
                    if p.get("bracket"):
                        bracket_set.add(p["bracket"])
                # Brackets with recent signal activity
                recent_signals = sb.table("signals").select("bracket").eq("module_id", m["id"]).order("created_at", desc=True).limit(50).execute()
                for s in (recent_signals.data or []):
                    if s.get("bracket"):
                        bracket_set.add(s["bracket"])
                # Fallback when nothing fresh: pull all brackets ever seen in signals so chart isn't empty
                if not bracket_set:
                    all_signals = sb.table("signals").select("bracket").eq("module_id", m["id"]).limit(500).execute()
                    for s in (all_signals.data or []):
                        if s.get("bracket"):
                            bracket_set.add(s["bracket"])
                brackets = list(bracket_set)
                if not brackets:
                    continue
                try:
                    books = _run_async(fetch_order_books_for_brackets(slug, brackets))
                except Exception as e:
                    log.warning(f"Order book snapshot fetch failed for {slug}: {e}")
                    continue
                rows = []
                for bracket, book in (books or {}).items():
                    rows.append({
                        "module_id": m["id"],
                        "market_id": slug,
                        "bracket": bracket,
                        "best_bid": book.get("best_bid"),
                        "best_ask": book.get("best_ask"),
                        "spread": book.get("spread"),
                        "bid_depth_5": book.get("bid_depth_5"),
                        "ask_depth_5": book.get("ask_depth_5"),
                        "midpoint": book.get("midpoint"),
                        "snapshot_at": now,
                    })
                if rows:
                    sb.table("order_book_snapshots").insert(rows).execute()
                    total += len(rows)
            if total:
                log.info(f"Order book snapshot: captured {total} rows")
        except Exception as e:
            log.error(f"Order book snapshot error: {e}")

    def _run_post_count_snapshot(self):
        try:
            import asyncio as _asyncio
            from datetime import datetime as _dt
            from api.modules.shared.polymarket import fetch_active_tracking, fetch_xtracker_stats, get_xtracker_summary, parse_hourly_counts, compute_running_total
            from api.modules.truth_social.truthsocial_direct import count_posts_in_window

            sb = get_supabase()
            modules = sb.table("modules").select("id,name").in_("status", ["active", "paused", "paper"]).execute()
            now_iso = datetime.now(timezone.utc).isoformat()
            rows = []

            for m in modules.data or []:
                name = (m.get("name") or "").lower()
                if "trump" in name or "truth" in name:
                    handle = "realDonaldTrump"
                elif "elon" in name:
                    handle = "elonmusk"
                else:
                    continue

                try:
                    tracking = _run_async(fetch_active_tracking(handle))
                except Exception as e:
                    log.warning(f"Post count snapshot: tracking fetch failed for {handle}: {e}")
                    continue
                if not tracking:
                    continue

                tid = str(tracking.get("id") or tracking.get("trackingId") or "")
                ws = tracking.get("startDate", "")
                we = tracking.get("endDate", "")

                try:
                    raw = _run_async(fetch_xtracker_stats(tid)) if tid else {}
                    summary = get_xtracker_summary(raw)
                    hourly = parse_hourly_counts(raw)
                    xt_count = summary.get("total", 0) or compute_running_total(hourly, ws)
                    rows.append({
                        "module_id": m["id"],
                        "source": "xtracker",
                        "tracking_id": tid,
                        "window_start": ws or None,
                        "window_end": we or None,
                        "count": int(xt_count) if xt_count is not None else None,
                        "latest_post_at": hourly[-1].get("date") if hourly else None,
                        "captured_at": now_iso,
                    })
                except Exception as e:
                    log.warning(f"xTracker snapshot failed for {handle}: {e}")
                    rows.append({
                        "module_id": m["id"], "source": "xtracker", "tracking_id": tid,
                        "window_start": ws or None, "window_end": we or None,
                        "count": None, "error": str(e)[:200], "captured_at": now_iso,
                    })

                if handle == "realDonaldTrump" and ws and we:
                    try:
                        w_start = _dt.fromisoformat(ws.replace("Z", "+00:00"))
                        w_end = _dt.fromisoformat(we.replace("Z", "+00:00"))
                        w_end_capped = min(w_end, datetime.now(timezone.utc))
                        # 15s timeout — Cloudflare rate-limit responses can stall the call indefinitely.
                        # Insert a row even on timeout so the divergence chart shows the gap explicitly.
                        ts_result = _run_async(
                            _asyncio.wait_for(
                                count_posts_in_window(w_start, w_end_capped, handle=handle),
                                timeout=15.0,
                            )
                        )
                        rows.append({
                            "module_id": m["id"],
                            "source": "truthsocial_direct",
                            "tracking_id": tid,
                            "window_start": ws,
                            "window_end": we,
                            "count": ts_result.get("count"),
                            "latest_post_at": ts_result.get("latest_post_at"),
                            "error": ts_result.get("error"),
                            "captured_at": now_iso,
                        })
                    except _asyncio.TimeoutError:
                        log.warning("Truth Social direct snapshot timed out (>15s)")
                        rows.append({
                            "module_id": m["id"], "source": "truthsocial_direct", "tracking_id": tid,
                            "window_start": ws, "window_end": we,
                            "count": None, "error": "timeout", "captured_at": now_iso,
                        })
                    except Exception as e:
                        log.warning(f"Truth Social direct snapshot failed: {e}")
                        rows.append({
                            "module_id": m["id"], "source": "truthsocial_direct", "tracking_id": tid,
                            "window_start": ws, "window_end": we,
                            "count": None, "error": str(e)[:200], "captured_at": now_iso,
                        })

            if rows:
                sb.table("post_count_snapshots").insert(rows).execute()
                log.info(f"Post count snapshot: captured {len(rows)} rows ({sum(1 for r in rows if r.get('count') is not None)} with data)")
        except Exception as e:
            log.error(f"Post count snapshot error: {e}")

    def _run_order_ttl_sweep(self):
        ORDER_TTL_MINUTES = 5
        try:
            sb = get_supabase()
            cutoff = datetime.now(timezone.utc).replace(microsecond=0)
            from datetime import timedelta
            cutoff = (cutoff - timedelta(minutes=ORDER_TTL_MINUTES)).isoformat()
            stale = sb.table("orders").select("id").in_("status", ["submitted", "live"]).lt("created_at", cutoff).execute()
            if stale.data:
                ids = [o["id"] for o in stale.data]
                for oid in ids:
                    sb.table("orders").update({"status": "cancelled"}).eq("id", oid).execute()
                log.info(f"Order TTL sweep: cancelled {len(ids)} stale orders older than {ORDER_TTL_MINUTES}min")
        except Exception as e:
            log.error(f"Order TTL sweep error: {e}")

    def _run_resolutions(self):
        try:
            check_resolutions(risk_manager=self.risk_manager)
        except Exception as e:
            log.error(f"Resolution check error: {e}")

    def _run_auction_monitor(self):
        try:
            import asyncio
            from api.modules.shared.polymarket import _fetch_trackings_raw
            from api.services.notifications import notify_auction_gap, notify_new_auction

            sb = get_supabase()
            modules = sb.table("modules").select("id,name,market_slug").in_("status", ["active", "paused", "paper"]).execute()
            handles = {"Truth Social": "realDonaldTrump", "Elon": "elonmusk"}

            for mod in (modules.data or []):
                name = mod.get("name", "")
                handle = None
                for key, h in handles.items():
                    if key.lower() in name.lower():
                        handle = h
                        break
                if not handle:
                    continue

                trackings = _run_async(_fetch_trackings_raw(handle))
                if not trackings:
                    continue

                now = datetime.now(timezone.utc)
                active = []
                most_recent_end = None
                for t in trackings:
                    start_str = t.get("startDate", "")
                    end_str = t.get("endDate", "")
                    if not start_str or not end_str:
                        continue
                    s = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    e = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    if s <= now <= e:
                        active.append(t)
                    if most_recent_end is None or e > most_recent_end:
                        most_recent_end = e

                if not active and most_recent_end:
                    gap_hours = (now - most_recent_end).total_seconds() / 3600
                    if gap_hours > 2:
                        _fire_and_forget_async(
                            notify_auction_gap(handle, most_recent_end.strftime("%Y-%m-%d %H:%M"), gap_hours)
                        )
                        log.warning(f"Auction gap for {handle}: {gap_hours:.0f}h since last auction ended")

                known_ids = set()
                try:
                    known_rows = sb.table("logs").select("metadata").eq("log_type", "system").like("message", "%New Auction%").execute()
                    for row in (known_rows.data or []):
                        meta = row.get("metadata") or {}
                        if meta.get("tracking_id"):
                            known_ids.add(str(meta["tracking_id"]))
                except Exception:
                    pass

                for t in active:
                    tid = str(t.get("id") or t.get("trackingId") or "")
                    if tid and tid not in known_ids:
                        _fire_and_forget_async(
                            notify_new_auction(handle, t.get("title", ""), t.get("startDate", "")[:10], t.get("endDate", "")[:10])
                        )
                        sb.table("logs").insert({
                            "log_type": "system", "severity": "info", "module_id": mod["id"],
                            "message": f"New Auction: {t.get('title', '')}",
                            "metadata": {"tracking_id": tid, "handle": handle},
                        }).execute()

        except Exception as e:
            log.error(f"Auction monitor error: {e}")

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

    def _track_rejection(self, module_name: str, module_id: str, reason: str):
        """Append to in-memory rejection streak. Fires rejection_spike alert
        when 5+ rejections accumulate without an intervening approval. The
        alert dispatcher dedupes so we don't ping every additional rejection."""
        self._recent_rejections.append({
            "module_name": module_name,
            "module_id": module_id,
            "reason": reason,
        })
        # Keep at most last 20 to bound memory
        if len(self._recent_rejections) > 20:
            self._recent_rejections = self._recent_rejections[-20:]
        if len(self._recent_rejections) >= 5:
            try:
                from api.services.alerts import notify_rejection_spike
                from collections import Counter
                reasons = Counter(r["reason"] for r in self._recent_rejections[-10:]).most_common(3)
                top = [f"{r} ({c}x)" for r, c in reasons]
                _fire_and_forget_async(notify_rejection_spike(
                    module_id=module_id,
                    module_name=module_name,
                    count=len(self._recent_rejections),
                    top_reasons=top,
                ))
            except Exception:
                pass

    def _track_error(self, module_name: str, error_msg: str):
        """Track repeated errors over a 15-min sliding window per signature."""
        # Use first 80 chars of error as signature (drops timestamps, addresses, etc).
        sig = (error_msg or "")[:80].strip()
        now_ts = time.time()
        self._recent_errors.append((now_ts, module_name, sig, error_msg or ""))
        # Drop entries older than 15 min
        cutoff = now_ts - 15 * 60
        self._recent_errors = [e for e in self._recent_errors if e[0] >= cutoff]
        # Count occurrences of this signature (across modules — alert dedupe is global)
        same_count = sum(1 for e in self._recent_errors if e[2] == sig)
        if same_count >= 3:
            try:
                from api.services.alerts import notify_repeated_errors
                _fire_and_forget_async(notify_repeated_errors(
                    error_signature=f"[{module_name}] {sig}",
                    count=same_count,
                    time_window_minutes=15.0,
                    sample=error_msg,
                ))
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

    @property
    def health(self):
        """Bot health snapshot for the dashboard banner.

        Returns: { state: 'trading'|'watching'|'paused'|'killed',
                   reason: str, details: {...} }
        """
        if not self._running:
            return {
                "state": "paused",
                "reason": "Engine stopped",
                "details": {"action": "Use /api/engine/start to resume"},
            }
        if self.risk_manager.circuit_breaker_tripped:
            cooldown_remaining_s = max(0, int(self.risk_manager._cooldown_until - time.time()))
            return {
                "state": "paused",
                "reason": "Circuit breaker tripped",
                "details": {
                    "consecutive_losses": self.risk_manager.consecutive_losses,
                    "cooldown_remaining_min": round(cooldown_remaining_s / 60, 1),
                },
            }
        if self._stale_data:
            return {
                "state": "paused",
                "reason": "Stale data — xTracker hasn't refreshed",
                "details": {"threshold_hours": STALE_DATA_THRESHOLD_HOURS},
            }
        active = self.registry.active_modules()
        if not active:
            return {
                "state": "paused",
                "reason": "No active modules",
                "details": {"action": "Resume modules from the dashboard"},
            }
        # Degraded state: if module evaluation has been throwing errors in the
        # last 15 min, the bot isn't actually trading even though the engine
        # is "running". Surface that explicitly so the operator can investigate
        # rather than the badge silently saying "trading".
        recent_errors = self._recent_errors
        if recent_errors:
            err_count = len(recent_errors)
            # _recent_errors is (ts, module_name, signature, sample). Show the most-recent signature.
            latest_sig = recent_errors[-1][2] if recent_errors else "unknown"
            return {
                "state": "paused",
                "reason": f"Degraded — {err_count} recent error{'s' if err_count != 1 else ''} from module evaluation",
                "details": {
                    "latest_error": latest_sig[:100],
                    "window_minutes": 15,
                    "active_modules": len(active),
                },
            }
        # Look at most recent module evaluation outcome to distinguish trading vs watching.
        # If every recent module is in TRANSITION and produced 0 signals, we're watching.
        try:
            sb = get_supabase()
            recent = sb.table("logs").select("message,created_at").eq("log_type", "decision").order("created_at", desc=True).limit(20).execute()
            rows = recent.data or []
            cycle_rows = [r for r in rows if (r.get("message") or "").startswith("Cycle:")]
            in_transition = any("regime=TRANSITION" in (r.get("message") or "") for r in cycle_rows[:3])
            zero_signals = all("signals=0" in (r.get("message") or "") for r in cycle_rows[:3])
            if cycle_rows and in_transition and zero_signals:
                return {
                    "state": "watching",
                    "reason": "Regime in transition — bot waiting for trend to clear",
                    "details": {"active_modules": len(active)},
                }
        except Exception:
            pass
        return {
            "state": "trading",
            "reason": "Bot is actively scanning markets",
            "details": {"active_modules": len(active), "cycle_count": self._cycle_count},
        }

    def health_for_module(self, module_name: str) -> dict:
        """Per-module health. Global engine state (stopped, circuit breaker,
        stale data) still applies to every module — but recent errors are
        scoped so one module's hiccup doesn't paint every page red.
        """
        if not self._running:
            return {"state": "paused", "reason": "Engine stopped",
                    "details": {"action": "Use /api/engine/start to resume"}}
        if self.risk_manager.circuit_breaker_tripped:
            cooldown_remaining_s = max(0, int(self.risk_manager._cooldown_until - time.time()))
            return {"state": "paused", "reason": "Circuit breaker tripped",
                    "details": {"consecutive_losses": self.risk_manager.consecutive_losses,
                                "cooldown_remaining_min": round(cooldown_remaining_s / 60, 1)}}
        if self._stale_data:
            return {"state": "paused", "reason": "Stale data — xTracker hasn't refreshed",
                    "details": {"threshold_hours": STALE_DATA_THRESHOLD_HOURS}}

        # Match errors by module name — registry uses the module's `name` attr
        # but the dashboard sometimes passes the human-friendly DB name. Match
        # on case-insensitive substring in either direction so both work.
        key = (module_name or "").lower().strip()
        my_errors = [
            e for e in self._recent_errors
            if key and (key in (e[1] or "").lower() or (e[1] or "").lower() in key)
        ]
        if my_errors:
            err_count = len(my_errors)
            latest_sig = my_errors[-1][2]
            return {
                "state": "paused",
                "reason": f"Degraded — {err_count} recent error{'s' if err_count != 1 else ''} from this module",
                "details": {"latest_error": latest_sig[:100], "window_minutes": 15, "module": module_name},
            }

        return {
            "state": "trading",
            "reason": "Module is actively evaluating",
            "details": {"module": module_name, "cycle_count": self._cycle_count},
        }


engine = TradingEngine()
