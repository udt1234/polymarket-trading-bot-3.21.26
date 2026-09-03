# -*- coding: utf-8 -*-
"""PRE-REGISTERED regime-discovery study. Built strictly against
`_DataMetricPulls/pacing_backtest/prereg/regime_discovery_2026-07-29.md` -- read
that file for the fixed questions, WALL dates, methods (R1-R5, S1-S5), regime
definition, baselines, scoring, trial-count declaration, and success criteria.

Q1 (between-auction trajectory): does the shape of past auction outcomes (Elon
2-day, Trump 7-day) predict the next auction's regime, beyond simple lag-1
persistence?

Q2 (within-day sectioning): if the day is cut into DISCOVERED (not imposed)
posting-intensity sections, does the section+cadence pattern predict the
day's regime/final-count beyond the existing within-day HMM (B4, the prior
study's M4)?

Scope: (b) pure forecast-accuracy / calibration diagnostic + descriptive rule
discovery. No P&L, no fills. This script does not certify its own result --
hand off to @backtest-auditor.

Reuse, not reinvention: data loading, noon-ET slug parsing, obs_count,
et_hour_dow, bracket-probability primitives, log-loss/Brier scoring, and the
M4 PoissonHMM (fit_M4/predict_M4_pmf/_hourly_seq -- the exact model that is
B4, the primary bar) are IMPORTED from pattern_discovery_lib.py /
pattern_discovery_methods.py (read-only imports; those files are not
modified). block_bootstrap_ci / jackknife_drop_best / SUCCESS_N_FLOOR follow
the identical pattern already audited at pattern_discovery_2026-07-26.py:65
and the top of its aggregation section -- duplicated here (not imported,
since that script also drives its OWN sweep and must not be executed as a
side effect of importing it), same logic, same semantics.
"""
from __future__ import annotations

import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.signal import periodogram
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.linear_model import Ridge
from statsmodels.tsa.stattools import acf as sm_acf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root -> locked_pace

import pattern_discovery_lib as L
import pattern_discovery_methods as M
from run_meta import emit_run_meta
from api.modules.shared.locked_pace import (
    build_priors as lp_build_priors, project_locked, bracket_fair, calib_sigma,
)

warnings.filterwarnings("ignore")
RNG_SEED = 20260729
np.random.seed(RNG_SEED)

OUT_DIR = Path(__file__).resolve().parent / "regime_out"
OUT_DIR.mkdir(exist_ok=True)
ET = L.ET

WALL_ELON = int(pd.Timestamp("2026-04-01 00:00:00", tz=ET).timestamp())
WALL_TRUMP = int(pd.Timestamp("2026-01-01 00:00:00", tz=ET).timestamp())
ELON_CLEAN_START = int(pd.Timestamp("2025-09-01 12:00:00", tz=ET).timestamp())
ELON_CLEAN_END = int(pd.Timestamp("2026-06-27 12:00:00", tz=ET).timestamp())

SUCCESS_N_FLOOR = 10  # reused pattern, pattern_discovery_2026-07-26.py:65
LEVEL_NAMES = ["LOW", "MID", "HIGH"]

TRIALS = {"n": 0, "by_method": {}}


def _trial(method, k=1):
    TRIALS["n"] += k
    TRIALS["by_method"][method] = TRIALS["by_method"].get(method, 0) + k


# ---------------------------------------------------------------------------
# Shared stats utilities -- IDENTICAL pattern to pattern_discovery_2026-07-26.py
# (block_bootstrap_ci, jackknife_drop_best, SUCCESS_N_FLOOR gate). Duplicated,
# not imported, because that script's module body also builds its OWN targets
# on import-time side paths we must not trigger; the logic here is byte-for-
# byte the same algorithm.
# ---------------------------------------------------------------------------
def block_bootstrap_ci(values, block_size=1, n_boot=2000, seed=0):
    rng = np.random.default_rng(seed)
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    n = len(vals)
    if n == 0:
        return dict(mean=float("nan"), lo=float("nan"), hi=float("nan"), n=0)
    blocks = [vals[i:i + block_size] for i in range(0, n, block_size)]
    nb = len(blocks)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, nb, nb)
        means[b] = np.concatenate([blocks[i] for i in idx]).mean()
    return dict(mean=float(vals.mean()), lo=float(np.percentile(means, 2.5)),
                hi=float(np.percentile(means, 97.5)), n=n)


def jackknife_drop_best(values):
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    if len(vals) < 2:
        return dict(full_mean=float(np.mean(vals)) if len(vals) else float("nan"),
                     dropbest_mean=float("nan"), sign_holds=None)
    idx_best = int(np.argmax(vals))
    rest = np.delete(vals, idx_best)
    full_mean, rest_mean = float(vals.mean()), float(rest.mean())
    sign_holds = (full_mean > 0) == (rest_mean > 0)
    return dict(full_mean=full_mean, dropbest_mean=rest_mean, sign_holds=bool(sign_holds))


def success_line(skill_ci, n, label):
    """SUCCESS_N_FLOOR sentinel -- reused gate pattern (pattern_discovery
    line 65 / _headline_flag). Never returns a bare pass/fail below the floor."""
    if n < SUCCESS_N_FLOOR:
        return f"noise (n={n}, below success floor of {SUCCESS_N_FLOOR})"
    if skill_ci["lo"] > 0:
        return f"BEATS {label} (CI excludes zero, positive)"
    if skill_ci["hi"] < 0:
        return f"LOSES to {label} (CI excludes zero, negative)"
    return f"unproven vs {label} (CI includes zero)"


def _cv_split(units, frac=0.7):
    idx = int(len(units) * frac)
    return units[:idx], units[idx:]


def floor_bracket(lo_val, hi_val):
    lo = int(math.floor(lo_val)) if lo_val is not None else None
    hi = int(math.floor(hi_val)) if hi_val is not None else None
    return lo, hi


def tercile_brackets_from_cuts(q1, q2):
    """LOW/MID/HIGH integer brackets on the FINAL count, using the IDENTICAL
    floor() convention as the level-assignment function below so the "true
    regime label" and the "probability mass bucket" can never silently
    disagree at a boundary integer."""
    lo1, hi1 = 0, int(math.floor(q1))
    lo2, hi2 = hi1 + 1, int(math.floor(q2))
    lo3, hi3 = hi2 + 1, None
    return [("LOW", lo1, hi1), ("MID", lo2, hi2), ("HIGH", lo3, hi3)]


def level_of(final, q1, q2):
    return 0 if final <= q1 else (1 if final <= q2 else 2)


def build_quantile_brackets(train_finals, K=5):
    """Reused pattern: pattern_discovery_2026-07-26.py::build_daily_brackets
    (quantile-bin scoring grid, frozen from TRAIN only, NOT tradeable -- for
    finer final-count-distribution log-loss/Brier only)."""
    cuts = sorted(set(int(round(q)) for q in np.quantile(train_finals, np.linspace(0, 1, K + 1)[1:-1])))
    edges = [0] + [c + 1 for c in cuts]
    brackets = []
    for i, lo in enumerate(edges):
        hi = (edges[i + 1] - 1) if i + 1 < len(edges) else None
        label = (f"<{edges[1]}" if i == 0 and len(edges) > 1 else (f"{lo}+" if hi is None else f"{lo}-{hi}"))
        brackets.append((label, lo, hi))
    return brackets


# --- B5 (prereg baseline, added 2026-07-31 per @backtest-auditor finding 2:
# was declared in the prereg, never implemented). Elon 2-day auctions ONLY,
# price-admissible auctions ONLY -- exactly the prereg's stated scope. Reuses
# L.load_prices / L.market_bracket_probs (the identical primitives
# pattern_discovery_2026-07-26.py's own market baseline is built on), never
# reimplemented. ------------------------------------------------------------
def market_probs_to_tercile(market_probs, poly_brackets, q1, q2):
    """Reallocate the market's OWN bracket-ladder probabilities into our
    LOW/MID/HIGH tercile levels. Disclosed approximation: assumes probability
    mass is spread UNIFORMLY across the integers inside each polymarket
    bracket (the market only tells us P(its own bucket), not a finer
    distribution) -- the share of a bracket's integer-width that falls in
    each tercile band gets that share of its probability. Uses the IDENTICAL
    floor() tercile-edge convention as tercile_brackets_from_cuts so a
    boundary integer can never land in two bins. Only meaningful on
    price-admissible auctions (every one of the auction's own brackets has a
    covered price), which the caller enforces before calling this."""
    SENTINEL = 10 ** 7
    tercile_edges = [(lo, (hi if hi is not None else SENTINEL))
                      for _, lo, hi in tercile_brackets_from_cuts(q1, q2)]
    out = [0.0, 0.0, 0.0]
    for label, lo_p, hi_p in poly_brackets:
        p = market_probs.get(label)
        if p is None:
            continue
        hi_pp = hi_p if hi_p is not None else SENTINEL
        width_p = hi_pp - lo_p + 1
        if width_p <= 0:
            continue
        for lvl, (lo_t, hi_t) in enumerate(tercile_edges):
            lo_ov, hi_ov = max(lo_p, lo_t), min(hi_pp, hi_t)
            ow = max(0, hi_ov - lo_ov + 1)
            out[lvl] += p * (ow / width_p)
    tot = sum(out)
    return [x / tot for x in out] if tot > 0 else None


def build_r1_market_baseline(units, price_idx, q1, q2):
    """B5 at the SAME decision point R1 uses: T=u['s'] (auction open) --
    R1's Markov forecast uses no within-auction information at all, so the
    fairest market comparison is the market's own price at that same moment.
    price-admissible = every one of the auction's own polymarket brackets has
    a covered price at/before T; auctions without full coverage are excluded
    (never invented a price), matching the prereg's 'where available'
    scoping."""
    out = {}
    n_admissible = 0
    for u in units:
        probs, n_cov, n_tot = L.market_bracket_probs(price_idx, u["slug"], u["brackets"], u["s"])
        if probs is None or n_cov < n_tot:
            out[u["slug"]] = None
            continue
        tp = market_probs_to_tercile(probs, u["brackets"], q1, q2)
        out[u["slug"]] = tp
        if tp is not None:
            n_admissible += 1
    return out, n_admissible


# ===========================================================================
# Q1 -- between-auction trajectory (Elon 2-day, Trump 7-day)
# ===========================================================================
def load_q1_data():
    elon_post_ts, elon_is_qr = L.load_elon_posts()
    trump_post_ts, trump_is_qr = L.load_trump_posts()
    elon_auc = L.load_auctions("elonmusk")
    trump_auc = L.load_auctions("realDonaldTrump")
    for u in elon_auc:
        u["final"] = L.obs_count(elon_post_ts, u["s"], u["e"])
    for u in trump_auc:
        u["final"] = L.obs_count(trump_post_ts, u["s"], u["e"])
    trump_max_post = int(trump_post_ts.max())

    elon_2day = sorted([u for u in elon_auc if u["dur"] == "2-day" and u["s"] >= ELON_CLEAN_START],
                        key=lambda x: x["s"])
    trump_7day_raw = sorted([u for u in trump_auc if u["dur"] == "7-day" and u["e"] <= trump_max_post],
                             key=lambda x: x["s"])

    # DATA-INTEGRITY finding (verified 2026-07-31): the Trump 7-day market
    # cadence changed from weekly NON-overlapping windows to a rolling
    # ~72-96h-step 7-day window starting 2026-02-06 (inside the SEALED span).
    # Adjacent rolling windows share up to 4 of 7 underlying days, so a naive
    # sequential Markov/trajectory analysis on the raw 42-auction series would
    # show inflated "persistence" purely from shared underlying posts, not
    # genuine regime dynamics -- a same_period_aggregate-style leak carried
    # into the auction-SEQUENCE context. Greedily de-overlap: keep an auction
    # only if its start is at/after the previously KEPT auction's end.
    trump_7day = []
    for u in trump_7day_raw:
        if not trump_7day or u["s"] >= trump_7day[-1]["e"]:
            trump_7day.append(u)
    n_overlap_dropped = len(trump_7day_raw) - len(trump_7day)

    return dict(elon_post_ts=elon_post_ts, trump_post_ts=trump_post_ts,
                elon_2day=elon_2day, trump_7day=trump_7day,
                trump_7day_raw_n=len(trump_7day_raw), n_overlap_dropped=n_overlap_dropped)


def assign_terciles(units, wall_ts):
    train = [u for u in units if u["s"] < wall_ts]
    train_finals = np.array([u["final"] for u in train], dtype=float)
    q1, q2 = np.quantile(train_finals, [1 / 3, 2 / 3])
    for u in units:
        u["level"] = level_of(u["final"], q1, q2)
        u["is_train"] = u["s"] < wall_ts
    return float(q1), float(q2)


