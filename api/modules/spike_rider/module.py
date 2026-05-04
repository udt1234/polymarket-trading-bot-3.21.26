"""Spike Rider trading module.

Entry: at the start of every recurring auction, buy every bracket whose price
lies in [entry_min_price, entry_max_price]. Fixed dollar size per entry.

Exit: configurable rule (multi-stage tranches, target multiplier, or trailing
stop). The simulator picks the default; production overrides via module_config.

Series-driven: one auction_series row tells this module which xTracker handle
+ title filter to follow. Adding more series scaffolds more Spike Rider
modules without code changes.
"""
import asyncio
import logging
from datetime import datetime, timezone

from api.modules.base import BaseModule
from api.services.risk_manager import Signal
from api.dependencies import get_supabase
from api.modules.spike_rider.module_config import get_module_config
from api.modules.spike_rider.data import (
    get_series_for_module, fetch_active_tracking_for_series,
    extract_slug_from_tracking, fetch_market_prices, fetch_market_brackets,
)
from api.modules.spike_rider.sell_rules import PositionState, evaluate as eval_sell_rule

log = logging.getLogger(__name__)


class SpikeRiderModule(BaseModule):
    name = "spike_rider"
    enabled = True

    def evaluate(self) -> list[Signal]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(lambda: asyncio.run(self._evaluate_async())).result(timeout=60)
            return loop.run_until_complete(self._evaluate_async())
        except RuntimeError:
            return asyncio.run(self._evaluate_async())

    async def _evaluate_async(self) -> list[Signal]:
        sb = get_supabase()
        # All Spike Rider modules in DB. One per series.
        rows = (
            sb.table("modules")
            .select("*")
            .eq("strategy", "spike_rider")
            .in_("status", ["active", "paper"])
            .execute()
        )
        if not rows.data:
            return []

        all_signals: list[Signal] = []
        for module_row in rows.data:
            try:
                signals = await self._evaluate_one_module(sb, module_row)
                all_signals.extend(signals)
            except Exception as e:
                log.error(f"spike_rider module {module_row.get('id')} eval failed: {e}")
                self._log(sb, module_row.get("id"), "system", "error", f"Eval failed: {e}")
        return all_signals

    async def _evaluate_one_module(self, sb, module_row: dict) -> list[Signal]:
        module_id = module_row["id"]
        cfg = get_module_config(module_id)

        if not cfg.get("enabled", True):
            return []

        series = get_series_for_module(module_id)
        if not series:
            self._log(sb, module_id, "decision", "warning",
                      "No auction_series row — skipping (scaffold incomplete)")
            return []

        tracking = await fetch_active_tracking_for_series(series)
        if not tracking:
            self._log(sb, module_id, "decision", "warning",
                      f"No active tracking for handle={series.get('handle')} filter={series.get('title_filter')}")
            return []

        slug = extract_slug_from_tracking(tracking)
        if not slug:
            self._log(sb, module_id, "decision", "warning", "Could not extract market slug")
            return []

        if slug != module_row.get("market_slug"):
            sb.table("modules").update({"market_slug": slug}).eq("id", module_id).execute()

        market_prices = await fetch_market_prices(slug)
        if not market_prices:
            self._log(sb, module_id, "decision", "warning", f"No market prices for {slug}")
            return []

        # Brackets advertised on Polymarket for this auction
        brackets = await fetch_market_brackets(slug) or list(market_prices.keys())
        focus = cfg.get("focus_brackets") or []
        if focus:
            brackets = [b for b in brackets if b in focus]

        # Auction timing — gate entries by elapsed fraction
        start_str = tracking.get("startDate") or ""
        end_str = tracking.get("endDate") or ""
        now = datetime.now(timezone.utc)
        elapsed_pct = self._elapsed_fraction(start_str, end_str, now)
        elapsed_max = float(cfg.get("elapsed_max_pct", 0.50) or 0.50)
        if elapsed_pct >= elapsed_max:
            self._log(sb, module_id, "decision", "info",
                      f"Past entry window: elapsed {elapsed_pct:.0%} >= {elapsed_max:.0%}")
            return []

        signals: list[Signal] = []

        # Existing positions (avoid duplicate entries; also enforce caps)
        open_positions = (
            sb.table("positions")
            .select("id,bracket,size,avg_price,market_id,model_prob,created_at")
            .eq("module_id", module_id)
            .eq("status", "open")
            .execute()
        )
        open_rows = open_positions.data or []
        held_brackets = {p.get("bracket") for p in open_rows if p.get("market_id") == slug}
        max_open = int(cfg.get("max_open_positions", 5) or 5)
        max_open_per_auction = int(cfg.get("max_open_per_auction", 3) or 3)
        positions_in_auction = sum(1 for p in open_rows if p.get("market_id") == slug)
        global_open = len(open_rows)

        entry_min = float(cfg.get("entry_min_price", 0.02) or 0.02)
        entry_max = float(cfg.get("entry_max_price", 0.40) or 0.40)
        entry_size_usd = float(cfg.get("entry_size_usd", 10.0) or 10.0)

        # ----- ENTRY signals -----
        for bracket in brackets:
            if bracket in held_brackets:
                continue
            if global_open >= max_open or positions_in_auction >= max_open_per_auction:
                break
            price = float(market_prices.get(bracket) or 0)
            if price < entry_min or price > entry_max:
                continue
            # kelly_pct here is *fraction of bankroll* the executor uses to size.
            # Spike Rider uses a fixed-dollar entry — convert to kelly_pct relative
            # to the module budget so it survives the existing executor pipeline.
            budget = float(module_row.get("budget", 100) or 100)
            kelly_pct = max(min(entry_size_usd / budget, 1.0), 0.0)
            signals.append(Signal(
                module_id=module_id, market_id=slug, bracket=bracket,
                side="BUY", edge=0.0, model_prob=0.0,
                market_price=price, kelly_pct=kelly_pct, confidence=0.5,
                metadata={
                    "strategy": "spike_rider",
                    "skip_edge_check": True,
                    "entry_size_usd": entry_size_usd,
                    "entry_price_band": [entry_min, entry_max],
                    "elapsed_pct": round(elapsed_pct, 3),
                    "tracking_id": str(tracking.get("id") or tracking.get("trackingId") or ""),
                    "auction_title": tracking.get("title", ""),
                },
            ))
            positions_in_auction += 1
            global_open += 1

        # ----- EXIT signals (sell-rule evaluation) -----
        # Pull peak prices + per-position exit-stage state in batch.
        peaks_by_pid = self._fetch_peak_prices(sb, module_id, open_rows)
        exit_states = self._fetch_exit_states(sb, [p["id"] for p in open_rows])

        for pos in open_rows:
            bracket = pos.get("bracket")
            current = float(market_prices.get(bracket, 0) or 0)
            if current <= 0 or current >= 1:
                continue
            entry = float(pos.get("avg_price", 0) or 0)
            if entry <= 0:
                continue
            peak = max(peaks_by_pid.get(pos["id"], current), current, entry)
            es = exit_states.get(pos["id"]) or {}
            stages = (
                bool(es.get("stage_1_done")),
                bool(es.get("stage_2_done")),
                bool(es.get("stage_3_done")),
            )
            original_size = float(es.get("original_size") or pos.get("size") or 0)
            current_size = float(pos.get("size") or 0)
            if original_size <= 0 or current_size <= 0:
                continue

            state = PositionState(
                avg_price=entry, current_price=current, peak_price=peak,
                original_size=original_size, current_size=current_size,
                stages_done=stages,
            )
            decision = eval_sell_rule(state, cfg)
            if decision is None:
                # Persist peak in exit_state so stop-losses don't reset on restart
                self._upsert_exit_state(sb, pos["id"], peak=peak, original_size=original_size)
                continue

            if decision[0] == "full":
                _, reason = decision
                signals.append(Signal(
                    module_id=module_id, market_id=slug, bracket=bracket,
                    side="SELL", edge=0.0, model_prob=0.0,
                    market_price=current, kelly_pct=1.0, confidence=1.0,
                    metadata={"strategy": "spike_rider", "exit_reason": reason,
                              "peak_price": peak, "entry_price": entry},
                ))
                self._upsert_exit_state(sb, pos["id"], peak=peak,
                                        original_size=original_size,
                                        stages_done=(True, True, True))
            elif decision[0] == "fraction":
                _, fraction, reason, stage_idx = decision
                # Convert fraction-of-original to fraction-of-current for executor
                shares_to_sell = original_size * fraction
                if shares_to_sell <= 0 or shares_to_sell > current_size:
                    shares_to_sell = current_size
                frac_of_current = shares_to_sell / current_size if current_size > 0 else 1.0
                kelly_pct = max(min(frac_of_current, 1.0), 0.0)
                signals.append(Signal(
                    module_id=module_id, market_id=slug, bracket=bracket,
                    side="SELL", edge=0.0, model_prob=0.0,
                    market_price=current, kelly_pct=kelly_pct, confidence=1.0,
                    metadata={"strategy": "spike_rider", "exit_reason": reason,
                              "tranche_fraction": fraction,
                              "stage_index": stage_idx,
                              "peak_price": peak, "entry_price": entry,
                              "partial_exit": True},
                ))
                new_stages = list(stages)
                if 0 <= stage_idx < len(new_stages):
                    new_stages[stage_idx] = True
                self._upsert_exit_state(sb, pos["id"], peak=peak,
                                        original_size=original_size,
                                        stages_done=tuple(new_stages))

        self._log(sb, module_id, "decision", "info",
                  f"Cycle: slug={slug}, elapsed={elapsed_pct:.0%}, signals={len(signals)} "
                  f"(buys={sum(1 for s in signals if s.side == 'BUY')}, sells={sum(1 for s in signals if s.side == 'SELL')})")
        return signals

    def get_status(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "strategy": "spike_rider",
                "status": "active" if self.enabled else "paused"}

    # ---- helpers ----
    def _elapsed_fraction(self, start_str: str, end_str: str, now: datetime) -> float:
        try:
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            total = (end - start).total_seconds()
            if total <= 0:
                return 1.0
            elapsed = (now - start).total_seconds()
            return max(min(elapsed / total, 1.0), 0.0)
        except Exception:
            return 0.0

    def _fetch_peak_prices(self, sb, module_id: str, positions: list[dict]) -> dict[str, float]:
        peaks: dict[str, float] = {}
        for pos in positions:
            pid = pos.get("id")
            bracket = pos.get("bracket")
            created = pos.get("created_at")
            if not (pid and bracket and created):
                continue
            try:
                res = (
                    sb.table("price_snapshots")
                    .select("price")
                    .eq("module_id", module_id)
                    .eq("bracket", bracket)
                    .gte("snapshot_hour", created)
                    .order("price", desc=True)
                    .limit(1)
                    .execute()
                )
                rows = res.data or []
                if rows and rows[0].get("price") is not None:
                    peaks[pid] = float(rows[0]["price"])
            except Exception as e:
                log.warning(f"peak fetch failed for position {pid}: {e}")
        return peaks

    def _fetch_exit_states(self, sb, position_ids: list[str]) -> dict[str, dict]:
        if not position_ids:
            return {}
        try:
            res = (
                sb.table("position_exit_state")
                .select("*")
                .in_("position_id", position_ids)
                .execute()
            )
            return {r["position_id"]: r for r in (res.data or [])}
        except Exception:
            return {}

    def _upsert_exit_state(self, sb, position_id: str, peak: float | None = None,
                           original_size: float | None = None,
                           stages_done: tuple[bool, bool, bool] | None = None):
        try:
            payload = {"position_id": position_id,
                       "updated_at": datetime.now(timezone.utc).isoformat()}
            if peak is not None:
                payload["peak_price"] = peak
            if original_size is not None:
                payload["original_size"] = original_size
            if stages_done is not None:
                payload["stage_1_done"] = stages_done[0]
                payload["stage_2_done"] = stages_done[1]
                payload["stage_3_done"] = stages_done[2]
            sb.table("position_exit_state").upsert(payload).execute()
        except Exception as e:
            log.warning(f"exit_state upsert failed for {position_id}: {e}")

    def _log(self, sb, module_id: str | None, log_type: str, severity: str, message: str):
        try:
            sb.table("logs").insert({
                "log_type": log_type, "severity": severity,
                "module_id": module_id, "message": message,
            }).execute()
        except Exception:
            log.error(f"Failed to write log: {message}")
