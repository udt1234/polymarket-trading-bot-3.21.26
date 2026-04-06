import asyncio
import logging
from datetime import datetime, timezone, timedelta
from api.modules.base import BaseModule
from api.services.risk_manager import Signal
from api.modules.elon_tweets.data import (
    fetch_xtracker_posts, fetch_active_tracking, fetch_market_brackets,
    parse_hourly_counts, compute_running_total,
    compute_elapsed_days, fetch_market_prices, fetch_historical_weekly_totals,
    extract_slug_from_tracking,
)
from api.modules.truth_social.news import fetch_google_news
from api.modules.truth_social.pacing import regular_pace, bayesian_pace, dow_hourly_bayesian_pace
from api.modules.truth_social.projection import ensemble_weights
from api.modules.truth_social.regime import detect_regime
from api.modules.truth_social.signals import compute_signal_modifier, kelly_sizing
from api.modules.truth_social.hawkes import hawkes_pace, fit_hawkes_params
from api.modules.truth_social.news_classifier import classify_news_regime
from api.modules.truth_social.enhanced_pacing import (
    recency_weighted_averages, pace_acceleration,
)
from api.services.lunarcrush import fetch_social_sentiment, fetch_creator_metrics, compute_lunarcrush_modifier
from api.dependencies import get_supabase

log = logging.getLogger(__name__)


