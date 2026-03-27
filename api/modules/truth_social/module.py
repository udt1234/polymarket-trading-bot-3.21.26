import asyncio
import logging
import math
from pathlib import Path
from datetime import datetime, timezone, timedelta
from api.modules.base import BaseModule
from api.services.risk_manager import Signal
from api.modules.truth_social.data import (
    fetch_xtracker_posts, fetch_active_tracking, extract_slug_from_tracking,
    parse_hourly_counts, compute_running_total,
    compute_elapsed_days, fetch_market_prices, fetch_historical_weekly_totals,
)
from api.modules.truth_social.news import fetch_google_news
from api.modules.truth_social.pacing import regular_pace, bayesian_pace, dow_hourly_bayesian_pace
from api.modules.truth_social.projection import ensemble_weights, ensemble_projection
from api.modules.truth_social.regime import detect_regime
from api.modules.truth_social.signals import compute_signal_modifier, kelly_sizing, rank_brackets
from api.modules.truth_social.enhanced_pacing import (
    recency_weighted_averages, regime_conditional_dow_averages,
    pace_acceleration, dow_deviation, ensemble_confidence_bands,
)
from api.modules.truth_social.parquet_history import (
    PARQUET_CACHE_DIR, historical_price_pattern,
)
from api.modules.truth_social.module_config import get_module_config
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