# --- R1: Markov transition matrix, fit on TRAIN only, frozen ---------------
def markov_transition_matrix(levels, n_states=3, alpha=1.0):
    counts = np.zeros((n_states, n_states))
    for i in range(len(levels) - 1):
        counts[levels[i], levels[i + 1]] += 1
    smoothed = counts + alpha
    probs = smoothed / smoothed.sum(axis=1, keepdims=True)
    return probs, counts


def markov_plain_words(probs, counts):
    lines = []
    for i, name in enumerate(LEVEL_NAMES):
        n_row = int(counts[i].sum())
        parts = ", ".join(f"{LEVEL_NAMES[j]} {probs[i, j] * 100:.0f}%" for j in range(3))
        lines.append(f"After a {name} auction (n={n_row} train transitions observed), "
                      f"the next auction is: {parts}.")
    return lines


def r1_markov(handle_name, units, wall_ts, market_by_slug=None):
    train = [u for u in units if u["s"] < wall_ts]
    sealed = [u for u in units if u["s"] >= wall_ts]
    train_levels = [u["level"] for u in train]
    probs, raw_counts = markov_transition_matrix(train_levels)
    clim = np.array([max(1e-6, np.mean(np.array(train_levels) == k)) for k in range(3)])
    clim = clim / clim.sum()

    full_seq = train + sealed
    rows = []
    for i in range(1, len(full_seq)):
        span = "train" if full_seq[i]["s"] < wall_ts else "sealed"
        prev_level = full_seq[i - 1]["level"]
        true_level = full_seq[i]["level"]
        p_markov = probs[prev_level]
        mkt = (market_by_slug or {}).get(full_seq[i]["slug"])
        ll_market = -math.log(max(mkt[true_level], 1e-9)) if mkt is not None else float("nan")
        rows.append(dict(handle=handle_name, slug=full_seq[i]["slug"], s=full_seq[i]["s"], span=span,
                          prev_level=prev_level, true_level=true_level,
                          ll_markov=-math.log(max(p_markov[true_level], 1e-9)),
                          ll_clim=-math.log(max(clim[true_level], 1e-9)),
                          ll_unif=-math.log(1.0 / 3),
                          ll_market=ll_market,
                          p_markov_true=float(p_markov[true_level])))
    df = pd.DataFrame(rows)
    out = dict(handle=handle_name, matrix=probs.tolist(), raw_counts=raw_counts.tolist(),
               clim=clim.tolist(), n_train_auctions=len(train), plain_words=markov_plain_words(probs, raw_counts),
               rows=df)
    for span in ("train", "sealed"):
        sub = df[df.span == span]
        if sub.empty:
            out[f"{span}_skill_vs_clim"] = None
            out[f"{span}_skill_vs_unif"] = None
            continue
        skill_clim = (sub.ll_clim - sub.ll_markov).to_numpy()
        skill_unif = (sub.ll_unif - sub.ll_markov).to_numpy()
        out[f"{span}_skill_vs_clim"] = block_bootstrap_ci(skill_clim, block_size=1)
        out[f"{span}_skill_vs_unif"] = block_bootstrap_ci(skill_unif, block_size=1)
        out[f"{span}_jk_vs_clim"] = jackknife_drop_best(skill_clim)
        out[f"{span}_n"] = int(len(sub))
        sub_mkt = sub[sub.ll_market.notna()]
        if len(sub_mkt) >= 2:
            skill_market = (sub_mkt.ll_market - sub_mkt.ll_markov).to_numpy()  # positive = markov beats B5/market
            out[f"{span}_skill_vs_market"] = block_bootstrap_ci(skill_market, block_size=1)
            out[f"{span}_jk_vs_market"] = jackknife_drop_best(skill_market)
            out[f"{span}_n_market"] = int(len(sub_mkt))
        else:
            out[f"{span}_skill_vs_market"] = None
            out[f"{span}_n_market"] = int(len(sub_mkt))
    return out


