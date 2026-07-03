"""Compute validation values for the 4 transparency tabs against xTracker live."""
import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict
from zoneinfo import ZoneInfo

CACHE = Path.home() / "OneDrive" / "Desktop" / "Claude Code" / "_downloads" / "_cache_xtracker_validation"
posts = json.loads((CACHE/"elon_posts.json").read_text(encoding="utf-8"))
trackings = json.loads((CACHE/"elon_trackings.json").read_text(encoding="utf-8"))
gamma = json.loads((CACHE/"gamma_events.json").read_text(encoding="utf-8"))

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
xtracker_cutoff = datetime(2025,10,31,0,0,0,tzinfo=UTC)

def count_in_window(start_dt, end_dt):
    c = 0
    for p in posts:
        ca = p.get("createdAt","")
        if not ca: continue
        try:
            dt = datetime.fromisoformat(ca.replace("Z","+00:00"))
            if start_dt <= dt < end_dt:
                c += 1
        except Exception: continue
    return c

def winning_bracket(slug):
    ev = gamma.get(slug)
    if not ev: return "?"
    for m in ev.get("markets", []):
        prices = m.get("outcomePrices","[]")
        if isinstance(prices, str): prices = json.loads(prices)
        if prices and float(prices[0]) == 1.0:
            return m.get("groupItemTitle") or m.get("question","?")
    return "?"

results = {}

# ====================== _Worked_Example ======================
EX_SLUG = "elon-musk-of-tweets-january-30-february-6"
ex_start = datetime(2026,1,30,17,0,0,tzinfo=UTC)
ex_end = datetime(2026,2,6,17,0,0,tzinfo=UTC)
ex_t1d = ex_end - timedelta(hours=24)

observed_at_t1d = count_in_window(ex_start, ex_t1d)
actual_final = count_in_window(ex_start, ex_end)
ex_winning_bracket = winning_bracket(EX_SLUG)
hours_elapsed = (ex_t1d - ex_start).total_seconds() / 3600
hours_remaining = (ex_end - ex_t1d).total_seconds() / 3600

results["worked_example"] = {
    "window": f"{ex_start.isoformat()} -> {ex_end.isoformat()}",
    "observed_at_t1d": observed_at_t1d,
    "hours_elapsed": hours_elapsed,
    "hours_remaining": hours_remaining,
    "actual_final": actual_final,
    "winning_bracket": ex_winning_bracket,
}

# Model math (using sheet-stated inputs)
sheet_obs, sheet_elap, sheet_rem = 255, 144, 24
sheet_hist_tw, sheet_hist_hrs, sheet_hist_avg = 11740, 6554, 301
linear = sheet_obs * 168 / sheet_elap
lam_m0 = (sheet_hist_tw + sheet_obs)/(sheet_hist_hrs + sheet_elap)
m0 = sheet_obs + lam_m0 * sheet_rem
expected_at_elap = sheet_hist_avg * sheet_elap / 168
pace_factor = sheet_obs / expected_at_elap
m5 = sheet_hist_avg * (0.7 + 0.3 * pace_factor)
m4_pace = (sheet_obs / sheet_elap + 11740/6554) / 2
m4 = sheet_obs + m4_pace * sheet_rem
prior_rate = 11740/6554
obs_rate = sheet_obs / sheet_elap
kalman_rate = prior_rate * 0.33 + obs_rate * 0.67
kalman = sheet_obs + kalman_rate * sheet_rem

results["worked_example_models"] = {
    "linear": round(linear,1),
    "m0_gamma_poisson": round(m0,1),
    "m4_mmpp": round(m4,1),
    "m5_negbin": round(m5,1),
    "kalman": round(kalman,1),
}

# ====================== _PROOF_TweetCount ======================
jun_start = datetime(2026,6,16,16,0,0,tzinfo=UTC)
jun_end = datetime(2026,6,23,16,0,0,tzinfo=UTC)
jun18_start = datetime(2026,6,18,16,0,0,tzinfo=UTC)
jun20_end = datetime(2026,6,20,16,0,0,tzinfo=UTC)

results["proof_tweetcount"] = {
    "total_in_window": actual_final,
    "winning_bracket": ex_winning_bracket,
    "type_sum": 10+113+155+4,
    "jun_16_23_count": count_in_window(jun_start, jun_end),
    "jun_18_20_count": count_in_window(jun18_start, jun20_end),
}

# ====================== _PROOF_Seasonality ======================
hourly = defaultdict(int)
days_seen = set()
for p in posts:
    ca = p.get("createdAt","")
    if not ca: continue
    try:
        dt_et = datetime.fromisoformat(ca.replace("Z","+00:00")).astimezone(ET)
        hourly[dt_et.hour] += 1
        days_seen.add(dt_et.strftime("%Y-%m-%d"))
    except Exception: continue
n_days = len(days_seen)

dow_count = defaultdict(int)
dow_days = defaultdict(set)
for p in posts:
    ca = p.get("createdAt","")
    if not ca: continue
    try:
        dt_et = datetime.fromisoformat(ca.replace("Z","+00:00")).astimezone(ET)
        dow_count[dt_et.weekday()] += 1
        dow_days[dt_et.weekday()].add(dt_et.strftime("%Y-%m-%d"))
    except Exception: continue

results["proof_seasonality"] = {
    "n_days_actual": n_days,
    "n_tweets_actual": sum(hourly.values()),
    "hourly": {h: round(hourly[h]/n_days, 2) if n_days else 0 for h in range(24)},
    "dow": {i: round(dow_count[i]/len(dow_days[i]), 2) if dow_days[i] else 0 for i in range(7)},
}