class TruthSocialModule(BaseModule):
    name = "truth_social"
    enabled = True

    BRACKETS = [
        "0-19", "20-39", "40-59", "60-79", "80-99",
        "100-119", "120-139", "140-159", "160-179", "180-199", "200+"
    ]
    HANDLE = "realDonaldTrump"

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
        module_row = sb.table("modules").select("*").eq("name", "Truth Social Posts").single().execute()
        if not module_row.data:
            log.warning("Truth Social module not found in DB")
            return []

        module_config = module_row.data
        module_id = module_config["id"]

        # Auto-discover the active market slug from xTracker
        tracking = await fetch_active_tracking(self.HANDLE)
        if not tracking:
            self._log(sb, module_id, "decision", "warning", "No active xTracker tracking found")
            return []

        slug = extract_slug_from_tracking(tracking)
        if not slug:
            self._log(sb, module_id, "decision", "warning", "Could not extract market slug from tracking")
            return []

        # Update the module's slug if it changed
        if slug != module_config.get("market_slug"):
            sb.table("modules").update({"market_slug": slug}).eq("id", module_id).execute()
            self._log(sb, module_id, "system", "info", f"Updated market slug to {slug}")

        # Fetch xTracker stats for this tracking
        raw_data = await fetch_xtracker_posts(self.HANDLE)
        hourly_counts = parse_hourly_counts(raw_data)

        # Fetch market prices from Gamma
        market_prices = await fetch_market_prices(slug)
        if not market_prices:
            self._log(sb, module_id, "decision", "warning", f"No market prices for slug={slug}")
            return []

        # Historical data + news
        weekly_history = await fetch_historical_weekly_totals(self.HANDLE, weeks=12)
        news = await fetch_google_news("Trump")

        # Determine the week window from the tracking
        week_start_str = tracking.get("startDate", "")[:10]
        week_end_str = tracking.get("endDate", "")[:10]
        now = datetime.now(timezone.utc)

        if not week_start_str:
            days_since_monday = (now.weekday()) % 7
            week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            week_start_str = week_start.strftime("%Y-%m-%d")

        # If we have hourly data, use it. Otherwise estimate from tracking info.
        if hourly_counts:
            running_total = compute_running_total(hourly_counts, week_start_str)
        else:
            # No granular data — use any metrics from tracking
            metrics = raw_data.get("metrics", {}) if isinstance(raw_data, dict) else {}
            if metrics:
                running_total = sum(v for v in metrics.values() if isinstance(v, (int, float)))
            else:
                running_total = 0
            self._log(sb, module_id, "decision", "info",
                      f"No hourly data; using aggregate total={running_total}")

        elapsed_days = compute_elapsed_days(week_start_str, now)
        remaining_days = max(7.0 - elapsed_days, 0.01)
        total_days = 7.0

        mod_cfg = get_module_config(module_id)
        half_life = mod_cfg.get("recency_half_life", 4.0)

        rw = recency_weighted_averages(weekly_history, half_life=half_life)
        hist_mean = rw["mean"] if rw["mean"] > 0 else (sum(weekly_history) / len(weekly_history) if weekly_history else 100.0)
        hist_std = rw["std"] if rw["std"] > 0 else 30.0

        # Pacing models
        pace = regular_pace(running_total, elapsed_days, total_days)
        bayes = bayesian_pace(running_total, elapsed_days, remaining_days, hist_mean, total_days)

        # Build hourly averages for DOW model
        hourly_avgs = {}
        dow_weights = {i: 1.0 for i in range(7)}
        if hourly_counts:
            for h in hourly_counts:
                hr = h.get("hour", 0)
                hourly_avgs.setdefault(hr, [])
                hourly_avgs[hr].append(h["count"])
            hourly_avgs = {k: sum(v) / len(v) for k, v in hourly_avgs.items()}
        else:
            hourly_avgs = {h: hist_mean / 168 for h in range(24)}

        remaining_hours = []
        for d in range(int(remaining_days) + 1):
            future_date = now + timedelta(days=d)
            start_hr = now.hour + 1 if d == 0 else 0
            for hr in range(start_hr, 24):
                remaining_hours.append({"hour": hr, "dow": future_date.weekday()})

        dow = dow_hourly_bayesian_pace(running_total, remaining_hours, hourly_avgs, dow_weights, hist_mean, elapsed_days, remaining_days)

        model_outputs = {"pace": pace, "bayesian": bayes, "dow": dow, "historical": hist_mean}
        weights = ensemble_weights(elapsed_days, total_days)

        regime = detect_regime(weekly_history) if len(weekly_history) >= 4 else {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0.8}

        accel = pace_acceleration(hourly_counts)

        dev = None
        if hourly_counts and hourly_avgs:
            dow_avg_today = hist_mean / 7.0
            dev = dow_deviation(running_total, now.hour, now.weekday(), dow_avg_today, hourly_avgs)
            if dev["status"] != "on_pace":
                self._log(sb, module_id, "decision", "info",
                          f"DOW deviation: {dev['status']} ({dev['deviation_pct']:+.1f}%)")

        # Historical parquet model (5th ensemble model)
        parquet_probs = None
        if mod_cfg.get("use_parquet_model", True):
            cache_path = PARQUET_CACHE_DIR / f"{slug}.parquet"
            if cache_path.exists():
                try:
                    import pandas as pd
                    cached_df = pd.read_parquet(cache_path)
                    parquet_probs = historical_price_pattern(
                        running_total, elapsed_days, cached_df, self.BRACKETS
                    )
                except Exception as e:
                    log.warning(f"Parquet model failed: {e}")

        signal_mod = compute_signal_modifier(
            news.get("headline_count", 0),
            news.get("conflict_score", 0),
            news.get("schedule_events", []),
        )

        if parquet_probs:
            model_outputs["parquet"] = sum(
                float(b.split("-")[0] if "-" in b else b.replace("+", ""))
                * p for b, p in parquet_probs.items()
            )
            total_w = sum(weights.values())
            parquet_w = 0.20
            scale = (1.0 - parquet_w) / total_w if total_w > 0 else 1.0
            weights = {k: v * scale for k, v in weights.items()}
            weights["parquet"] = parquet_w

        bracket_probs = ensemble_projection(model_outputs, weights, hist_std, signal_mod)

        conf_bands = ensemble_confidence_bands(bracket_probs, top_n=mod_cfg.get("confidence_band_top_n", 3))
        if conf_bands:
            top_bracket = conf_bands[0]
            log.info(f"Top bracket: {top_bracket['bracket']} ({top_bracket['probability']:.1%}), "
                     f"confidence={top_bracket.get('confidence', 0):.1%}")

        # Smart bracket targeting: only trade top 3 brackets by score
        top_brackets = rank_brackets(bracket_probs, market_prices)
        top_bracket_names = {b["bracket"] for b in top_brackets}

        elapsed_pct = min(elapsed_days / total_days, 1.0)

        signals = []
        for bracket_label, model_prob in bracket_probs.items():
            if bracket_label not in top_bracket_names:
                continue
            market_price = market_prices.get(bracket_label, 0)
            if market_price <= 0 or market_price >= 1:
                continue

            sizing = kelly_sizing(
                model_prob, market_price,
                kelly_fraction=0.25,
                volatility=regime.get("volatility", 0.8),
                regime_label=regime.get("label", "NORMAL"),
                elapsed_pct=elapsed_pct,
            )

            if sizing["action"] == "BUY" and sizing["kelly_pct"] > 0:
                signal = Signal(
                    module_id=module_id,
                    market_id=slug,
                    bracket=bracket_label,
                    side="BUY",
                    edge=sizing["edge"],
                    model_prob=model_prob,
                    market_price=market_price,
                    kelly_pct=sizing["kelly_pct"],
                    confidence=1.0 - regime.get("volatility", 0.8) / 2,
                )
                signals.append(signal)

                enhanced_meta = {
                    "pace_acceleration": accel,
                    "dow_deviation": dev,
                    "regime": regime,
                    "confidence_bands": conf_bands,
                    "parquet_model_active": parquet_probs is not None,
                    "recency_half_life": half_life,
                }
                sb.table("signals").insert({
                    "module_id": module_id,
                    "market_id": slug,
                    "bracket": bracket_label,
                    "side": "BUY",
                    "edge": sizing["edge"],
                    "model_prob": model_prob,
                    "market_price": market_price,
                    "kelly_pct": sizing["kelly_pct"],
                    "approved": False,
                    "metadata": enhanced_meta,
                }).execute()

        self._log(sb, module_id, "decision", "info",
                  f"Cycle: slug={slug}, total={running_total}, elapsed={elapsed_days:.1f}d, "
                  f"regime={regime['label']}, prices={len(market_prices)}, signals={len(signals)}")

        return signals

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "brackets": self.BRACKETS,
            "status": "active" if self.enabled else "paused",
        }

    def _log(self, sb, module_id: str, log_type: str, severity: str, message: str):
        try:
            sb.table("logs").insert({
                "log_type": log_type,
                "severity": severity,
                "module_id": module_id,
                "message": message,
            }).execute()
        except Exception:
            log.error(f"Failed to write log: {message}")