class ElonTweetsModule(BaseModule):
    name = "elon_tweets"
    enabled = True
    HANDLE = "elonmusk"

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
        module_row = sb.table("modules").select("*").eq("name", "Elon Tweets").single().execute()
        if not module_row.data:
            log.warning("Elon Tweets module not found in DB")
            return []

        module_config = module_row.data
        module_id = module_config["id"]

        tracking = await fetch_active_tracking(self.HANDLE)
        if not tracking:
            self._log(sb, module_id, "decision", "warning", "No active xTracker tracking found")
            return []

        slug = extract_slug_from_tracking(tracking)
        if not slug:
            self._log(sb, module_id, "decision", "warning", "Could not extract market slug")
            return []

        if slug != module_config.get("market_slug"):
            sb.table("modules").update({"market_slug": slug}).eq("id", module_id).execute()

        raw_data = await fetch_xtracker_posts(self.HANDLE)
        hourly_counts = parse_hourly_counts(raw_data)

        market_prices = await fetch_market_prices(slug)
        if not market_prices:
            self._log(sb, module_id, "decision", "warning", f"No market prices for slug={slug}")
            return []

        dynamic_brackets = await fetch_market_brackets(slug)
        if not dynamic_brackets:
            dynamic_brackets = list(market_prices.keys())

        # Data sources: history + news + social intelligence
        weekly_history = await fetch_historical_weekly_totals(self.HANDLE, weeks=12)
        news = await fetch_google_news("Elon Musk")
        lunar_sentiment = await fetch_social_sentiment("elon musk")
        lunar_creator = await fetch_creator_metrics("elonmusk", network="x")

        # Auction timing (full timestamp, works for weekly/monthly)
        week_start_str = tracking.get("startDate", "")
        week_end_str = tracking.get("endDate", "")
        now = datetime.now(timezone.utc)

        if not week_start_str:
            days_since_monday = (now.weekday()) % 7
            week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            week_start_str = week_start.isoformat()

        try:
            start_dt = datetime.fromisoformat(week_start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(week_end_str.replace("Z", "+00:00")) if week_end_str else start_dt + timedelta(days=7)
            total_days = max((end_dt - start_dt).total_seconds() / 86400, 1.0)
        except (ValueError, TypeError):
            total_days = 7.0

        if hourly_counts:
            running_total = compute_running_total(hourly_counts, week_start_str)
        else:
            metrics = raw_data.get("metrics", {}) if isinstance(raw_data, dict) else {}
            running_total = sum(v for v in metrics.values() if isinstance(v, (int, float))) if metrics else 0

        elapsed_days = compute_elapsed_days(week_start_str, now)
        remaining_days = max(total_days - elapsed_days, 0.01)

        rw = recency_weighted_averages(weekly_history, half_life=4.0)
        hist_mean = rw["mean"] if rw["mean"] > 0 else (sum(weekly_history) / len(weekly_history) if weekly_history else 100.0)
        hist_std = rw["std"] if rw["std"] > 0 else 30.0

        # 5 pacing models
        pace = regular_pace(running_total, elapsed_days, total_days)
        bayes = bayesian_pace(running_total, elapsed_days, remaining_days, hist_mean, total_days)

        hourly_avgs = {}
        if hourly_counts:
            for h in hourly_counts:
                hr = h.get("hour", 0)
                hourly_avgs.setdefault(hr, [])
                hourly_avgs[hr].append(h["count"])
            hourly_avgs = {k: sum(v) / len(v) for k, v in hourly_avgs.items()}
        else:
            hourly_avgs = {h: hist_mean / (total_days * 24) for h in range(24)}

        dow_weights = {i: 1.0 for i in range(7)}

        remaining_hours = []
        for d in range(int(remaining_days) + 1):
            future_date = now + timedelta(days=d)
            start_hr = now.hour + 1 if d == 0 else 0
            for hr in range(start_hr, 24):
                remaining_hours.append({"hour": hr, "dow": future_date.weekday()})

        dow = dow_hourly_bayesian_pace(running_total, remaining_hours, hourly_avgs, dow_weights, hist_mean, elapsed_days, remaining_days)

        # Hawkes burst model
        hawkes_params = fit_hawkes_params(hourly_counts)
        hawkes_proj = hawkes_pace(
            hourly_counts, len(remaining_hours), running_total,
            mu=hawkes_params["mu"], alpha=hawkes_params["alpha"], beta=hawkes_params["beta"],
        )

        # Regime detection + Claude override
        regime = detect_regime(weekly_history) if len(weekly_history) >= 4 else {"label": "NORMAL", "zscore": 0, "trend": "STABLE", "volatility": 0.8}
        regime_label = regime.get("label", "NORMAL")

        news_override = await classify_news_regime(
            headlines=news.get("headlines", []),
            conflict_score=news.get("conflict_score", 0),
            schedule_events=news.get("schedule_events", []),
            handle="Elon Musk",
        )
        if news_override.get("override") and news_override["override"] != regime_label:
            old_label = regime_label
            regime_label = news_override["override"]
            regime["label"] = regime_label
            self._log(sb, module_id, "decision", "info",
                      f"Regime override: {old_label} -> {regime_label} ({news_override['reason']})")

        model_outputs = {"pace": pace, "bayesian": bayes, "dow": dow, "historical": hist_mean, "hawkes": hawkes_proj}
        weights = ensemble_weights(elapsed_days, total_days, regime_label=regime_label)

        # Signal modifier stack: news 60%, LunarCrush 40% (no presidential schedule for Elon)
        news_mod = compute_signal_modifier(
            news.get("headline_count", 0),
            news.get("conflict_score", 0),
            news.get("schedule_events", []),
        )
        lunar_mod = compute_lunarcrush_modifier(lunar_sentiment, lunar_creator)
        signal_mod = 0.6 * news_mod + 0.4 * lunar_mod

        accel = pace_acceleration(hourly_counts)

        bracket_probs = _dynamic_bracket_probabilities(model_outputs, weights, hist_std, signal_mod, dynamic_brackets)

        elapsed_pct = min(elapsed_days / total_days, 1.0)
        signals = []
        for bracket_label, model_prob in bracket_probs.items():
            market_price = market_prices.get(bracket_label, 0)
            if market_price <= 0 or market_price >= 1:
                continue

            sizing = kelly_sizing(
                model_prob, market_price,
                kelly_fraction=0.25,
                volatility=regime.get("volatility", 0.8),
                regime_label=regime_label,
                elapsed_pct=elapsed_pct,
            )

            if sizing["action"] == "BUY" and sizing["kelly_pct"] > 0:
                signal = Signal(
                    module_id=module_id, market_id=slug, bracket=bracket_label,
                    side="BUY", edge=sizing["edge"], model_prob=model_prob,
                    market_price=market_price, kelly_pct=sizing["kelly_pct"],
                    confidence=1.0 - regime.get("volatility", 0.8) / 2,
                    metadata={
                        "regime": regime_label,
                        "regime_override": news_override.get("override"),
                        "running_total": running_total,
                        "elapsed_days": round(elapsed_days, 2),
                        "total_days": round(total_days, 2),
                        "model_outputs": {k: round(v, 1) for k, v in model_outputs.items()},
                        "weights": {k: round(v, 4) for k, v in weights.items()},
                        "signal_mod": round(signal_mod, 3),
                        "news_mod": round(news_mod, 3),
                        "lunar_mod": round(lunar_mod, 3),
                        "hawkes_params": hawkes_params,
                        "momentum": accel.get("momentum", "steady"),
                        "news": {
                            "headline_count": news.get("headline_count", 0),
                            "conflict_score": news.get("conflict_score", 0),
                            "schedule_events": news.get("schedule_events", []),
                            "top_headlines": news.get("headlines", [])[:5],
                        },
                        "lunarcrush": {
                            "velocity": lunar_creator.get("velocity", 0),
                            "dominance": lunar_creator.get("social_dominance", 0),
                            "interactions": lunar_creator.get("interactions", 0),
                        },
                    },
                )
                signals.append(signal)

        self._log(sb, module_id, "decision", "info",
                  f"Cycle: slug={slug}, total={running_total}, elapsed={elapsed_days:.1f}/{total_days:.1f}d, "
                  f"regime={regime_label}, news={news.get('headline_count', 0)}, "
                  f"lunar_vel={lunar_creator.get('velocity', 0)}, signals={len(signals)}")

        return signals

    def get_status(self) -> dict:
        return {"name": self.name, "enabled": self.enabled, "brackets": "dynamic",
                "status": "active" if self.enabled else "paused"}

    def _log(self, sb, module_id: str, log_type: str, severity: str, message: str):
        try:
            sb.table("logs").insert({
                "log_type": log_type, "severity": severity,
                "module_id": module_id, "message": message,
            }).execute()
        except Exception:
            log.error(f"Failed to write log: {message}")


def _parse_bracket_range(label: str) -> tuple[int, int]:
    label = label.strip()
    if label.endswith("+"):
        return (int(label[:-1]), 99999)
    if label.startswith("<"):
        return (0, int(label[1:]) - 1)
    if label.startswith(">=") or label.startswith("≥"):
        return (int(label.lstrip(">=≥")), 99999)
    parts = label.split("-")
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    return (0, 0)


def _dynamic_bracket_probabilities(
    model_outputs: dict[str, float], weights: dict[str, float],
    weekly_std: float, signal_modifier: float, bracket_labels: list[str],
) -> dict[str, float]:
    from scipy import stats

    combined_mean = sum(weights.get(name, 0) * val * signal_modifier for name, val in model_outputs.items())
    std = max(weekly_std, 10.0)
    norm = stats.norm(loc=combined_mean, scale=std)

    p_nb = combined_mean / (std ** 2) if std ** 2 > combined_mean else 0.99
    p_nb = max(min(p_nb, 0.99), 0.01)
    r_nb = max(combined_mean * p_nb / (1 - p_nb), 1.0)
    nb = stats.nbinom(r_nb, p_nb)

    probs = {}
    for label in bracket_labels:
        lo, hi = _parse_bracket_range(label)
        p_norm = norm.cdf(hi + 0.5) - norm.cdf(lo - 0.5)
        p_nb_val = nb.cdf(hi) - nb.cdf(lo - 1) if lo > 0 else nb.cdf(hi)
        probs[label] = 0.4 * max(p_norm, 0) + 0.6 * max(p_nb_val, 0)

    total = sum(probs.values())
    if total > 0:
        probs = {k: v / total for k, v in probs.items()}
    return probs
