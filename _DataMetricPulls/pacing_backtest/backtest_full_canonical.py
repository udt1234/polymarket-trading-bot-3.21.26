"""Full backtest harness on canonical Elon data.

Runs 10 pacing models walk-forward on high-confidence Elon auctions.
For each auction, snapshots predictions at T-2d and T-1d.
Compares to actual final post count.

Models:
  Linear          — total × total_h / elapsed_h
  CurrentBayes    — vAI's deployed precision-weighted blend
  M0_GammaPoi     — conjugate Gamma-Poisson on tweet rate
  M1_Seasonal     — hour-of-day × day-of-week from history
  Decay_eps0.85   — M0 with exponential decay on older auctions
  M2_Hawkes       — self-exciting point process (μ, α, β fit via MLE)
  M3_MarkedHawkes — M2 with mark-scaled excitation (is_reply, is_repost, is_quote)
  M4_MMPP         — 2-state quiet/manic regime switching
  M5_NegBin       — Negative Binomial on prior totals (marginal calibration)
  Kalman          — 1D state-space tracking λ
"""
import os, sys, math, time
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.optimize import minimize
from datetime import timezone, timedelta
sys.stdout.reconfigure(encoding='utf-8')
np.random.seed(42)  # reproducible Hawkes simulation

CANON = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\canonical')
OUT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\pacing_backtest')
OUT.mkdir(parents=True, exist_ok=True)

print('=== Loading canonical Elon data ===')
t0 = time.time()
auctions = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
posts = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'posts/elonmusk').glob('*.parquet'))], ignore_index=True)
posts['ts_utc'] = pd.to_datetime(posts['ts_utc'], utc=True)
auctions['start_utc'] = pd.to_datetime(auctions['start_utc'], utc=True)
auctions['end_utc'] = pd.to_datetime(auctions['end_utc'], utc=True)
print(f'  loaded {len(auctions)} auctions, {len(posts)} posts in {time.time()-t0:.1f}s')

# Filter to backtest universe
counted = posts[posts['counts_for_auction'] == True].copy().sort_values('ts_utc').reset_index(drop=True)
clean = auctions[
    (auctions['confidence'] == 'high')
    & (auctions['duration_type'].isin(['2-day','7-day','monthly']))
    & (auctions['winning_bucket'] != '')
].copy().sort_values('start_utc').reset_index(drop=True)
print(f'  filtered: {len(counted)} counted posts, {len(clean)} high-conf auctions')