# ====================== _PROOF_PriorAuctions ======================
PRIOR_AUCTIONS = [
    (1,  "elon-musk-of-tweets-september-5-12",            "2025-09-05 16:00:00+00:00", 227),
    (2,  "elon-musk-of-tweets-september-9-september-16",  "2025-09-09 16:00:00+00:00", 251),
    (3,  "elon-musk-of-tweets-september-12-september-19", "2025-09-12 16:00:00+00:00", 263),
    (4,  "elon-musk-of-tweets-september-16-september-23", "2025-09-16 16:00:00+00:00", 200),
    (5,  "elon-musk-of-tweets-september-19-september-26", "2025-09-19 16:00:00+00:00", 138),
    (6,  "elon-musk-of-tweets-september-23-september-30", "2025-09-23 16:00:00+00:00", 131),
    (7,  "elon-musk-of-tweets-september-26-october-3",    "2025-09-26 16:00:00+00:00", 242),
    (8,  "elon-musk-of-tweets-september-30-october-7",    "2025-09-30 16:00:00+00:00", 306),
    (9,  "elon-musk-of-tweets-october-3-october-10",      "2025-10-03 16:00:00+00:00", 277),
    (10, "elon-musk-of-tweets-october-7-october-14",      "2025-10-07 16:00:00+00:00", 245),
    (11, "elon-musk-of-tweets-october-10-october-17",     "2025-10-10 16:00:00+00:00", 187),
    (12, "elon-musk-of-tweets-october-14-october-21",     "2025-10-14 16:00:00+00:00", 275),
    (13, "elon-musk-of-tweets-october-17-october-24",     "2025-10-17 16:00:00+00:00", 278),
    (14, "elon-musk-of-tweets-october-21-october-28",     "2025-10-21 16:00:00+00:00", 185),
    (15, "elon-musk-of-tweets-october-24-october-31",     "2025-10-24 16:00:00+00:00", 213),
    (16, "elon-musk-of-tweets-october-28-november-4",     "2025-10-28 16:00:00+00:00", 209),
    (17, "elon-musk-of-tweets-october-31-november-7",     "2025-10-31 16:00:00+00:00", 170),
    (18, "elon-musk-of-tweets-november-4-november-11",    "2025-11-04 17:00:00+00:00", 146),
    (19, "elon-musk-of-tweets-november-7-november-14",    "2025-11-07 17:00:00+00:00", 247),
    (20, "elon-musk-of-tweets-november-11-november-18",   "2025-11-11 17:00:00+00:00", 286),
    (21, "elon-musk-of-tweets-november-14-november-21",   "2025-11-14 17:00:00+00:00", 180),
    (22, "elon-musk-of-tweets-november-18-november-25",   "2025-11-18 17:00:00+00:00", 201),
    (23, "elon-musk-of-tweets-november-21-november-28",   "2025-11-21 17:00:00+00:00", 284),
    (24, "elon-musk-of-tweets-november-25-december-2",    "2025-11-25 17:00:00+00:00", 260),
    (25, "elon-musk-of-tweets-november-28-december-5",    "2025-11-28 17:00:00+00:00", 265),
    (26, "elon-musk-of-tweets-december-2-december-9",     "2025-12-02 17:00:00+00:00", 432),
    (27, "elon-musk-of-tweets-december-5-december-12",    "2025-12-05 17:00:00+00:00", 449),
    (28, "elon-musk-of-tweets-december-9-december-16",    "2025-12-09 17:00:00+00:00", 272),
    (29, "elon-musk-of-tweets-december-12-december-19",   "2025-12-12 17:00:00+00:00", 273),
    (30, "elon-musk-of-tweets-december-16-december-23",   "2025-12-16 17:00:00+00:00", 350),
    (31, "elon-musk-of-tweets-december-19-december-26",   "2025-12-19 17:00:00+00:00", 353),
    (32, "elon-musk-of-tweets-december-23-december-30",   "2025-12-23 17:00:00+00:00", 420),
    (33, "elon-musk-of-tweets-december-26-january-2",     "2025-12-26 17:00:00+00:00", 499),
    (34, "elon-musk-of-tweets-december-30-january-6",     "2025-12-30 17:00:00+00:00", 535),
    (35, "elon-musk-of-tweets-january-6-january-13",      "2026-01-06 17:00:00+00:00", 553),
    (36, "elon-musk-of-tweets-january-9-january-16",      "2026-01-09 17:00:00+00:00", 539),
    (37, "elon-musk-of-tweets-january-13-january-20",     "2026-01-13 17:00:00+00:00", 534),
    (38, "elon-musk-of-tweets-january-16-january-23",     "2026-01-16 17:00:00+00:00", 471),
    (39, "elon-musk-of-tweets-january-20-january-27",     "2026-01-20 17:00:00+00:00", 394),
]

prior_results = []
for num, slug, window_start_str, sheet_count in PRIOR_AUCTIONS:
    start_dt = datetime.fromisoformat(window_start_str)
    end_dt = start_dt + timedelta(days=7)
    if end_dt < xtracker_cutoff:
        actual = None; verdict = "skipped — pre-Oct 31"
    elif start_dt < xtracker_cutoff:
        actual = count_in_window(xtracker_cutoff, end_dt)
        verdict = f"partial coverage from Oct 31"
    else:
        actual = count_in_window(start_dt, end_dt)
        verdict = "correct" if actual == sheet_count else "not correct"
    prior_results.append((num, slug, sheet_count, actual, verdict))

results["proof_prior_auctions"] = prior_results

(CACHE/"validation_results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
print("Validation values written")
print(json.dumps({k: (v if not isinstance(v, list) else f"list[{len(v)}]") for k,v in results.items()}, indent=2, default=str))