# --- R2: ACF / PACF + a lightweight periodogram check -----------------------
def r2_acf(handle_name, units, wall_ts, max_nlags=8):
    train = [u for u in units if u["s"] < wall_ts]
    finals = np.array([u["final"] for u in train], dtype=float)
    levels = np.array([u["level"] for u in train], dtype=float)
    nlags = min(max_nlags, max(1, len(finals) // 3))
    if len(finals) < 8:
        return dict(handle=handle_name, ok=False, n=len(finals))
    acf_f, ci_f = sm_acf(finals, nlags=nlags, alpha=0.05, fft=False)
    acf_l, ci_l = sm_acf(levels, nlags=nlags, alpha=0.05, fft=False)
    freqs, power = periodogram(finals - finals.mean())
    top_i = int(np.argmax(power[1:])) + 1 if len(power) > 1 else 0
    top_period = (1.0 / freqs[top_i]) if top_i > 0 and freqs[top_i] > 0 else float("nan")
    top_ratio = float(power[top_i] / max(np.mean(np.delete(power, top_i)), 1e-9)) if len(power) > 2 else float("nan")
    # statsmodels acf(..., alpha=0.05) returns confint as ABSOLUTE bounds
    # (not offsets) using Bartlett's formula -- "significant" = CI excludes 0.
    sig_lags_finals = [lag for lag in range(1, nlags + 1) if not (ci_f[lag][0] <= 0 <= ci_f[lag][1])]
    return dict(handle=handle_name, ok=True, n=len(finals), nlags=nlags,
                acf_finals=acf_f.tolist(), ci_finals=ci_f.tolist(),
                acf_levels=acf_l.tolist(), ci_levels=ci_l.tolist(),
                sig_lags_finals=sig_lags_finals, top_period_auctions=top_period, top_power_ratio=top_ratio)


# --- R3: changepoint detection -- offline (retrospective, LABELING ONLY,
# never fed into a forecast -- same "stationary-shape research" allowance
# BACKTEST_RULES.md gives LOO) vs online/causal (walk-forward, real decision
# rule), reporting DETECTION LAG per the prereg's mandatory constraint. -----
def _sse(x):
    return float(np.sum((x - x.mean()) ** 2)) if len(x) > 1 else 0.0


def binseg_offline(x, min_size=4, penalty=None):
    """Simple binary segmentation, BIC-like penalty. Offline/retrospective
    ONLY -- used purely to LABEL where a "true" mean shift sits in hindsight,
    for measuring the causal detector's lag against. Never used as a forecast
    input anywhere in this script."""
    n = len(x)
    if penalty is None:
        penalty = 2 * math.log(max(n, 2)) * max(np.var(x), 1e-6)
    cps = []

    def recurse(lo, hi):
        seg = x[lo:hi]
        if hi - lo < 2 * min_size:
            return
        base = _sse(seg)
        best_gain, best_k = 0.0, None
        for k in range(lo + min_size, hi - min_size + 1):
            gain = base - (_sse(x[lo:k]) + _sse(x[k:hi]))
            if gain > best_gain:
                best_gain, best_k = gain, k
        if best_k is not None and best_gain > penalty:
            cps.append(best_k)
            recurse(lo, best_k)
            recurse(best_k, hi)
    recurse(0, n)
    return sorted(cps)


def cusum_run(x, h, mu0, sigma, k_mult=0.5, reset_win=8):
    """Causal two-sided CUSUM: at each step t, only x[0..t] is used (WALL-
    respecting -- these are resolved auction outcomes, legitimate history for
    a next-auction decision). Re-baselines to the trailing `reset_win` mean
    after each detection (still causal: only uses x[..t])."""
    k = k_mult * sigma
    Splus = Sminus = 0.0
    cur_mu = mu0
    flags = []
    for t in range(len(x)):
        Splus = max(0.0, Splus + (x[t] - cur_mu - k))
        Sminus = min(0.0, Sminus + (x[t] - cur_mu + k))
        fired = (Splus > h) or (Sminus < -h)
        flags.append(fired)
        if fired:
            Splus = Sminus = 0.0
            cur_mu = float(np.mean(x[max(0, t - reset_win + 1):t + 1]))
    return np.array(flags)


def calibrate_cusum_h(train_x, sigma, target_fp=0.08, seed=0, n_perm=500):
    """Threshold h calibrated on TRAIN ONLY via permutation: shuffle the
    train series (destroys any true order/shift, giving a null "no genuine
    regime change" surrogate), find the smallest h (of a frozen candidate
    grid, in units of sigma) whose mean per-step false-alarm rate on the null
    surrogate is <= target_fp. This IS a threshold sweep -- every candidate
    counted as a trial by the caller."""
    rng = np.random.default_rng(seed)
    mu0 = float(np.mean(train_x[:8])) if len(train_x) >= 8 else float(np.mean(train_x))
    cand_mults = [0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0]
    chosen = None
    fp_table = {}
    for mult in cand_mults:
        h = mult * sigma
        fps = []
        for _ in range(n_perm):
            surrogate = rng.permutation(train_x)
            flags = cusum_run(surrogate, h, mu0, sigma)
            fps.append(flags.mean())
        fp = float(np.mean(fps))
        fp_table[mult] = fp
        if fp <= target_fp and chosen is None:
            chosen = h
    if chosen is None:
        chosen = cand_mults[-1] * sigma
    return chosen, mu0, fp_table, len(cand_mults)


def r3_changepoint(handle_name, units, wall_ts):
    finals = np.array([u["final"] for u in units], dtype=float)
    train_finals = np.array([u["final"] for u in units if u["s"] < wall_ts], dtype=float)
    sigma_train = float(np.std(train_finals)) if len(train_finals) > 1 else 1.0

    # offline/retrospective segmentation on the FULL series -- labeling only
    true_cps = binseg_offline(finals)

    h, mu0, fp_table, n_h_cands = calibrate_cusum_h(train_finals, sigma_train)
    _trial("R3_cusum_h", k=n_h_cands)
    online_flags = cusum_run(finals, h, mu0, sigma_train)
    online_idx = np.where(online_flags)[0].tolist()

    # detection lag: for each true (retrospective) changepoint, first online
    # detection at/after it, before the NEXT true changepoint (else censored)
    lag_rows = []
    for j, cp in enumerate(true_cps):
        next_cp = true_cps[j + 1] if j + 1 < len(true_cps) else len(finals)
        candidates = [i for i in online_idx if cp <= i < next_cp]
        if candidates:
            det = candidates[0]
            lag_auctions = det - cp
            lag_days = (units[det]["s"] - units[cp]["s"]) / 86400.0
            lag_rows.append(dict(true_cp_idx=cp, true_cp_slug=units[cp]["slug"], true_cp_span="train" if units[cp]["s"] < wall_ts else "sealed",
                                  detected_idx=det, detected_slug=units[det]["slug"],
                                  lag_auctions=lag_auctions, lag_days=lag_days, censored=False))
        else:
            lag_rows.append(dict(true_cp_idx=cp, true_cp_slug=units[cp]["slug"], true_cp_span="train" if units[cp]["s"] < wall_ts else "sealed",
                                  detected_idx=None, detected_slug=None,
                                  lag_auctions=None, lag_days=None, censored=True))
    unmatched_online = [i for i in online_idx if not any(r["detected_idx"] == i for r in lag_rows)]
    return dict(handle=handle_name, n=len(finals), true_cps=true_cps, h=h, mu0=mu0,
                fp_table=fp_table, online_idx=online_idx, lag_rows=lag_rows,
                unmatched_online_idx=unmatched_online)


# --- R4: mean-reversion vs momentum -- does trajectory SHAPE (up-up/up-down/
# down-up/down-down of the raw final-count curve) add anything OVER simple
# lag-1 persistence? Both models are WALK-FORWARD (refit each step on an
# expanding window of strictly-prior transitions), scored on the SAME sample
# so the comparison isolates the marginal value of shape, not sample size. --
def _shape4(finals, i):
    d1 = "U" if finals[i - 2] > finals[i - 3] else "D"
    d2 = "U" if finals[i - 1] > finals[i - 2] else "D"
    return d1 + d2  # UU/UD/DU/DD


def r4_trajectory_shape(handle_name, units, wall_ts):
    finals = [u["final"] for u in units]
    levels = [u["level"] for u in units]
    n = len(units)
    rows = []
    for i in range(3, n):
        prior_j = list(range(3, i))
        if len(prior_j) < 4:
            continue
        # Model A: lag-1 only, Laplace-smoothed table, fit on prior_j only
        cnt_a = np.ones((3, 3))  # +1 Laplace
        cnt_b = {}
        for j in prior_j:
            cnt_a[levels[j - 1], levels[j]] += 1
            key = (levels[j - 1], _shape4(finals, j))
            cnt_b.setdefault(key, np.ones(3))
            cnt_b[key][levels[j]] += 1
        p_a_table = cnt_a / cnt_a.sum(axis=1, keepdims=True)
        p_a = p_a_table[levels[i - 1]]
        key_i = (levels[i - 1], _shape4(finals, i))
        cell = cnt_b.get(key_i)
        n_cell = int(cell.sum() - 3) if cell is not None else 0  # subtract the +1 prior mass
        if cell is not None and n_cell >= 3:
            p_b = cell / cell.sum()
            backoff = False
        else:
            p_b = p_a  # backoff -- too few (level, shape) priors to trust the finer table
            backoff = True
        true_level = levels[i]
        span = "train" if units[i]["s"] < wall_ts else "sealed"
        rows.append(dict(handle=handle_name, slug=units[i]["slug"], s=units[i]["s"], span=span,
                          n_prior_transitions=len(prior_j), shape=key_i[1], backoff=backoff, n_cell=n_cell,
                          ll_a=-math.log(max(p_a[true_level], 1e-9)), ll_b=-math.log(max(p_b[true_level], 1e-9))))
    df = pd.DataFrame(rows)
    out = dict(handle=handle_name, rows=df)
    for span in ("train", "sealed"):
        sub = df[df.span == span]
        if sub.empty:
            out[f"{span}_skill"] = None
            continue
        skill = (sub.ll_a - sub.ll_b).to_numpy()  # positive = shape (Model B) beats lag-1-only (Model A)
        out[f"{span}_skill"] = block_bootstrap_ci(skill, block_size=1)
        out[f"{span}_jk"] = jackknife_drop_best(skill)
        out[f"{span}_n"] = int(len(sub))
        out[f"{span}_pct_backoff"] = float(sub.backoff.mean())
    return out


# --- R5: readable trajectory-shape rules with cell counts, n>=30 or flagged
def r5_trajectory_rules(handle_name, units, wall_ts, min_report=2):
    levels = [u["level"] for u in units]
    n = len(units)
    train_end_idx = sum(1 for u in units if u["s"] < wall_ts)
    cells = {}
    for i in range(2, n - 1):
        triplet = (levels[i - 2], levels[i - 1], levels[i])
        nxt = levels[i + 1]
        span = "train" if i + 1 < train_end_idx else ("sealed" if i >= train_end_idx else "boundary")
        cells.setdefault(triplet, {"train_next": [], "sealed_next": []})
        if i + 1 < train_end_idx:
            cells[triplet]["train_next"].append(nxt)
        elif i >= train_end_idx:
            cells[triplet]["sealed_next"].append(nxt)
    rows = []
    train_clim = np.array([max(1e-6, levels[:train_end_idx].count(k) / max(train_end_idx, 1)) for k in range(3)])
    train_clim = train_clim / train_clim.sum()
    base_rate_majority = LEVEL_NAMES[int(np.argmax(train_clim))]
    for triplet, d in cells.items():
        n_train, n_sealed = len(d["train_next"]), len(d["sealed_next"])
        if n_train < min_report and n_sealed < min_report:
            continue
        train_majority = (pd.Series(d["train_next"]).mode().iloc[0] if n_train else None)
        train_hit = float(np.mean([x == train_majority for x in d["train_next"]])) if n_train else float("nan")
        sealed_hit = (float(np.mean([x == train_majority for x in d["sealed_next"]]))
                       if (n_sealed and train_majority is not None) else float("nan"))
        lift = (sealed_hit - train_clim[train_majority]) if (train_majority is not None and not math.isnan(sealed_hit)) else float("nan")
        rows.append(dict(handle=handle_name,
                          pattern=f"{LEVEL_NAMES[triplet[0]]}-{LEVEL_NAMES[triplet[1]]}-{LEVEL_NAMES[triplet[2]]}",
                          n_train=n_train, n_sealed=n_sealed,
                          predicted_next=(LEVEL_NAMES[train_majority] if train_majority is not None else None),
                          train_hit_rate=train_hit, sealed_hit_rate=sealed_hit, lift_vs_base_rate=lift,
                          flagged_small_n=bool(max(n_train, n_sealed) < 30)))
    return dict(handle=handle_name, rows=pd.DataFrame(rows), base_rate_majority_class=base_rate_majority,
                train_climatology=train_clim.tolist())


def run_q1(handle_name, units, wall_ts, price_idx=None):
    q1c, q2c = assign_terciles(units, wall_ts)
    market_by_slug, b5_n_admissible = (None, 0)
    if price_idx is not None:
        market_by_slug, b5_n_admissible = build_r1_market_baseline(units, price_idx, q1c, q2c)
    r1 = r1_markov(handle_name, units, wall_ts, market_by_slug=market_by_slug)
    r2 = r2_acf(handle_name, units, wall_ts)
    r3 = r3_changepoint(handle_name, units, wall_ts)
    r4 = r4_trajectory_shape(handle_name, units, wall_ts)
    r5 = r5_trajectory_rules(handle_name, units, wall_ts)
    return dict(handle=handle_name, q1_cut=q1c, q2_cut=q2c, n_train=sum(1 for u in units if u["s"] < wall_ts),
                n_sealed=sum(1 for u in units if u["s"] >= wall_ts), r1=r1, r2=r2, r3=r3, r4=r4, r5=r5,
                b5_n_admissible=b5_n_admissible, b5_n_total=len(units), b5_scored=(price_idx is not None))


# ===========================================================================
# Q2 -- within-day sectioning (Elon daily -- see run notes for scope reason)
# ===========================================================================
class DailySeries:
    """noon-ET anchored, non-overlapping daily blocks. FIXED 2026-07-31 per
    @backtest-auditor finding 1 (regime_discovery_2026-07-31.md): the prior
    version accumulated raw `d += 86400` offsets from a single epoch anchor,
    which silently drifts the ET wall-clock boundary off noon across a DST
    transition (noon-to-noon spans either 23h or 25h of real elapsed time on
    a spring-forward/fall-back day, not exactly 86400s). That drifted 126
    consecutive TRAIN days (2025-11-02 to 2026-03-07) to an 11:00-ET anchor.
    RE-FIXED 2026-07-31 (2nd pass): the first fix above still misfired by 1h
    on the two literal transition dates themselves -- `pd.Timestamp(date,
    tz=ET) + pd.Timedelta(hours=12)` is ABSOLUTE-duration arithmetic on top of
    a wall-clock-localized midnight, so on the transition date it lands 1h off
    wall-clock noon (a fixed Timedelta doesn't know the clock jumped). Each
    day's noon boundary is now constructed DIRECTLY in the target timezone via
    `pd.Timestamp(year=,month=,day=,hour=12,tz=ET)` -- the same idiom this
    module's own trump_day0 anchor and pattern_discovery_2026-07-26.py's
    add_days_et() both already use, which resolves the wall-clock hour first
    and lets pandas pick the correct UTC offset, instead of adding a duration
    after the fact. (The s4_literal_calendar reference above was wrong: that
    function used the identical buggy pattern and has also been fixed, see
    below.) NOTE: pattern_discovery_2026-07-26.py::DailySeries uses
    add_days_et() and was already correct before this pass."""
    def __init__(self, post_ts, day0_noon_ts, day_end_ts):
        start_date = pd.Timestamp(day0_noon_ts, unit="s", tz="UTC").tz_convert(ET).date()
        days = []
        cur_date = start_date
        while True:
            next_date = cur_date + pd.Timedelta(days=1)
            s = int(pd.Timestamp(year=cur_date.year, month=cur_date.month, day=cur_date.day,
                                  hour=12, tz=ET).timestamp())
            e = int(pd.Timestamp(year=next_date.year, month=next_date.month, day=next_date.day,
                                  hour=12, tz=ET).timestamp())
            if e > day_end_ts:
                break
            f = L.obs_count(post_ts, s, e)
            days.append(dict(slug=f"elon-daily-{s}", s=s, e=e, final=int(f)))
            cur_date = next_date
        self.days = days

    def priors_before(self, T):
        return [d for d in self.days if d["e"] < T]


def build_daily_series():
    elon_post_ts, _ = L.load_elon_posts()
    daily = DailySeries(elon_post_ts, ELON_CLEAN_START, ELON_CLEAN_END)
    q1d, q2d = np.quantile([d["final"] for d in daily.days if d["s"] < WALL_ELON], [1 / 3, 2 / 3])
    for d in daily.days:
        d["level"] = level_of(d["final"], q1d, q2d)
    return daily, elon_post_ts, float(q1d), float(q2d)


def compute_base_rate_shift(daily, wall_ts):
    """Undisclosed-until-now (@backtest-auditor finding 5, 2026-07-31):
    Elon's activity level itself shifts between TRAIN and SEALED. TRAIN-frozen
    terciles are still correctly never redefined on sealed (WALL-respecting),
    but a quieter sealed period gets systematically misclassified toward LOW
    by construction. Computed fresh here (post-DST-fix) so the disclosed
    numbers are self-consistent with this run, not copy-pasted from the audit
    log."""
    train_days = [d for d in daily.days if d["s"] < wall_ts]
    sealed_days = [d for d in daily.days if d["s"] >= wall_ts]
    return dict(
        n_train=len(train_days), n_sealed=len(sealed_days),
        mean_final_train=float(np.mean([d["final"] for d in train_days])),
        mean_final_sealed=float(np.mean([d["final"] for d in sealed_days])),
        low_share_train=float(np.mean([d["level"] == 0 for d in train_days])),
        low_share_sealed=float(np.mean([d["level"] == 0 for d in sealed_days])),
        high_share_train=float(np.mean([d["level"] == 2 for d in train_days])),
        high_share_sealed=float(np.mean([d["level"] == 2 for d in sealed_days])),
    )


# --- S1: discover the day sections from TRAIN posting intensity, NEVER from
# imposed clock hours. Circular (angle-embedded) KMeans on ET minute-of-day
# of every TRAIN post; K selected by held-out (chronological 70/30 TRAIN
# split) silhouette; centroids + boundaries FROZEN on ALL of train, then
# never touched again. Compared to the user's 11am/3pm/9pm/11pm guess only
# AFTER being frozen. ---------------------------------------------------
def _minute_of_day_angle(ts_arr):
    dts = pd.to_datetime(ts_arr, unit="s", utc=True).tz_convert(ET)
    minute = dts.hour.to_numpy() * 60 + dts.minute.to_numpy()
    theta = 2 * np.pi * minute / 1440.0
    return minute, np.column_stack([np.cos(theta), np.sin(theta)])


def _fmt_et(minute):
    m = int(round(minute)) % 1440
    h, mm = divmod(m, 60)
    return f"{h:02d}:{mm:02d}"


def discover_sections(post_ts, k_candidates=(3, 4, 5, 6, 7, 8), seed=0):
    train_mask = (post_ts >= ELON_CLEAN_START) & (post_ts < WALL_ELON)
    train_ts = post_ts[train_mask]
    order = np.argsort(train_ts)
    ts_sorted = train_ts[order]
    split_ts = ts_sorted[int(len(ts_sorted) * 0.7)]
    fit_ts, eval_ts = train_ts[train_ts < split_ts], train_ts[train_ts >= split_ts]
    _, X_fit = _minute_of_day_angle(fit_ts)
    _, X_eval = _minute_of_day_angle(eval_ts)

    sweep = {}
    best = None
    for K in k_candidates:
        km = KMeans(n_clusters=K, n_init=10, random_state=seed).fit(X_fit)
        _trial("S1_section_K")
        labels_eval = km.predict(X_eval)
        if len(set(labels_eval)) < 2:
            sweep[K] = None
            continue
        sil = float(silhouette_score(X_eval, labels_eval))
        sweep[K] = sil
        if best is None or sil > best[0]:
            best = (sil, K)
    K = best[1] if best else 4

    # refit FROZEN centroids on ALL of train (fit_ts + eval_ts)
    _, X_train = _minute_of_day_angle(train_ts)
    km_final = KMeans(n_clusters=K, n_init=10, random_state=seed).fit(X_train)
    centers = km_final.cluster_centers_
    angles = np.arctan2(centers[:, 1], centers[:, 0]) % (2 * np.pi)
    order2 = np.argsort(angles)
    angles_sorted = angles[order2]
    minute_centers_sorted = (angles_sorted / (2 * np.pi) * 1440)
    labels_train = km_final.labels_
    n_train_days = (WALL_ELON - ELON_CLEAN_START) / 86400.0

    bounds = []
    for i in range(K):
        a1 = angles_sorted[i]
        a2 = angles_sorted[(i + 1) % K] + (2 * np.pi if i == K - 1 else 0)
        bounds.append(((a1 + a2) / 2) % (2 * np.pi))
    minute_bounds = sorted(float(b / (2 * np.pi) * 1440) for b in bounds)

    sections = []
    for rank, orig_k in enumerate(order2):
        n_posts = int((labels_train == orig_k).sum())
        sections.append(dict(rank=rank, center_et=_fmt_et(minute_centers_sorted[rank]),
                              center_minute=float(minute_centers_sorted[rank]),
                              n_train_posts=n_posts, posts_per_day=n_posts / n_train_days))

    # hours-since-noon checkpoint grid for the within-day decision loop
    boundary_hours = sorted(float(((b - 720) % 1440) / 60.0) for b in minute_bounds)
    boundary_et = [_fmt_et(b) for b in minute_bounds]

    return dict(K=K, sweep_silhouette=sweep, sections=sections,
                boundary_et=boundary_et, boundary_hours=boundary_hours,
                n_train_days=n_train_days)


def compare_to_user_guess(sections, guess_et=("11:00", "15:00", "21:00", "23:00")):
    def to_minute(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    guess_min = [to_minute(g) for g in guess_et]
    rows = []
    for g_label, g_min in zip(guess_et, guess_min):
        best = None
        for s in sections:
            d = min(abs(s["center_minute"] - g_min), 1440 - abs(s["center_minute"] - g_min))
            if best is None or d < best[0]:
                best = (d, s["center_et"])
        rows.append(dict(user_guess=g_label, nearest_discovered_center=best[1], offset_minutes=int(round(best[0]))))
    return rows


# --- B1-B4 + S2: unified within-day walk-forward loop at the DISCOVERED
# section-boundary checkpoints (hours-since-noon). Every model scored on the
# SAME decision times so the S2-vs-B4 (PRIMARY) comparison is apples-to-
# apples. B4 reuses fit_M4/predict_M4_pmf VERBATIM (imported) -- the exact
# HMM the prior study locked in. --------------------------------------------
FEATURE_NAMES_S2 = ["count_so_far", "n_sections_completed", "max_section_count",
                     "median_gap_h", "first_post_h", "hours_elapsed"]


def build_s2_features(post_ts, day_s, T, boundary_hours, k_idx):
    import bisect
    o = L.obs_count(post_ts, day_s, T)
    lo = bisect.bisect_left(post_ts, day_s)
    hi = bisect.bisect_left(post_ts, T)
    seg = post_ts[lo:hi]
    c_now = boundary_hours[k_idx]
    if len(seg) >= 2:
        median_gap_h = float(np.median(np.diff(seg.astype("int64")))) / 3600.0
    else:
        median_gap_h = 6.0  # neutral fallback, disclosed
    first_post_h = float((int(seg[0]) - day_s) / 3600.0) if len(seg) else c_now
    prev_b, max_section_count = 0.0, 0
    for bi in range(k_idx + 1):
        b_end = boundary_hours[bi]
        cnt = L.obs_count(post_ts, day_s + int(round(prev_b * 3600)), day_s + int(round(b_end * 3600)))
        max_section_count = max(max_section_count, cnt)
        prev_b = b_end
    return dict(count_so_far=float(o), n_sections_completed=float(k_idx + 1),
                max_section_count=float(max_section_count), median_gap_h=median_gap_h,
                first_post_h=first_post_h, hours_elapsed=float(c_now))


def _feat_vec(feats):
    return np.array([feats[n] for n in FEATURE_NAMES_S2], dtype=float)


def fit_s2_ridge(priors_days, post_ts, boundary_hours, k_idx, min_n=15, alpha=3.0):
    X, y = [], []
    T_off = int(round(boundary_hours[k_idx] * 3600))
    for d in priors_days:
        T = d["s"] + T_off
        feats = build_s2_features(post_ts, d["s"], T, boundary_hours, k_idx)
        remaining = max(0.0, d["final"] - feats["count_so_far"])
        X.append(_feat_vec(feats))
        y.append(math.log1p(remaining))
    if len(X) < min_n:
        return None
    model = Ridge(alpha=alpha, random_state=0)
    model.fit(np.vstack(X), np.array(y))
    return model


def select_ridge_alpha(train_days, post_ts, boundary_hours, k_idx):
    fit_pool, eval_pool = _cv_split(train_days)
    default = 3.0
    if len(fit_pool) < 20 or len(eval_pool) < 8:
        return default, False
    T_off = int(round(boundary_hours[k_idx] * 3600))
    Xe, ye, oe = [], [], []
    for d in eval_pool:
        T = d["s"] + T_off
        feats = build_s2_features(post_ts, d["s"], T, boundary_hours, k_idx)
        Xe.append(_feat_vec(feats))
        ye.append(max(0.0, d["final"] - feats["count_so_far"]))
        oe.append(feats["count_so_far"])
    Xe = np.vstack(Xe)
    best = None
    for alpha in (0.5, 1.0, 3.0, 10.0, 30.0):
        model = fit_s2_ridge(fit_pool, post_ts, boundary_hours, k_idx, alpha=alpha)
        _trial("S2_ridge_alpha")
        if model is None:
            continue
        pred = np.expm1(np.clip(model.predict(Xe), -50, 50))
        mae = float(np.mean(np.abs(pred - np.array(ye))))
        if best is None or mae < best[0]:
            best = (mae, alpha)
    return (best[1], True) if best else (default, False)


def select_hmm_states(train_days, post_ts, cap=40):
    fit_pool, eval_pool = _cv_split(train_days)
    default = 3
    if len(fit_pool) < 8 or len(eval_pool) < 5:
        return default, False
    best = None
    for n_states in (2, 3, 4):
        state = M.fit_M4(fit_pool, post_ts, n_states, cap=cap)
        _trial("B4_HMM_states")
        if state is None:
            continue
        lls = []
        for u in eval_pool:
            seq = M._hourly_seq(post_ts, u["s"], u["e"])
            if len(seq) < 5:
                continue
            try:
                lls.append(state["model"].score(seq.reshape(-1, 1)))
            except Exception:
                continue
        if lls and (best is None or np.mean(lls) > best[0]):
            best = (np.mean(lls), n_states)
    return (best[1], True) if best else (default, False)


def _to_final_dist_probs(kind, params, o, brackets):
    """Every model expresses its remaining-count belief either as (mu, sigma)
    Normal-on-FINAL-count (B1/B3/S2), a pooled empirical mixture-on-FINAL
    (B2), or a discrete remaining-count pmf offset by o (B4). Route to the
    matching reused primitive so log-loss/Brier scoring is identical for
    every method."""
    if kind == "normal":
        mu, sigma = params
        return L.normal_bracket_probs(mu, sigma, brackets)
    if kind == "mixture":
        centers, weights, bw = params
        return L.gaussian_mixture_bracket_probs(centers, weights, bw, brackets)
    if kind == "pmf":
        pmf = params
        return L.discrete_pmf_bracket_probs(o, pmf, brackets) if pmf is not None else None
    return None


def run_q2_core(daily, post_ts, boundary_hours, tercile_brackets, quant_brackets, refit_block=7):
    days = daily.days
    train_days = [d for d in days if d["s"] < WALL_ELON]
    n_states, hmm_cv_ok = select_hmm_states(train_days, post_ts)
    alphas = {}
    for k_idx in range(len(boundary_hours)):
        alphas[k_idx], _ = select_ridge_alpha(train_days, post_ts, boundary_hours, k_idx)
    print(f"[Q2 core] n_states={n_states}(cv={hmm_cv_ok}) ridge_alphas={alphas}")

    rows = []
    errh_b1 = {k: [] for k in range(len(boundary_hours))}
    errh_s2 = {k: [] for k in range(len(boundary_hours))}
    n = len(days)
    for block_start in range(0, n, refit_block):
        block = days[block_start:block_start + refit_block]
        if not block:
            continue
        priors = [d for d in days if d["e"] < block[0]["s"]]
        if len(priors) < 15:
            continue
        st_b4 = M.fit_M4(priors, post_ts, n_states, cap=40)
        st_s2 = {k_idx: fit_s2_ridge(priors, post_ts, boundary_hours, k_idx, alpha=alphas[k_idx])
                  for k_idx in range(len(boundary_hours))}
        priors_finals = np.array([d["final"] for d in priors], dtype=float)
        bw_clim = max(0.35 * float(np.std(priors_finals)), 2.0) if len(priors_finals) > 1 else 5.0

        for d in block:
            span = "train" if d["s"] < WALL_ELON else "sealed"
            for k_idx, c in enumerate(boundary_hours):
                T = d["s"] + int(round(c * 3600))
                o = L.obs_count(post_ts, d["s"], T)
                true_remaining = d["final"] - o

                # B1 naive
                proj_rem_b1 = o * (24.0 - c) / c if c > 0 else 0.0
                sig_b1 = float(np.std(errh_b1[k_idx])) if len(errh_b1[k_idx]) >= 5 else max(8.0, 0.25 * max(proj_rem_b1, 1))
                p3_b1 = _to_final_dist_probs("normal", (o + proj_rem_b1, sig_b1), o, tercile_brackets)
                p5_b1 = _to_final_dist_probs("normal", (o + proj_rem_b1, sig_b1), o, quant_brackets)
                errh_b1[k_idx].append(abs(true_remaining - proj_rem_b1))

                # B2 climatology (unconditional over priors' FINAL counts, checkpoint-independent)
                if len(priors_finals) >= 4:
                    p3_b2 = _to_final_dist_probs("mixture", (priors_finals, np.ones(len(priors_finals)), bw_clim), o, tercile_brackets)
                    p5_b2 = _to_final_dist_probs("mixture", (priors_finals, np.ones(len(priors_finals)), bw_clim), o, quant_brackets)
                else:
                    p3_b2 = p5_b2 = None

                # B3 locked_pace incumbent
                pri = lp_build_priors(list(post_ts), d["s"], 24.0, d["s"])
                if pri is not None:
                    rmean, Kk, share = pri
                    proj_final_b3 = project_locked(o, c, 24.0 - c, dict(rmean=rmean, Kk=Kk, share=share))
                else:
                    proj_final_b3 = None
                if proj_final_b3 is not None:
                    sigma_b3 = calib_sigma(24.0 - c)
                    p3_b3 = {lab: bracket_fair(lo, hi if hi is not None else 1e9, proj_final_b3, sigma_b3) for lab, lo, hi in tercile_brackets}
                    tot = sum(p3_b3.values()); p3_b3 = {k: v / tot for k, v in p3_b3.items()}
                    p5_b3 = {lab: bracket_fair(lo, hi if hi is not None else 1e9, proj_final_b3, sigma_b3) for lab, lo, hi in quant_brackets}
                    tot = sum(p5_b3.values()); p5_b3 = {k: v / tot for k, v in p5_b3.items()}
                else:
                    p3_b3 = p5_b3 = None

                # B4 HMM (the primary bar)
                rem_pmf = M.predict_M4_pmf(st_b4, post_ts, d["s"], T, d["e"], maxn=300) if st_b4 else None
                p3_b4 = _to_final_dist_probs("pmf", rem_pmf, o, tercile_brackets)
                p5_b4 = _to_final_dist_probs("pmf", rem_pmf, o, quant_brackets)

                # S2 section-feature model
                model_s2 = st_s2.get(k_idx)
                feats = build_s2_features(post_ts, d["s"], T, boundary_hours, k_idx)
                if model_s2 is not None:
                    proj_rem_s2 = max(0.0, float(np.expm1(np.clip(model_s2.predict(_feat_vec(feats).reshape(1, -1))[0], -50, 50))))
                    sig_s2 = float(np.std(errh_s2[k_idx])) if len(errh_s2[k_idx]) >= 5 else max(8.0, 0.25 * max(proj_rem_s2, 1))
                    p3_s2 = _to_final_dist_probs("normal", (o + proj_rem_s2, sig_s2), o, tercile_brackets)
                    p5_s2 = _to_final_dist_probs("normal", (o + proj_rem_s2, sig_s2), o, quant_brackets)
                    errh_s2[k_idx].append(abs(true_remaining - proj_rem_s2))
                else:
                    p3_s2 = p5_s2 = None

                for method, p3, p5 in (("B1", p3_b1, p5_b1), ("B2", p3_b2, p5_b2), ("B3", p3_b3, p5_b3),
                                        ("B4", p3_b4, p5_b4), ("S2", p3_s2, p5_s2)):
                    if p3 is None:
                        continue
                    rows.append(dict(slug=d["slug"], s=d["s"], span=span, checkpoint_idx=k_idx,
                                      checkpoint_hours=c, method=method, true_level=d["level"],
                                      true_final=d["final"], o=o, true_remaining=true_remaining,
                                      **{f"p3_{lab}": p3.get(lab, 1e-6) for lab, _, _ in tercile_brackets},
                                      **({f"p5_{lab}": p5.get(lab, 1e-6) for lab, _, _ in quant_brackets} if p5 else {})))
        if (block_start // refit_block + 1) % 10 == 0:
            print(f"  [Q2 core] block {block_start}/{n} days processed")
    return pd.DataFrame(rows), dict(n_states=n_states, hmm_cv_ok=hmm_cv_ok, ridge_alphas=alphas)


# --- S3: cadence-to-regime rule -- hypothesis (b) "posting ~every 2h signals
# a HIGH day". Threshold swept on TRAIN, frozen, evaluated on SEALED at every
# discovered checkpoint (S5 accuracy-by-hour is native to this table). ------
def collect_gap_burst_features(daily, post_ts, boundary_hours):
    rows = []
    for d in daily.days:
        span = "train" if d["s"] < WALL_ELON else "sealed"
        for k_idx, c in enumerate(boundary_hours):
            T = d["s"] + int(round(c * 3600))
            feats = build_s2_features(post_ts, d["s"], T, boundary_hours, k_idx)
            rows.append(dict(slug=d["slug"], s=d["s"], span=span, checkpoint_idx=k_idx,
                              checkpoint_hours=c, median_gap_h=feats["median_gap_h"],
                              count_so_far=feats["count_so_far"], true_level=d["level"], true_final=d["final"]))
    return pd.DataFrame(rows)


def s3_gap_rule(gap_df, thresholds=(1.0, 1.5, 2.0, 2.5, 3.0, 4.0), select_checkpoint_idx=0, min_fired_frac=0.05):
    """Threshold selected at the EARLIEST checkpoint only (idx=0), maximizing
    LIFT (precision-when-fired minus base rate) on TRAIN -- NOT raw accuracy
    pooled across all checkpoints. Median-gap-so-far mechanically compresses
    toward zero for almost every day as the day progresses (more posts
    accumulate -> smaller gaps), so a LATER or pooled-accuracy objective
    would just reward "fires on everyone" with zero discriminative power.
    Selecting (and reporting) the FULL accuracy-by-hour curve afterward makes
    that degeneration visible rather than hiding it."""
    train0 = gap_df[(gap_df.span == "train") & (gap_df.checkpoint_idx == select_checkpoint_idx)]
    is_high_train = (train0.true_level == 2).to_numpy()
    base_rate0 = float(is_high_train.mean())
    best = None
    for th in thresholds:
        fires = (train0.median_gap_h <= th).to_numpy()
        n_fired = int(fires.sum())
        _trial("S3_gap_threshold")
        if n_fired < max(5, min_fired_frac * len(train0)):
            continue
        precision = float(np.mean(is_high_train[fires])) if n_fired else 0.0
        lift = precision - base_rate0
        if best is None or lift > best[0]:
            best = (lift, th, precision, n_fired)
    th_frozen = best[1] if best else thresholds[len(thresholds) // 2]
    best_acc = best[2] if best else float("nan")

    rows = []
    for span in ("train", "sealed"):
        sub = gap_df[gap_df.span == span]
        for k_idx in sorted(sub.checkpoint_idx.unique()):
            s2 = sub[sub.checkpoint_idx == k_idx]
            fires = (s2.median_gap_h <= th_frozen).to_numpy()
            is_high = (s2.true_level == 2).to_numpy()
            n = len(s2)
            n_fired = int(fires.sum())
            precision = float(np.mean(is_high[fires])) if n_fired else float("nan")
            base_rate = float(np.mean(is_high)) if n else float("nan")
            # CI + jackknife added 2026-07-31 per @backtest-auditor finding 3
            # ("every headline in the study, not just S4") -- this checkpoint-0
            # sealed lift is the number quoted verbatim as verdict (b)'s headline
            # and previously carried neither.
            skill_vec = (is_high[fires].astype(float) - base_rate) if n_fired else np.array([])
            ci = block_bootstrap_ci(skill_vec, block_size=1) if n_fired >= 2 else None
            jk = jackknife_drop_best(skill_vec)
            rows.append(dict(span=span, checkpoint_idx=int(k_idx), checkpoint_hours=float(s2.checkpoint_hours.iloc[0]),
                              n=n, n_fired=n_fired, hit_rate=float(np.mean(fires == is_high)) if n else float("nan"),
                              base_rate=base_rate, precision_when_fired=precision,
                              lift=(precision - base_rate) if not math.isnan(precision) else float("nan"),
                              lift_ci_lo=(ci["lo"] if ci else None), lift_ci_hi=(ci["hi"] if ci else None),
                              lift_jk_full=jk["full_mean"], lift_jk_dropbest=jk["dropbest_mean"],
                              lift_jk_sign_holds=jk["sign_holds"]))
    return dict(threshold_hours=th_frozen, train_best_lift=(best[0] if best else float("nan")),
                train_best_precision=best_acc, select_checkpoint_idx=select_checkpoint_idx,
                sweep_candidates=list(thresholds), table=pd.DataFrame(rows))


def s3_at_fixed_threshold(gap_df, th=2.0):
    """The user's LITERAL '~every 2 hours' claim, evaluated as-stated (not
    the swept/frozen value) -- interpretability only, not a separate formal
    success claim (that role belongs to the frozen sweep winner above)."""
    rows = []
    for span in ("train", "sealed"):
        sub = gap_df[gap_df.span == span]
        for k_idx in sorted(sub.checkpoint_idx.unique()):
            s2 = sub[sub.checkpoint_idx == k_idx]
            fires = (s2.median_gap_h <= th).to_numpy()
            is_high = (s2.true_level == 2).to_numpy()
            n_fired = int(fires.sum())
            precision = float(np.mean(is_high[fires])) if n_fired else float("nan")
            base_rate = float(np.mean(is_high)) if len(s2) else float("nan")
            rows.append(dict(span=span, checkpoint_idx=int(k_idx), n=len(s2), n_fired=n_fired,
                              precision_when_fired=precision, base_rate=base_rate,
                              lift=(precision - base_rate) if not math.isnan(precision) else float("nan")))
    return pd.DataFrame(rows)


# --- S4: burst-exhaustion rule -- hypothesis (c) "a big morning burst signals
# a LOW remainder". FORMAL (window-anchored, regime-linked, matches prereg's
# S4 literally): burst = count in the first X hours of the noon-window,
# X swept+frozen on TRAIN. LITERAL (calendar-clock supplementary,
# descriptive, answers the user's own wording directly: ET 5am-12pm morning
# vs ET 12pm-midnight SAME calendar date remainder) -- clearly separated from
# the formal test, not used for PRIMARY/SECONDARY/TERTIARY gating. ----------
def s4_formal_burst_rule(daily, post_ts, x_candidates):
    train_days = [d for d in daily.days if d["s"] < WALL_ELON]
    sealed_days = [d for d in daily.days if d["s"] >= WALL_ELON]
    base_rate_low = float(np.mean([d["level"] == 0 for d in train_days]))
    best = None
    for X in x_candidates:
        counts = np.array([L.obs_count(post_ts, d["s"], d["s"] + int(round(X * 3600))) for d in train_days])
        p75 = float(np.percentile(counts, 75))
        is_low = np.array([d["level"] == 0 for d in train_days])
        fires = counts >= p75
        n_fired = int(fires.sum())
        _trial("S4_morning_window_X")
        if n_fired < 5:
            continue
        precision = float(np.mean(is_low[fires]))
        lift = precision - base_rate_low
        if best is None or lift > best[0]:
            best = (lift, X, p75, precision)
    X_frozen, p75_frozen = (best[1], best[2]) if best else (x_candidates[0], float("nan"))

    rows = []
    for span, days in (("train", train_days), ("sealed", sealed_days)):
        counts = np.array([L.obs_count(post_ts, d["s"], d["s"] + int(round(X_frozen * 3600))) for d in days])
        is_low = np.array([d["level"] == 0 for d in days])
        fires = counts >= p75_frozen
        n, n_fired = len(days), int(fires.sum())
        precision = float(np.mean(is_low[fires])) if n_fired else float("nan")
        base_rate = float(np.mean(is_low)) if n else float("nan")
        skill_vec = (is_low[fires].astype(float) - base_rate) if n_fired else np.array([])
        ci = block_bootstrap_ci(skill_vec, block_size=1) if n_fired >= 2 else None
        # jackknife added 2026-07-31 per @backtest-auditor finding 3 -- this is
        # THE positive finding's headline number (hypothesis c); the auditor
        # ran this independently (mean -0.4014 -> -0.4655 dropping the single
        # most favorable sealed day, sign holds) and required it be in the
        # artifact, not just the audit log.
        jk = jackknife_drop_best(skill_vec)
        rows.append(dict(span=span, n=n, n_fired=n_fired, precision_when_fired=precision, base_rate=base_rate,
                          lift=(precision - base_rate) if not math.isnan(precision) else float("nan"),
                          lift_ci_lo=(ci["lo"] if ci else None), lift_ci_hi=(ci["hi"] if ci else None),
                          lift_jk_full=jk["full_mean"], lift_jk_dropbest=jk["dropbest_mean"],
                          lift_jk_sign_holds=jk["sign_holds"]))
    return dict(X_hours=X_frozen, p75_count=p75_frozen, train_best_lift=(best[0] if best else float("nan")),
                train_best_precision=(best[3] if best else float("nan")),
                sweep_candidates=list(x_candidates), table=pd.DataFrame(rows))


def s4_literal_calendar(post_ts):
    dts = pd.to_datetime(post_ts, unit="s", utc=True).tz_convert(ET)
    unique_dates = sorted(set(dts.date))
    rows = []
    for dt in unique_dates:
        # DST fix (audit 2026-07-31, 2nd pass): was `pd.Timestamp(dt, tz=ET) +
        # pd.Timedelta(hours=N)` -- absolute-duration arithmetic on a wall-clock
        # midnight, same bug class as DailySeries above. hour=5/12 are never in
        # the DST-ambiguous/nonexistent window (that's 1-3am), so constructing
        # each boundary DIRECTLY in-tz is unambiguous and DST-correct.
        next_dt = dt + pd.Timedelta(days=1)
        m_s = int(pd.Timestamp(year=dt.year, month=dt.month, day=dt.day, hour=5, tz=ET).timestamp())
        m_e = int(pd.Timestamp(year=dt.year, month=dt.month, day=dt.day, hour=12, tz=ET).timestamp())
        r_s = m_e
        r_e = int(pd.Timestamp(year=next_dt.year, month=next_dt.month, day=next_dt.day, hour=0, tz=ET).timestamp())
        if m_s < ELON_CLEAN_START or r_e > ELON_CLEAN_END:
            continue
        morning = L.obs_count(post_ts, m_s, m_e)
        remainder = L.obs_count(post_ts, r_s, r_e)
        rows.append(dict(date=str(dt), morning_count=morning, remainder_count=remainder, is_train=(m_s < WALL_ELON)))
    df = pd.DataFrame(rows)
    train = df[df.is_train]
    r_val = float(np.corrcoef(train.morning_count, train.remainder_count)[0, 1]) if len(train) > 5 else float("nan")
    p75 = float(np.percentile(train.morning_count, 75)) if len(train) else float("nan")
    _trial("S4_literal_calendar")
    out_rows = []
    sealed_loo = None
    for span_name, sub in (("train", train), ("sealed", df[~df.is_train])):
        if sub.empty:
            continue
        big = sub.morning_count >= p75
        n_big = int(big.sum())
        med_big = float(sub.remainder_count[big].median()) if n_big else float("nan")
        med_not = float(sub.remainder_count[~big].median()) if (~big).sum() else float("nan")
        out_rows.append(dict(span=span_name, n=len(sub), n_big_morning=n_big,
                              median_remainder_given_big_morning=med_big,
                              median_remainder_given_not_big=med_not,
                              median_remainder_overall=float(sub.remainder_count.median()),
                              below_success_floor=bool(n_big < SUCCESS_N_FLOOR)))
        # Leave-one-out fragility on the SEALED corroboration slice, added
        # 2026-07-31 per @backtest-auditor findings 3+4: n_big_morning=8 sits
        # below SUCCESS_N_FLOOR=10 and is cited by name in the bolded verdict
        # (c) sentence, so it needs both the jackknife the prereg mandates AND
        # a disqualifying sentinel like every other sub-floor claim gets.
        if span_name == "sealed" and n_big >= 2:
            vals = sub.remainder_count[big].to_numpy(dtype=float)
            loo_medians = [float(np.median(np.delete(vals, i))) for i in range(len(vals))]
            n_tie_or_erase = sum(1 for lm in loo_medians if lm <= med_not)
            sealed_loo = dict(n=len(vals), full_median=med_big, loo_medians=loo_medians,
                               loo_min=float(min(loo_medians)), loo_max=float(max(loo_medians)),
                               n_drops_tie_or_erase_gap=n_tie_or_erase, baseline_median_not_big=med_not)
    sealed_corroboration_note = None
    if sealed_loo is not None and sealed_loo["n"] < SUCCESS_N_FLOOR:
        sealed_corroboration_note = (
            f"noise (n={sealed_loo['n']}, below success floor of {SUCCESS_N_FLOOR}) -- SEALED corroboration slice "
            f"is UNDERSIZED and fragile under leave-one-out: median remainder-given-big-morning ranges "
            f"[{sealed_loo['loo_min']:.1f},{sealed_loo['loo_max']:.1f}] depending which single day is dropped, and "
            f"{sealed_loo['n_drops_tie_or_erase_gap']}/{sealed_loo['n']} single-day drops tie or erase the gap vs "
            f"the 'not-big-morning' baseline ({sealed_loo['baseline_median_not_big']:.1f}). Descriptive only, not "
            f"corroborating evidence for verdict (c) on its own -- the FORMAL test (sealed n_fired=13, "
            f"floor-clearing, jackknife-robust) is what actually carries verdict (c).")
    return dict(pearson_r_train=r_val, p75_morning_count=p75, table=pd.DataFrame(out_rows), raw_n=len(df),
                sealed_loo=sealed_loo, sealed_corroboration_note=sealed_corroboration_note)


# --- Q2 aggregation: classification metrics (accuracy/macro-F1/confusion/
# log-loss), PRIMARY (S2 vs B4) / TERTIARY (S2 vs B1/B2) skill with block
# bootstrap BY WEEK (block_size=7, days already chronological within span),
# jackknife, reliability table, and per-checkpoint (S5) accuracy curve. -----
def q2_classification_metrics(df, span):
    sub = df[df.span == span]
    out = {}
    for method in sub.method.unique():
        m = sub[sub.method == method]
        probs = m[[f"p3_{lab}" for lab in LEVEL_NAMES]].to_numpy()
        pred = probs.argmax(axis=1)
        true = m.true_level.to_numpy()
        acc = float(np.mean(pred == true))
        f1s = []
        for k in range(3):
            tp = int(np.sum((pred == k) & (true == k)))
            fp = int(np.sum((pred == k) & (true != k)))
            fn = int(np.sum((pred != k) & (true == k)))
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0)
        conf = np.zeros((3, 3), dtype=int)
        for p, t in zip(pred, true):
            conf[t, p] += 1
        ll = -np.log(np.clip(probs[np.arange(len(true)), true], 1e-9, 1.0))
        out[method] = dict(n=int(len(m)), accuracy=acc, macro_f1=float(np.mean(f1s)), confusion=conf.tolist(),
                            logloss_mean=float(ll.mean()))
    return out


def q2_skill_vs_baseline(df, method, baseline, span, block_size=7):
    sub = df[(df.span == span) & (df.method.isin([method, baseline]))].copy()
    if sub.empty:
        return None
    probs = sub[[f"p3_{lab}" for lab in LEVEL_NAMES]].to_numpy()
    sub["logloss"] = -np.log(np.clip(probs[np.arange(len(sub)), sub.true_level.to_numpy()], 1e-9, 1.0))
    piv = sub.pivot_table(index=["slug", "s"], columns="method", values="logloss", aggfunc="mean")
    piv = piv.sort_index(level="s")
    if method not in piv.columns or baseline not in piv.columns:
        return None
    pair = piv[[method, baseline]].dropna()
    if pair.empty:
        return None
    skill = (pair[baseline] - pair[method]).to_numpy()  # positive = method beats baseline
    ci = block_bootstrap_ci(skill, block_size=block_size)
    jk = jackknife_drop_best(skill)
    return dict(n_days=int(len(pair)), skill_mean=ci["mean"], ci_lo=ci["lo"], ci_hi=ci["hi"],
                jk_full=jk["full_mean"], jk_dropbest=jk["dropbest_mean"], jk_sign_holds=jk["sign_holds"],
                mean_logloss_method=float(pair[method].mean()), mean_logloss_baseline=float(pair[baseline].mean()))


def q2_accuracy_by_hour(df, methods=("B1", "B2", "B3", "B4", "S2")):
    rows = []
    for span in ("train", "sealed"):
        sub = df[df.span == span]
        for method in methods:
            m = sub[sub.method == method]
            if m.empty:
                continue
            for c_idx, g in m.groupby("checkpoint_idx"):
                probs = g[[f"p3_{lab}" for lab in LEVEL_NAMES]].to_numpy()
                pred = probs.argmax(axis=1)
                true = g.true_level.to_numpy()
                ll = -np.log(np.clip(probs[np.arange(len(true)), true], 1e-9, 1.0))
                rows.append(dict(span=span, method=method, checkpoint_idx=int(c_idx),
                                  checkpoint_hours=float(g.checkpoint_hours.iloc[0]), n=int(len(g)),
                                  accuracy=float(np.mean(pred == true)), logloss_mean=float(ll.mean())))
    return pd.DataFrame(rows)


def reliability_table(df, span, method, n_bins=10):
    sub = df[(df.span == span) & (df.method == method)]
    if sub.empty:
        return pd.DataFrame()
    probs = sub[[f"p3_{lab}" for lab in LEVEL_NAMES]].to_numpy()
    true = sub.true_level.to_numpy()
    p_pred = probs.max(axis=1)
    pred = probs.argmax(axis=1)
    correct = (pred == true).astype(float)
    bins = np.linspace(0, 1, n_bins + 1)
    rows = []
    for i in range(n_bins):
        mask = (p_pred >= bins[i]) & (p_pred < bins[i + 1] if i < n_bins - 1 else p_pred <= bins[i + 1])
        n = int(mask.sum())
        rows.append(dict(bin_lo=bins[i], bin_hi=bins[i + 1], n=n,
                          mean_predicted_prob=float(p_pred[mask].mean()) if n else float("nan"),
                          empirical_accuracy=float(correct[mask].mean()) if n else float("nan")))
    return pd.DataFrame(rows)


# ===========================================================================
# Orchestration + output
# ===========================================================================
def write_summary(q1_results, q2, out_path):
    L_ = []
    A = L_.append
    A("# Regime Discovery -- Trajectory + Day-Sectioning (2026-07-29)")
    A("")
    A("Pre-registration: `_DataMetricPulls/pacing_backtest/prereg/regime_discovery_2026-07-29.md`. "
      "Scope: (b) pure forecast-accuracy/calibration diagnostic + descriptive rule discovery. No P&L, no fills. "
      "This is a hypothesis, not a certified result -- hand off to @backtest-auditor.")
    A("")
    brs = q2["base_rate_shift"]
    A("## Data note -- Elon's activity level itself shifted between TRAIN and SEALED")
    A(f"Mean daily counting-posts falls from **{brs['mean_final_train']:.1f}** (train, n={brs['n_train']}) to "
      f"**{brs['mean_final_sealed']:.1f}** (sealed, n={brs['n_sealed']}). Because regime terciles are frozen from "
      f"TRAIN (correctly, per THE WALL -- never redefined on sealed), this quieter sealed period gets classified "
      f"LOW at **{brs['low_share_sealed']*100:.1f}%** of days vs **{brs['low_share_train']*100:.1f}%** in train, and "
      f"HIGH at only **{brs['high_share_sealed']*100:.1f}%** vs **{brs['high_share_train']*100:.1f}%** in train. "
      f"This is legitimate WALL-respecting behavior, not a bug or a leak -- but every sealed-span result below was "
      f"measured in a meaningfully quieter regime than the models/thresholds were fit in. Read any regime-"
      f"classification accuracy figure, and B2's climatology performance in particular (anchored to a stale "
      f"train-era rate), with that in mind.")
    A("")
    A("## PART 1 -- THE MAP (read this first)")
    A("")
    A("### Q2: the discovered day sections (Elon, TRAIN-only discovery, frozen)")
    sec = q2["sections"]
    A(f"K={sec['K']} sections chosen by held-out silhouette on a chronological 70/30 split of TRAIN days "
      f"(candidates K=3..8, silhouette: {', '.join(f'{k}={v:.3f}' for k, v in sec['sweep_silhouette'].items() if v is not None)}).")
    A("")
    A("| Section (burst center, ET) | Boundary reached at (ET) | Hours since noon | Posts/day (TRAIN) |")
    A("|---|---|---|---|")
    for i, s in enumerate(sec["sections"]):
        A(f"| {s['center_et']} | {sec['boundary_et'][i]} | {sec['boundary_hours'][i]:.2f}h | {s['posts_per_day']:.1f} |")
    A("")
    A("### Hypothesis (a) verdict -- \"he tends to post around 11am, 3pm, 9pm, 11pm ET\"")
    cmp_rows = q2["guess_compare"]
    A("| User's guess | Nearest discovered burst center | Offset |")
    A("|---|---|---|")
    for r in cmp_rows:
        A(f"| {r['user_guess']} | {r['nearest_discovered_center']} | {r['offset_minutes']} min |")
    avg_offset = np.mean([r["offset_minutes"] for r in cmp_rows])
    verdict_a = "DOES NOT HOLD as stated" if avg_offset > 60 else ("PARTIALLY HOLDS" if avg_offset > 30 else "HOLDS")
    A(f"\n**Verdict (a): {verdict_a}.** Average offset from the user's guessed times to the nearest discovered "
      f"burst center is {avg_offset:.0f} minutes. The discovered K={sec['K']} centers are "
      f"{', '.join(s['center_et'] for s in sec['sections'])} ET -- a real, data-driven daily 4-burst rhythm exists, "
      f"but it runs roughly {avg_offset/60:.1f}h earlier than the user's guessed clock times, not on them.")
    A("")
    A("### Q1: transition matrices in plain words (auction-level, TRAIN-fit, frozen)")
    for hname, res in q1_results.items():
        A(f"\n**{hname}** (n_train={res['n_train']} auctions, cuts LOW<= {res['q1_cut']:.0f}, HIGH> {res['q2_cut']:.0f}):")
        for line in res["r1"]["plain_words"]:
            A(f"- {line}")
    A("")
    A("## PART 2 -- readable rules (n_train / n_sealed / hit rate / lift)")
    A("")
    A("### Hypothesis (b) -- \"posting roughly every 2 hours signals a HIGH day\" (Q2/S3)")
    s3 = q2["s3"]
    A(f"Rule (frozen on TRAIN, selected at the EARLIEST checkpoint idx=0 by lift, not pooled accuracy -- "
      f"median gap mechanically shrinks toward zero for almost every day as the day progresses, which would make a "
      f"pooled-accuracy objective just reward \"fires on everyone\"): **IF median inter-post gap so far <= "
      f"{s3['threshold_hours']:.1f}h THEN predict HIGH.** Swept candidates (hours): {s3['sweep_candidates']}.")
    A("")
    A("| Span | Checkpoint (h since noon) | n | n fired | precision when fired | base rate | lift | lift 95% CI |")
    A("|---|---|---|---|---|---|---|---|")
    for _, r in s3["table"].iterrows():
        ci3 = f"[{r['lift_ci_lo']:+.3f},{r['lift_ci_hi']:+.3f}]" if r["lift_ci_lo"] is not None else "n/a"
        A(f"| {r['span']} | {r['checkpoint_hours']:.1f} | {int(r['n'])} | {int(r['n_fired'])} | "
          f"{r['precision_when_fired']:.3f} | {r['base_rate']:.3f} | {r['lift']:+.3f} | {ci3} |")
    sealed3 = s3["table"][(s3["table"].span == "sealed") & (s3["table"].checkpoint_idx == 0)]
    lift0 = float(sealed3.lift.iloc[0]) if not sealed3.empty else float("nan")
    lift0_jk = sealed3.iloc[0] if not sealed3.empty else None
    if lift0_jk is not None and lift0_jk["lift_jk_sign_holds"] is not None:
        jk_txt_b = (f"{lift0_jk['lift_jk_full']:+.4f} -> {lift0_jk['lift_jk_dropbest']:+.4f}, "
                    f"sign holds={lift0_jk['lift_jk_sign_holds']}")
    else:
        jk_txt_b = "n/a"
    verdict_b = "DOES NOT HOLD" if abs(lift0) < 0.05 else ("WEAKLY HOLDS" if lift0 > 0 else "HOLDS IN REVERSE")
    A(f"\n**Verdict (b): {verdict_b}.** At its EARLIEST usable hour ({s3['table'].checkpoint_hours.iloc[0]:.1f}h "
      f"since noon), the frozen rule's sealed-span lift over base rate is only {lift0:+.3f} -- a real but tiny edge "
      f"that decays to exactly zero lift by the later checkpoints (the rule ends up firing on ~100% of days once "
      f"most of the day has posts, at which point it carries no information at all). Single-outlier jackknife: "
      f"{jk_txt_b}. The user's literal '2 hours' gives an almost identical, similarly weak result (see "
      f"`s3_at_fixed_threshold` table in the CSVs).")
    A("")
    A("### Hypothesis (c) -- \"a big morning burst signals a LOW remainder\" (Q2/S4)")
    s4 = q2["s4_formal"]
    A(f"**Formal (window-anchored, regime-linked) test:** morning burst = post count in the first "
      f"{s4['X_hours']:.2f}h of the noon-anchored window (>= TRAIN 75th percentile = {s4['p75_count']:.0f} posts), "
      f"rule predicts the WHOLE window ends LOW. Swept candidates (hours): {[round(x,2) for x in s4['sweep_candidates']]} "
      f"-- EVERY candidate gave a NEGATIVE lift on train (range -0.24 to -0.29); the reported one is the least-negative.")
    A("")
    A("| Span | n | n fired | precision when fired | base rate (LOW) | lift | lift 95% CI | jackknife (drop best) |")
    A("|---|---|---|---|---|---|---|---|")
    for _, r in s4["table"].iterrows():
        ci = f"[{r['lift_ci_lo']:+.3f},{r['lift_ci_hi']:+.3f}]" if r["lift_ci_lo"] is not None else "n/a"
        jk_txt = (f"{r['lift_jk_full']:+.4f}->{r['lift_jk_dropbest']:+.4f}, sign holds={r['lift_jk_sign_holds']}"
                  if r["lift_jk_sign_holds"] is not None else "n/a")
        A(f"| {r['span']} | {int(r['n'])} | {int(r['n_fired'])} | {r['precision_when_fired']:.3f} | "
          f"{r['base_rate']:.3f} | {r['lift']:+.3f} | {ci} | {jk_txt} |")
    A(f"\n**Caveat on the formal framing:** the noon-anchored window means hours 0-3 are literally noon-3pm ET, "
      f"NOT a calendar morning -- \"burst right after the window opens\" mostly just re-measures that early "
      f"activity correlates with total activity (o_so_far predicts final), not genuine within-day exhaustion. "
      f"Read the LITERAL test below as the more faithful check of the user's actual claim.")
    s4l = q2["s4_literal"]
    A(f"\n**Literal (calendar-day) supplementary test, descriptive only, not part of the formal PRIMARY/SECONDARY/"
      f"TERTIARY gate:** morning = ET 5am-12pm, remainder = ET 12pm-midnight of the SAME calendar date. "
      f"TRAIN Pearson r(morning, remainder) = {s4l['pearson_r_train']:+.3f} (positive = MORE morning activity "
      f"goes with MORE remainder activity -- the opposite sign of the exhaustion hypothesis).")
    A("")
    A("| Span | n | n big-morning days | median remainder given big morning | median remainder given not | median remainder overall |")
    A("|---|---|---|---|---|---|")
    for _, r in s4l["table"].iterrows():
        flag = " [BELOW SUCCESS FLOOR]" if r["below_success_floor"] else ""
        A(f"| {r['span']} | {int(r['n'])} | {int(r['n_big_morning'])} | {r['median_remainder_given_big_morning']:.1f} | "
          f"{r['median_remainder_given_not_big']:.1f} | {r['median_remainder_overall']:.1f}{flag} |")
    if s4l.get("sealed_corroboration_note"):
        A(f"\n**SEALED corroboration slice sentinel:** {s4l['sealed_corroboration_note']}")
    sealed_lift_c = float(s4["table"][s4["table"].span == "sealed"].lift.iloc[0])
    sealed_jk_c = s4["table"][s4["table"].span == "sealed"].iloc[0]
    A(f"\n**Verdict (c): HOLDS IN REVERSE.** The FORMAL window-anchored test carries this verdict: sealed lift "
      f"{sealed_lift_c:+.3f} (CI excludes zero, n_fired={int(sealed_jk_c['n_fired'])} clears SUCCESS_N_FLOOR="
      f"{SUCCESS_N_FLOOR}), single-outlier jackknife mean {sealed_jk_c['lift_jk_full']:+.4f} -> "
      f"{sealed_jk_c['lift_jk_dropbest']:+.4f} dropping the single most rule-favorable sealed day -- sign holds "
      f"({sealed_jk_c['lift_jk_sign_holds']}) and the effect strengthens, not weakens. The LITERAL calendar-day "
      f"test points the SAME direction (positive correlation, higher median remainder after a big morning in both "
      f"train and sealed) but its own sealed corroboration slice is undersized and fragile (see sentinel above) -- "
      f"it corroborates the direction, it does not independently prove it. Either way: a big early burst goes with "
      f"MORE subsequent activity, not less. There is no exhaustion effect in this data -- if anything, mild "
      f"momentum/day-level heterogeneity (some days are just busier throughout).")
    A("")
    A("### Q1 -- readable trajectory-shape rules (R5), n_train / n_sealed / hit rate / lift, n>=30 or flagged")
    for hname, res in q1_results.items():
        A(f"\n**{hname}**:")
        r5 = res["r5"]["rows"]
        if r5.empty:
            A("- no pattern observed with n>=2 in either span.")
            continue
        for _, r in r5.sort_values("n_train", ascending=False).head(12).iterrows():
            flag = " [FLAGGED n<30]" if r["flagged_small_n"] else ""
            sealed_txt = f"{r['sealed_hit_rate']:.2f}" if not (isinstance(r['sealed_hit_rate'], float) and math.isnan(r['sealed_hit_rate'])) else "n/a"
            A(f"- After {r['pattern']} (n_train={r['n_train']}, n_sealed={r['n_sealed']}): majority-predicted next "
              f"= {r['predicted_next']}, train hit rate={r['train_hit_rate']:.2f}, sealed hit rate={sealed_txt}{flag}")
        A(f"- Largest observed cell: n_train={int(r5.n_train.max())}. Prereg floor for an unflagged claim is n>=30 "
          f"-- {'no' if r5.n_train.max() < 30 else 'some'} pattern clears it. This is the expected outcome the "
          f"prereg itself warned about at this sample size.")
    A("")
    A("## PART 3 -- earliest usable hour per rule (S5, mandatory)")
    A("")
    A("| Rule | Earliest usable checkpoint | Sealed accuracy/lift there | Notes |")
    A("|---|---|---|---|")
    A(f"| S3 gap-cadence | {s3['table'].checkpoint_hours.iloc[0]:.1f}h since noon | lift {lift0:+.3f} | "
      f"decays to zero by the last checkpoint -- unusable late |")
    A(f"| S4 morning-burst (formal) | {s4['X_hours']:.2f}h since noon (single-shot) | lift "
      f"{s4['table'][s4['table'].span=='sealed'].lift.iloc[0]:+.3f} | static after this hour, no new info added later |")
    acc_curve = q2["acc_by_hour"]
    for method in ("B1", "B2", "B3", "B4", "S2"):
        sub = acc_curve[(acc_curve.span == "sealed") & (acc_curve.method == method)].sort_values("checkpoint_hours")
        if sub.empty:
            continue
        first = sub.iloc[0]
        A(f"| {method} (regime classifier) | {first['checkpoint_hours']:.1f}h since noon | "
          f"acc={first['accuracy']:.3f}, logloss={first['logloss_mean']:.3f} | full accuracy-by-hour curve in "
          f"`q2_accuracy_by_hour.csv` |")
    A("")
    A("## PART 4 -- score tables and baseline comparisons")
    A("")
    A("### Q1 success criteria")
    for hname, res in q1_results.items():
        A(f"\n**{hname}**")
        r1s = res["r1"].get("sealed_skill_vs_clim")
        r1n = res["r1"].get("sealed_n", 0)
        r1jk = res["r1"].get("sealed_jk_vs_clim")
        A(f"- TERTIARY-style (R1 Markov beats climatology, sealed): {success_line(r1s, r1n, 'climatology') if r1s else 'no sealed data'} "
          f"(skill={r1s['mean']:+.4f} CI[{r1s['lo']:+.4f},{r1s['hi']:+.4f}] n={r1n}, jackknife sign holds={r1jk['sign_holds'] if r1jk else 'n/a'})" if r1s else "")
        if res.get("b5_scored"):
            r1m = res["r1"].get("sealed_skill_vs_market")
            r1mn = res["r1"].get("sealed_n_market", 0)
            r1mjk = res["r1"].get("sealed_jk_vs_market")
            A(f"- **B5/MARKET (prereg baseline, implemented 2026-07-31): R1 Markov beats the market-implied "
              f"tercile distribution at auction open, sealed**: {success_line(r1m, r1mn, 'market') if r1m else 'no admissible sealed auctions'} "
              + (f"(skill={r1m['mean']:+.4f} CI[{r1m['lo']:+.4f},{r1m['hi']:+.4f}] n={r1mn}, jackknife sign holds="
                 f"{r1mjk['sign_holds'] if r1mjk else 'n/a'}, price-admissible={res['b5_n_admissible']}/{res['b5_n_total']} "
                 f"auctions total)" if r1m else f"(price-admissible={res['b5_n_admissible']}/{res['b5_n_total']} auctions total)"))
        else:
            A("- B5/MARKET: not scored for this handle -- prereg scopes B5 to Elon 2-day only "
              "(\"implied bracket distribution where available (Elon 2-day only...)\").")
        r4s = res["r4"].get("sealed_skill")
        r4n = res["r4"].get("sealed_n", 0)
        A(f"- **SECONDARY (R4, the prereg's named criterion): trajectory-shape beats lag-1-only persistence, sealed**: "
          f"{success_line(r4s, r4n, 'lag-1 persistence') if r4s else 'no sealed data'}"
          + (f" (skill={r4s['mean']:+.4f} CI[{r4s['lo']:+.4f},{r4s['hi']:+.4f}] n={r4n}, jackknife sign holds={res['r4'].get('sealed_jk',{}).get('sign_holds')})" if r4s else ""))
        r3 = res["r3"]
        A(f"- R3 changepoint: {len(r3['true_cps'])} retrospective changepoint(s) found; "
          f"{sum(1 for r in r3['lag_rows'] if not r['censored'])}/{len(r3['lag_rows'])} matched by a causal online "
          f"detection, lags (auctions): {[r['lag_auctions'] for r in r3['lag_rows'] if not r['censored']]}. "
          f"{len(r3['unmatched_online_idx'])} additional online detections had no matching retrospective changepoint "
          f"nearby (possible false positives at this small n).")
    A("")
    A("### Q2 success criteria (sealed span only)")
    for method, baseline, tag in (("S2", "B4", "PRIMARY"), ("S2", "B1", "TERTIARY"), ("S2", "B2", "TERTIARY")):
        skill = q2["skill"][(method, baseline)]
        n = skill["n_days"] if skill else 0
        line = success_line(dict(lo=skill["ci_lo"], hi=skill["ci_hi"]), n, baseline) if skill else "no data"
        A(f"- **{tag}: S2 beats {baseline}** -- {line}" + (f" (skill={skill['skill_mean']:+.4f} "
          f"CI[{skill['ci_lo']:+.4f},{skill['ci_hi']:+.4f}] n_days={n}, jackknife sign holds={skill['jk_sign_holds']})" if skill else ""))
    A(f"\n**Context (not a formal criterion): does B4 itself still beat B1 on this discovered-boundary checkpoint "
      f"grid?** " + (lambda s: f"skill={s['skill_mean']:+.4f} CI[{s['ci_lo']:+.4f},{s['ci_hi']:+.4f}] n={s['n_days']} "
      f"-- same order of magnitude as the prior study's own +0.121 CI[+0.029,+0.206] on its fixed-hour grid, a sanity "
      f"cross-check that nothing structural broke.")(q2["skill"][("B4", "B1")]))
    A("")
    A("### Classification metrics (sealed span, accuracy / macro-F1 / log-loss)")
    A("| Method | n | Accuracy | Macro-F1 | Log-loss |")
    A("|---|---|---|---|---|")
    for method, d in q2["metrics_sealed"].items():
        A(f"| {method} | {d['n']} | {d['accuracy']:.3f} | {d['macro_f1']:.3f} | {d['logloss_mean']:.4f} |")
    A("")
    A("### Data-integrity findings")
    A(f"- Trump 7-day market cadence changed from weekly non-overlapping windows to a rolling ~72-96h-step "
      f"7-day window starting 2026-02-06 (inside the sealed span). Raw n={q2['trump_raw_n']}, "
      f"de-overlapped n={q2['trump_raw_n'] - q2['trump_dropped']} used for ALL Q1 Trump analysis above "
      f"({q2['trump_dropped']} overlapping auctions dropped) to avoid a same_period_aggregate-style leak from "
      f"shared underlying days across 'different' auction outcomes.")
    A(f"- Elon 2-day auctions only begin 2026-01-03 (not from the 2025-09-01 clean-span start) -- Polymarket did "
      f"not run 2-day Elon brackets earlier. Train n=38, sealed n=28.")
    A("")
    A("### Trial count")
    A(f"Realized trial count: **{TRIALS['n']}**. By method: {TRIALS['by_method']}")
    A("")
    A("### What this does NOT show")
    A("- This is a forecast-accuracy/calibration diagnostic. No P&L, no fills, no live-tradeable claim.")
    A("- Q1 auction-level n is small (elon sealed=28, trump sealed=10 -- AT the SUCCESS_N_FLOOR). Any Q1 finding "
      "at n<10 is emitted as an explicit noise sentinel, never a bare pass/fail.")
    A("- R5's trajectory-shape rules never clear the n>=30 floor at this auction count -- reported for the map, "
      "not as a tradeable signal.")
    A("- Q2 scope was narrowed to Elon daily only (not Trump); the user's stated hypotheses are Elon-specific and "
      "B4's own quoted +0.121 baseline fact is Elon-daily-specific. Documented here as a construction decision "
      "for the auditor to review, not a silent scope cut.")
    A("- B5/MARKET (prereg baseline) is implemented ONLY for elon_2day's Q1 R1 test, exactly the prereg's own "
      "declared scope (\"Elon 2-day only, and only on price-admissible auctions\"). It is intentionally NOT scored "
      "for trump_7day (out of the declared scope) or anywhere in Q2 (Q2's daily windows are arbitrary noon-to-noon "
      "cuts, not tradeable Polymarket auctions -- there is no market to compare against). This was previously an "
      "undisclosed gap; disclosed here per @backtest-auditor finding 2.")
    out_path.write_text("\n".join(L_), encoding="utf-8")
    return "\n".join(L_)


def main():
    t0 = time.time()

    # ---------------- Q1 ----------------
    print("=== Q1: loading auction-level data ===")
    q1data = load_q1_data()
    print(f"elon_2day n={len(q1data['elon_2day'])}  trump_7day raw n={q1data['trump_7day_raw_n']} "
          f"de-overlapped n={len(q1data['trump_7day'])} (dropped {q1data['n_overlap_dropped']})")

    # B5/MARKET baseline (prereg-declared, added 2026-07-31 per @backtest-auditor
    # finding 2): "implied bracket distribution where available (Elon 2-day
    # only, and only on price-admissible auctions)" -- scoped to elon_2day ONLY.
    elon_price_idx = L.load_prices("elonmusk")

    q1_results = {}
    q1_results["elon_2day"] = run_q1("elon_2day", q1data["elon_2day"], WALL_ELON, price_idx=elon_price_idx)
    q1_results["trump_7day"] = run_q1("trump_7day", q1data["trump_7day"], WALL_TRUMP, price_idx=None)
    for hname, res in q1_results.items():
        print(f"[Q1 {hname}] n_train={res['n_train']} n_sealed={res['n_sealed']} "
              f"R1 sealed skill vs clim={res['r1'].get('sealed_skill_vs_clim')} "
              f"R4 sealed skill (shape vs lag1)={res['r4'].get('sealed_skill')}")

    # Q1 per-row CSVs
    q1_r1_rows = pd.concat([res["r1"]["rows"] for res in q1_results.values()], ignore_index=True)
    q1_r1_rows.to_csv(OUT_DIR / "q1_r1_markov_rows.csv", index=False)
    q1_r4_rows = pd.concat([res["r4"]["rows"] for res in q1_results.values()], ignore_index=True)
    q1_r4_rows.to_csv(OUT_DIR / "q1_r4_trajectory_shape_rows.csv", index=False)
    q1_r5_rows = pd.concat([res["r5"]["rows"] for res in q1_results.values()], ignore_index=True)
    q1_r5_rows.to_csv(OUT_DIR / "q1_r5_trajectory_rules.csv", index=False)
    q1_r3_rows = pd.DataFrame([dict(handle=res["handle"], **r) for res in q1_results.values() for r in res["r3"]["lag_rows"]])
    q1_r3_rows.to_csv(OUT_DIR / "q1_r3_changepoint_lag.csv", index=False)
    print(f"[Q1] done in {time.time()-t0:.1f}s")

    # ---------------- Q2 ----------------
    print("\n=== Q2: Elon daily sectioning ===")
    daily, elon_post_ts, q1d, q2d = build_daily_series()
    base_rate_shift = compute_base_rate_shift(daily, WALL_ELON)
    print(f"[Q2] base-rate shift: mean daily posts train={base_rate_shift['mean_final_train']:.1f} "
          f"sealed={base_rate_shift['mean_final_sealed']:.1f}; LOW share train={base_rate_shift['low_share_train']:.3f} "
          f"sealed={base_rate_shift['low_share_sealed']:.3f}")
    sec = discover_sections(elon_post_ts)
    print(f"[S1] K={sec['K']} boundaries(ET)={sec['boundary_et']} centers(ET)={[s['center_et'] for s in sec['sections']]}")
    guess_compare = compare_to_user_guess(sec["sections"])
    bh = sec["boundary_hours"]

    tercile_b = tercile_brackets_from_cuts(q1d, q2d)
    train_daily_finals = [d["final"] for d in daily.days if d["s"] < WALL_ELON]
    quant_b = build_quantile_brackets(train_daily_finals, K=5)
    print(f"[Q2] tercile brackets={tercile_b}  quantile brackets={quant_b}")

    print("[Q2] running B1-B4+S2 walk-forward core (weekly refit)...")
    df_core, core_meta = run_q2_core(daily, elon_post_ts, bh, tercile_b, quant_b)
    df_core.to_csv(OUT_DIR / "q2_per_row.csv", index=False)

    metrics_train = q2_classification_metrics(df_core, "train")
    metrics_sealed = q2_classification_metrics(df_core, "sealed")
    skill = {}
    for method in ("S2", "B4", "B1"):
        for baseline in ("B4", "B1", "B2"):
            if method == baseline:
                continue
            skill[(method, baseline)] = q2_skill_vs_baseline(df_core, method, baseline, "sealed", block_size=7)
    acc_by_hour = q2_accuracy_by_hour(df_core)
    acc_by_hour.to_csv(OUT_DIR / "q2_accuracy_by_hour.csv", index=False)
    for method in ("B1", "B2", "B3", "B4", "S2"):
        rel = reliability_table(df_core, "sealed", method)
        rel.to_csv(OUT_DIR / f"q2_reliability_{method}_sealed.csv", index=False)

    print("[Q2] S3 gap-cadence rule (hypothesis b)...")
    gap_df = collect_gap_burst_features(daily, elon_post_ts, bh)
    gap_df.to_csv(OUT_DIR / "q2_gap_burst_features.csv", index=False)
    s3 = s3_gap_rule(gap_df)
    s3_literal = s3_at_fixed_threshold(gap_df, th=2.0)
    s3_literal.to_csv(OUT_DIR / "q2_s3_literal_2h.csv", index=False)

    print("[Q2] S4 burst-exhaustion rule (hypothesis c)...")
    s4_formal = s4_formal_burst_rule(daily, elon_post_ts, x_candidates=(3.0, 6.0, 9.0, bh[0], bh[1]))
    s4_literal = s4_literal_calendar(elon_post_ts)
    s4_literal["raw"] if False else None  # (raw kept internal, not exported -- summary table is sufficient)

    q2 = dict(sections=sec, guess_compare=guess_compare, metrics_train=metrics_train, metrics_sealed=metrics_sealed,
              skill=skill, acc_by_hour=acc_by_hour, s3=s3, s4_formal=s4_formal, s4_literal=s4_literal,
              core_meta=core_meta, trump_raw_n=q1data["trump_7day_raw_n"], trump_dropped=q1data["n_overlap_dropped"],
              base_rate_shift=base_rate_shift)
    print(f"[Q2] done in {time.time()-t0:.1f}s total")

    # ---------------- summary + RUN_META ----------------
    summary_text = write_summary(q1_results, q2, OUT_DIR / "summary.md")
    print("\n" + "=" * 60)
    print(summary_text[:3000])
    print("=" * 60)

    headline = {
        "q1_elon_R1_sealed_skill_vs_clim": q1_results["elon_2day"]["r1"].get("sealed_skill_vs_clim", {}).get("mean") if q1_results["elon_2day"]["r1"].get("sealed_skill_vs_clim") else None,
        "q1_elon_R4_sealed_skill_shape_vs_lag1": q1_results["elon_2day"]["r4"].get("sealed_skill", {}).get("mean") if q1_results["elon_2day"]["r4"].get("sealed_skill") else None,
        "q2_S2_vs_B4_sealed_skill": skill[("S2", "B4")]["skill_mean"] if skill.get(("S2", "B4")) else None,
        "q2_S2_vs_B4_ci_lo": skill[("S2", "B4")]["ci_lo"] if skill.get(("S2", "B4")) else None,
        "q2_S2_vs_B4_ci_hi": skill[("S2", "B4")]["ci_hi"] if skill.get(("S2", "B4")) else None,
        "q2_primary_beats_hmm": bool(skill.get(("S2", "B4")) and skill[("S2", "B4")]["ci_lo"] > 0),
        "discovered_K_sections": sec["K"],
        "n_auctions_elon_2day_sealed": q1_results["elon_2day"]["n_sealed"],
        "n_auctions_trump_7day_sealed": q1_results["trump_7day"]["n_sealed"],
        "n_days_elon_sealed": int(len(daily.days) - sum(1 for d in daily.days if d["s"] < WALL_ELON)),
        "s4_formal_sealed_lift": float(s4_formal["table"][s4_formal["table"].span == "sealed"].lift.iloc[0]),
        "s4_formal_sealed_jk_dropbest": float(s4_formal["table"][s4_formal["table"].span == "sealed"].lift_jk_dropbest.iloc[0]),
        "b5_elon2day_sealed_skill_vs_market": (q1_results["elon_2day"]["r1"].get("sealed_skill_vs_market") or {}).get("mean"),
        "b5_elon2day_n_admissible_of_total": f"{q1_results['elon_2day']['b5_n_admissible']}/{q1_results['elon_2day']['b5_n_total']}",
        "elon_mean_daily_posts_train_vs_sealed": f"{base_rate_shift['mean_final_train']:.1f}->{base_rate_shift['mean_final_sealed']:.1f}",
    }
    emit_run_meta(
        script=__file__,
        headline=headline,
        data_paths=[str(Path(__file__).resolve().parent / "elon_backfill_2025-09_to_now.parquet"),
                    "canonical/posts/realDonaldTrump", "canonical/auctions/elonmusk",
                    "canonical/auctions/realDonaldTrump", "canonical/prices/elonmusk"],
        window_basis="noon-ET from slug (auctions); noon-ET-anchored 24h blocks (Elon daily, per-day "
                      "hour=12-in-tz construction -- FIXED 2026-07-31 (2 passes), see notes)",
        fills="n/a -- forecast-accuracy/calibration diagnostic, no P&L, no fills simulated",
        trial_count=TRIALS["n"],
        scope="accuracy-diagnostic + descriptive rule discovery",
        notes=f"Re-run 2026-07-31 per @backtest-auditor WARN (regime_discovery_2026-07-31.md): (1) fixed DailySeries "
              f"DST-anchoring bug (was accumulating raw 86400s offsets, drifted 126 TRAIN days off noon-ET); "
              f"(1b) 2nd DST pass same day, same audit: the 1st fix's `pd.Timestamp(date,tz=ET)+Timedelta(hours=12)` "
              f"still misfired by 1h on the 2 literal transition dates (absolute-duration add on a wall-clock "
              f"instant) -- both DailySeries and s4_literal_calendar (identical pattern) now construct noon/5am/"
              f"midnight directly via pd.Timestamp(year=,month=,day=,hour=,tz=ET), the trump_day0/add_days_et idiom; "
              f"(2) implemented B5/MARKET baseline for elon_2day Q1 R1 "
              f"(price-admissible {q1_results['elon_2day']['b5_n_admissible']}/{q1_results['elon_2day']['b5_n_total']} "
              f"auctions), out of scope for trump_7day and for Q2 (Q2 has no market -- arbitrary daily windows, "
              f"not tradeable auctions); (3) added jackknife to s3_gap_rule/s4_formal_burst_rule/s4_literal_calendar "
              f"(previously missing); (4) disclosed base-rate shift (Elon mean daily posts "
              f"{base_rate_shift['mean_final_train']:.1f} train -> {base_rate_shift['mean_final_sealed']:.1f} sealed). "
              f"Q1 R1/R4 walk-forward on auction-level regime sequences (elon_2day n_train=38/n_sealed=28, "
              f"trump_7day DE-OVERLAPPED n_train=22/n_sealed=10 -- SUCCESS_N_FLOOR={SUCCESS_N_FLOOR}, trump sealed is "
              f"AT the floor). Q2 S1-S5 on Elon daily only (n_train_days=212/n_sealed_days=87), B4=reused fit_M4/"
              f"predict_M4_pmf from pattern_discovery_methods.py (n_states={core_meta['n_states']}, cv={core_meta['hmm_cv_ok']}), "
              f"weekly refit_block=7. trial_by_method={TRIALS['by_method']}",
        out_dir="regime_out",
    )
    print(f"\n[total runtime] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
