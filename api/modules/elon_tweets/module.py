import asyncio
import logging
import math
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
from api.modules.truth_social.projection import ensemble_weights, ensemble_projection, bracket_probabilities
from api.modules.truth_social.regime import detect_regime
from api.modules.truth_social.signals import compute_signal_modifier, kelly_sizing
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
            self._log(sb, module_id, "decision", "warning", "Could not extract market slug from tracking")
            return []

        if slug != module_config.get("market_slug"):
            sb.table("modules").update({"market_slug": slug}).eq("id", module_id).execute()
            self._log(sb, module_id, "system", "info", f"Updated market slug to {slug}")

        raw_data = await fetch_xtracker_posts(self.HANDLE)
        hourly_counts = parse_hourly_counts(raw_data)

        market_prices = await fetch_market_prices(slug)
        if not market_prices:
            self._log(sb, module_id, "decision", "warning", f"No market prices for slug={slug}")
            return []

        # Dynamically read brackets from the market
        dynamic_brackets = await fetch_market_brackets(slug)
        if not dynamic_brackets:
            dynamic_brackets = list(market_prices.keys())

        weekly_history = await fetch_historical_weekly_totals(self.HANDLE, weeks=12)
        news = await fetch_google_news("Elon Musk")

        week_start_str = tracking.get("startDate", "")[:10]
        week_end_str = tracking.get("endDate", "")[:10]
        now = datetime.now(timezone.utc)

        if not week_start_str:
            days_since_monday = (now.weekday()) % 7
            week_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            week_start_str = week_start.strftime("%Y-%m-%d")

        # Determine period length from tracking dates
        if week_start_str and week_end_str:
            start_dt = datetime.fromisoformat(week_start_str)
            end_dt = datetime.fromisoformat(week_end_str)
            total_days = max((end_dt - start_dt).days, 1)
        else:
            total_days = 7.0

        if hourly_counts:
            running_total = compute_running_total(hourly_counts, week_start_str)
        else:
            metrics = raw_data.get("metrics", {}) if isinstance(raw_data, dict) else {}
            if metrics:
                running_total = sum(v for v in metrics.values() if isinstance(v, (int, float)))
            else:
                running_total = 0
            self._log(sb, module_id, "decision", "info",
                      f"No hourly data; using aggregate total={running_total}")

        elapsed_days = compute_elapsed_days(week_start_str, now)
        remaining_days = max(total_days - elapsed_days, 0.01)

        hist_mean = sum(weekly_history) / len(weekly_history) if weekly_history else 100.0
        hist_std = math.sqrt(sum((x - hist_mean) ** 2 for x in weekly_history) / max(len(weekly_history) - 1, 1)) if len(weekly_history) > 1 else 30.0

        pace = regular_pace(running_total, elapsed_days, total_days)
        bayes = bayesian_pace(running_total, elapsed_days, remaining_days, hist_mean, total_days)

        hourly_avgs = {}
        dow_weights = {i: 1.0 for i in range(7)}
        if hourly_counts:
            for h in hourly_counts:
                hr = h.get("hour", 0)
                hourly_avgs.setdefault(hr, [])
                hourly_avgs[hr].append(h["count"])
            hourly_avgs = {k: sum(v) / len(v) for k, v in hourly_avgs.items()}
        else:
            hourly_avgs = {h: hist_mean / (total_days * 24) for h in range(24)}

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

        signal_mod = compute_signal_modifier(
            news.get("headline_count", 0),
            news.get("conflict_score", 0),
            news.get("schedule_events", []),
        )

        # Build dynamic bracket probabilities from the market's actual brackets
        bracket_probs = _dynamic_bracket_probabilities(model_outputs, weights, hist_std, signal_mod, dynamic_brackets)

        signals = []
        for bracket_label, model_prob in bracket_probs.items():
            market_price = market_prices.get(bracket_label, 0)
            if market_price <= 0 or market_price >= 1:
                continue

            sizing = kelly_sizing(
                model_prob, market_price,
                kelly_fraction=0.25,
                volatility=regime.get("volatility", 0.8),
                regime_label=regime.get("label", "NORMAL"),
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
                }).execute()

        self._log(sb, module_id, "decision", "info",
                  f"Cycle: slug={slug}, total={running_total}, elapsed={elapsed_days:.1f}d, "
                  f"regime={regime['label']}, prices={len(market_prices)}, signals={len(signals)}")

        return signals

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "brackets": "dynamic",
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


def _parse_bracket_range(label: str) -> tuple[int, int]:
    label = label.strip()
    if label.endswith("+"):
        lo = int(label[:-1])
        return (lo, 99999)
    if label.startswith("<"):
        return (0, int(label[1:]) - 1)
    if label.startswith("≥"):
        return (int(label[1:]), 99999)
    parts = label.split("-")
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    return (0, 0)


def _dynamic_bracket_probabilities(
    model_outputs: dict[str, float],
    weights: dict[str, float],
    weekly_std: float,
    signal_modifier: float,
    bracket_labels: list[str],
) -> dict[str, float]:
    from scipy import stats

    combined_mean = sum(
        weights.get(name, 0) * val * signal_modifier
        for name, val in model_outputs.items()
    )
    std = max(weekly_std, 10.0)
    norm = stats.norm(loc=combined_mean, scale=std)

    p_nb = combined_mean / (std ** 2) if std ** 2 > combined_mean else 0.99
    p_nb = max(min(p_nb, 0.99), 0.01)
    r_nb = combined_mean * p_nb / (1 - p_nb)
    r_nb = max(r_nb, 1.0)
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


# Supabase seed SQL:
# INSERT INTO modules (name, market_slug, strategy, budget, status) VALUES ('Elon Tweets', 'elon-musk-of-tweets', 'ensemble', 100, 'active');