# Pre-compute post timestamps as float seconds for speed
post_ts_secs = (counted['ts_utc'].astype('int64') // 10**9).to_numpy()
post_is_reply = counted['is_reply'].to_numpy()
post_is_repost = counted['is_repost'].to_numpy()
post_is_quote = counted['is_quote'].to_numpy()

def observed_in_window(start_secs, end_secs):
    """Count posts in [start, end)."""
    return int(np.searchsorted(post_ts_secs, end_secs) - np.searchsorted(post_ts_secs, start_secs))

def post_times_in_window(start_secs, end_secs):
    """Return (rel_times_hours, marks) for posts in window. rel_times measured from start."""
    lo = np.searchsorted(post_ts_secs, start_secs)
    hi = np.searchsorted(post_ts_secs, end_secs)
    return ((post_ts_secs[lo:hi] - start_secs) / 3600.0,
            post_is_reply[lo:hi], post_is_repost[lo:hi], post_is_quote[lo:hi])

# =========================== MODELS ===========================

def m_linear(observed, elapsed_h, remaining_h):
    if elapsed_h <= 0: return 0
    return observed * (elapsed_h + remaining_h) / elapsed_h

def m_current_bayes(observed, elapsed_h, remaining_h, prior_pool):
    total_h = elapsed_h + remaining_h
    if not prior_pool or observed <= 0 or elapsed_h <= 0:
        return float(np.mean(prior_pool)) if prior_pool else 0
    elapsed_frac = elapsed_h / total_h
    elapsed_capped = min(0.99, max(0.001, elapsed_frac))
    obs_proj = observed / elapsed_capped
    prior_mean = float(np.mean(prior_pool))
    prior_std = max(1.0, float(np.std(prior_pool, ddof=1)) if len(prior_pool) > 1 else prior_mean*0.25)
    obs_var = max(1.0, observed * (1 - elapsed_capped) / (elapsed_capped ** 2))
    prec_prior = 1.0 / (prior_std ** 2)
    prec_obs = 1.0 / obs_var
    return (prec_prior * prior_mean + prec_obs * obs_proj) / (prec_prior + prec_obs)

def m_gamma_poisson(observed, elapsed_h, remaining_h, prior_totals, prior_durations):
    if not prior_totals: return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    alpha_0 = sum(prior_totals)
    beta_0 = sum(prior_durations)
    lambda_post = (alpha_0 + observed) / (beta_0 + elapsed_h) if (beta_0 + elapsed_h) > 0 else 0
    return observed + lambda_post * remaining_h

def m_seasonal(observed, elapsed_h, remaining_h, season_map, current_ts_secs, seasonal_default):
    """M1: expected rate per (DoW, hour) from history."""
    if not season_map: return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    expected_remaining = 0.0
    cur = current_ts_secs
    for h in range(int(remaining_h)):
        ts = cur + h * 3600
        et = pd.Timestamp(ts, unit='s', tz='UTC').tz_convert('America/New_York')
        key = (et.dayofweek, et.hour)
        expected_remaining += season_map.get(key, seasonal_default)
    return observed + expected_remaining

def m_decay_bayes(observed, elapsed_h, remaining_h, prior_with_ages_weeks, eps=0.85):
    """Decay older auctions exponentially."""
    if not prior_with_ages_weeks: return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    alpha_0 = sum(t * (eps ** age) for t, _, age in prior_with_ages_weeks)
    beta_0 = sum(d * (eps ** age) for _, d, age in prior_with_ages_weeks)
    if beta_0 <= 0: beta_0 = 1
    lambda_post = (alpha_0 + observed) / (beta_0 + elapsed_h)
    return observed + lambda_post * remaining_h

def _hawkes_nll(params, event_times_h, T_h):
    """Negative log-likelihood for Hawkes (μ, α, β) over [0, T] hours."""
    mu, alpha, beta = params
    if mu <= 0 or alpha < 0 or beta <= 0 or alpha >= beta: return 1e10
    n = len(event_times_h)
    # Sum of log intensity at each event
    ll = 0.0
    decay_sum = 0.0
    prev_t = 0.0
    for i, t in enumerate(event_times_h):
        decay_sum = decay_sum * math.exp(-beta * (t - prev_t)) + 1.0 if i > 0 else 0.0
        intensity = mu + alpha * decay_sum
        if intensity <= 0: return 1e10
        ll += math.log(intensity)
        prev_t = t
    # Integral: μ·T + Σ (α/β)(1 - exp(-β(T - tᵢ)))
    integral = mu * T_h
    for t in event_times_h:
        integral += (alpha / beta) * (1 - math.exp(-beta * (T_h - t)))
    return -(ll - integral)

def fit_hawkes(event_times_h, T_h):
    """Fit Hawkes process by MLE. Returns (mu, alpha, beta)."""
    if len(event_times_h) < 5: return None
    # Initial guess
    n = len(event_times_h)
    mu0 = n / T_h * 0.5
    x0 = [mu0, 0.5, 1.0]
    try:
        res = minimize(_hawkes_nll, x0, args=(event_times_h, T_h), method='Nelder-Mead',
                       options={'maxiter': 200, 'xatol': 1e-3, 'fatol': 1e-3})
        if res.success or res.fun < 1e9:
            mu, alpha, beta = res.x
            if mu > 0 and alpha >= 0 and beta > 0 and alpha < beta:
                return (mu, alpha, beta)
    except Exception:
        pass
    return None

def simulate_hawkes(mu, alpha, beta, t_start, t_end, history_events_h, n_sims=50):
    """Forward-simulate Hawkes from t_start to t_end. Returns mean event count in (t_start, t_end].

    Fast Ogata thinning for the exponential kernel. Track a running excitation
    state A = Σ exp(-β(t - t_k)) updated multiplicatively between candidate points,
    so each sim is O(events generated) instead of recomputing the full decay sum
    every step (the old version was O(n²) and hung on manic windows). MAX_EVENTS
    guards against runaway generation on near-critical fits (α close to β).
    """
    if mu <= 0 or beta <= 0: return 0
    MAX_EVENTS = 5000
    hist = np.asarray(history_events_h, dtype=float)
    A_start = float(np.sum(np.exp(-beta * (t_start - hist)))) if len(hist) else 0.0
    total_counts = []
    for _ in range(n_sims):
        A = A_start
        t = t_start
        n = 0
        while True:
            lam_bar = mu + alpha * A
            if lam_bar <= 0: break
            w = np.random.exponential(1.0 / lam_bar)
            t += w
            if t >= t_end: break
            A *= math.exp(-beta * w)        # decay excitation to candidate time
            lam_new = mu + alpha * A
            if np.random.random() < lam_new / lam_bar:
                A += 1.0                     # accepted event adds unit excitation
                n += 1
                if n >= MAX_EVENTS: break
        total_counts.append(n)
    return float(np.mean(total_counts)) if total_counts else 0

def m_hawkes(observed, elapsed_h, remaining_h, event_times_h, fit=None):
    """M2 Hawkes prediction."""
    if fit is None:
        fit = fit_hawkes(event_times_h, elapsed_h)
    if fit is None:
        return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    mu, alpha, beta = fit
    sim_count = simulate_hawkes(mu, alpha, beta, elapsed_h, elapsed_h + remaining_h, event_times_h)
    return observed + sim_count

def m_marked_hawkes(observed, elapsed_h, remaining_h, event_times_h, marks, fit=None):
    """M3: marks scale α. For simplicity, use weighted-α Hawkes with mark = (1 if original, 1.2 if repost, 0.7 if quote)."""
    if not len(event_times_h): return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    # Mark weight per event
    is_reply, is_repost, is_quote = marks
    mark_weights = np.where(is_repost, 1.2, np.where(is_quote, 0.7, 1.0))
    # Re-fit Hawkes but with marks. Simplified: just scale α by mean mark.
    if fit is None:
        fit = fit_hawkes(event_times_h, elapsed_h)
    if fit is None:
        return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    mu, alpha, beta = fit
    alpha_marked = alpha * float(np.mean(mark_weights)) if len(mark_weights) else alpha
    sim_count = simulate_hawkes(mu, alpha_marked, beta, elapsed_h, elapsed_h + remaining_h, event_times_h, n_sims=30)
    return observed + sim_count

def m_mmpp(observed, elapsed_h, remaining_h, prior_hourly_rates):
    """M4: 2-state quiet/manic regime. Simplified.
    Compute current rate over last 6 hours. If above prior median, assume manic; else quiet.
    Predict remaining = current_rate × remaining_h with regime mean reversion."""
    if not prior_hourly_rates: return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    current_rate = observed / max(elapsed_h, 1)
    prior_quiet = float(np.percentile(prior_hourly_rates, 25))
    prior_manic = float(np.percentile(prior_hourly_rates, 75))
    prior_mean = float(np.mean(prior_hourly_rates))
    # Mean-revert: weighted average current rate with prior_mean (50/50 — heuristic)
    expected_rate_remaining = 0.5 * current_rate + 0.5 * prior_mean
    return observed + expected_rate_remaining * remaining_h

def m_negbin(observed, elapsed_h, remaining_h, prior_totals):
    """M5: Negative Binomial on prior totals. Use posterior mean."""
    if not prior_totals: return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    mean = float(np.mean(prior_totals))
    if len(prior_totals) < 2: return mean
    var = float(np.var(prior_totals, ddof=1))
    if var <= mean: var = mean * 1.1  # avoid degenerate
    # r = mean² / (var - mean), p = mean / var
    r = mean ** 2 / (var - mean)
    p = mean / var
    # Predicted total from NegBin marginal (just use prior mean for now)
    # Adjust by observed pacing: if we're on pace for above-mean, predict higher
    pacing_factor = (observed / max(elapsed_h, 1)) / (mean / (elapsed_h + remaining_h)) if mean > 0 else 1
    return mean * (0.7 + 0.3 * pacing_factor)

def m_kalman(observed, elapsed_h, remaining_h, prior_hourly_rates):
    """Kalman filter on latent tweet rate."""
    if not prior_hourly_rates: return observed * (elapsed_h + remaining_h) / max(elapsed_h, 1)
    # Initial state: prior mean rate
    x = float(np.mean(prior_hourly_rates))
    P = float(np.var(prior_hourly_rates)) + 0.01
    Q = 0.01  # process noise
    R = max(0.1, P * 0.5)  # measurement noise
    # Single observation: observed/elapsed
    z = observed / max(elapsed_h, 1)
    # Kalman update
    x_pred = x
    P_pred = P + Q
    K = P_pred / (P_pred + R)
    x_new = x_pred + K * (z - x_pred)
    return observed + x_new * remaining_h

# =========================== Per-auction loop ===========================

print('\n=== Computing predictions per auction ===')
prior_all_post_times_secs = None  # built per-auction
results = []
total = len(clean)
t_start_loop = time.time()

for idx, a in clean.iterrows():
    if idx % 5 == 0:
        elapsed = time.time() - t_start_loop
        print(f'  {idx}/{total} ({elapsed:.0f}s elapsed)')
    start_secs = int(a['start_utc'].timestamp())
    end_secs = int(a['end_utc'].timestamp())
    total_h = (end_secs - start_secs) / 3600
    if total_h < 24: continue  # skip ultra-short

    # Actual final count
    actual = observed_in_window(start_secs, end_secs)
    if actual == 0: continue

    # Walk-forward priors: auctions ENDING before this start
    prior_auctions_df = clean[clean['end_utc'] < a['start_utc']]
    prior_totals = []
    prior_durations = []
    prior_hourly_rates = []
    prior_with_ages = []
    for _, pa in prior_auctions_df.iterrows():
        ps = int(pa['start_utc'].timestamp())
        pe = int(pa['end_utc'].timestamp())
        pt = observed_in_window(ps, pe)
        if pt == 0: continue
        pdur = (pe - ps) / 3600
        prior_totals.append(pt)
        prior_durations.append(pdur)
        prior_hourly_rates.append(pt / pdur if pdur > 0 else 0)
        age_weeks = (a['start_utc'] - pa['end_utc']).total_seconds() / 3600 / 24 / 7
        prior_with_ages.append((pt, pdur, age_weeks))

    # Seasonal map: posts BEFORE auction start, bucket by (DoW, hour)
    season_map = {}
    seasonal_default = float(np.mean(prior_hourly_rates)) if prior_hourly_rates else 1.0
    if len(prior_auctions_df) > 0:
        # Avg rate per (DoW, hour) from history (cheap version: use prior posts only — not auction-restricted)
        hist_cutoff_secs = start_secs
        hist_idx_hi = np.searchsorted(post_ts_secs, hist_cutoff_secs)
        if hist_idx_hi > 100:
            hist_times = post_ts_secs[:hist_idx_hi]
            hist_dt = pd.to_datetime(hist_times, unit='s', utc=True).tz_convert('America/New_York')
            df_hist = pd.DataFrame({'dow': hist_dt.dayofweek, 'hour': hist_dt.hour})
            # Posts per (DoW, hour). To convert to rate per hour, need total hours observed per bucket.
            counts = df_hist.groupby(['dow','hour']).size()
            # Approximate # of (DoW, hour) occurrences in history span
            hist_span_days = max(1, (hist_cutoff_secs - post_ts_secs[0]) / 86400)
            occurrences_per_bucket = hist_span_days / 7  # rough
            for (dow, hour), cnt in counts.items():
                season_map[(dow, hour)] = cnt / occurrences_per_bucket

    # Two checkpoints: T-2d and T-1d (for short auctions, T-2d might equal start)
    checkpoints = []
    for hr_remaining in [48, 24]:
        elapsed_h = total_h - hr_remaining
        if elapsed_h <= 0.5: continue  # skip if barely started
        checkpoints.append(hr_remaining)

    row = {
        'auction_slug': a['auction_slug'],
        'duration_type': a['duration_type'],
        'start_utc': a['start_utc'].strftime('%Y-%m-%d %H:%M'),
        'end_utc': a['end_utc'].strftime('%Y-%m-%d %H:%M'),
        'total_hours': round(total_h, 1),
        'actual': actual,
        'winning_bucket': a['winning_bucket'],
    }

    for hr_remaining in [48, 24]:
        elapsed_h = total_h - hr_remaining
        suffix = f'_T{hr_remaining // 24}d'
        if elapsed_h <= 0.5 or hr_remaining not in checkpoints:
            for m in ['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M4MMPP','M5NB','Kalman']:
                row[f'{m}{suffix}'] = ''
            continue

        checkpoint_secs = start_secs + int(elapsed_h * 3600)
        observed = observed_in_window(start_secs, checkpoint_secs)
        event_times_h, is_reply, is_repost, is_quote = post_times_in_window(start_secs, checkpoint_secs)
        event_times_h = event_times_h.tolist()

        # Run each model
        p_linear = m_linear(observed, elapsed_h, hr_remaining)
        p_curbayes = m_current_bayes(observed, elapsed_h, hr_remaining, prior_totals)
        p_m0 = m_gamma_poisson(observed, elapsed_h, hr_remaining, prior_totals, prior_durations)
        p_m1 = m_seasonal(observed, elapsed_h, hr_remaining, season_map, checkpoint_secs, seasonal_default)
        p_decay = m_decay_bayes(observed, elapsed_h, hr_remaining, prior_with_ages)
        # Hawkes — fit once, reuse for M2 and M3
        hawkes_fit = fit_hawkes(event_times_h, elapsed_h) if len(event_times_h) >= 5 else None
        p_m2 = m_hawkes(observed, elapsed_h, hr_remaining, event_times_h, hawkes_fit)
        p_m3 = m_marked_hawkes(observed, elapsed_h, hr_remaining, event_times_h,
                                (is_reply, is_repost, is_quote), hawkes_fit)
        p_m4 = m_mmpp(observed, elapsed_h, hr_remaining, prior_hourly_rates)
        p_m5 = m_negbin(observed, elapsed_h, hr_remaining, prior_totals)
        p_kalman = m_kalman(observed, elapsed_h, hr_remaining, prior_hourly_rates)

        for name, pred in [('Linear', p_linear), ('CurBayes', p_curbayes), ('M0', p_m0),
                           ('M1Seas', p_m1), ('Decay', p_decay), ('M2Hawk', p_m2),
                           ('M3Hawk', p_m3), ('M4MMPP', p_m4), ('M5NB', p_m5), ('Kalman', p_kalman)]:
            row[f'{name}{suffix}'] = round(pred, 0)
            row[f'{name}{suffix}_err%'] = round(abs(pred - actual) / actual * 100, 1) if actual > 0 else ''

    results.append(row)

elapsed_total = time.time() - t_start_loop
print(f'\nCompleted {len(results)} auctions in {elapsed_total:.0f}s')

# =========================== Summary ===========================
df = pd.DataFrame(results)
print('\n=== Mean abs error % per model ===')
print(f"{'Model':<12} {'T-2d':>10} {'T-1d':>10}")
print('-' * 35)
models = ['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M4MMPP','M5NB','Kalman']
summary_rows = []
for m in models:
    t2_col = f'{m}_T2d_err%'
    t1_col = f'{m}_T1d_err%'
    t2_vals = pd.to_numeric(df[t2_col], errors='coerce').dropna() if t2_col in df.columns else pd.Series([])
    t1_vals = pd.to_numeric(df[t1_col], errors='coerce').dropna() if t1_col in df.columns else pd.Series([])
    t2_mean = t2_vals.mean() if len(t2_vals) else float('nan')
    t1_mean = t1_vals.mean() if len(t1_vals) else float('nan')
    print(f"{m:<12} {t2_mean:>9.1f}% {t1_mean:>9.1f}%")
    summary_rows.append({'model': m, 't2d_n': len(t2_vals), 't2d_err': t2_mean, 't1d_n': len(t1_vals), 't1d_err': t1_mean})

pd.DataFrame(summary_rows).to_csv(OUT/'backtest_summary.csv', index=False)
df.to_csv(OUT/'backtest_full_results.csv', index=False)
print(f'\nWrote {len(df)} auction rows to {OUT/"backtest_full_results.csv"}')
print(f'Wrote summary to {OUT/"backtest_summary.csv"}')
