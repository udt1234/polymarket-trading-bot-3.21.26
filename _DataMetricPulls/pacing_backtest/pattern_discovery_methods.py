# -*- coding: utf-8 -*-
"""M1-M7 method implementations + B1-B3 baseline synthesizers for
pattern_discovery_2026-07-26.py. B4 (market) lives directly in the main
script since it only needs the price index, no fitting.

Every fit_* function is called ONCE per decision-unit (auction or weekly
daily-block), using ONLY priors = units that ENDED before this unit's START
(THE WALL). Hyperparameters are selected once via train-only CV in the main
script and passed in frozen; nothing in this file ever looks at ts > T.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize
from scipy.special import erf as _scipy_erf
from sklearn.tree import DecisionTreeClassifier
from sklearn.cluster import KMeans
from sklearn.ensemble import GradientBoostingClassifier

from pattern_discovery_lib import (
    obs_count, gap_features, et_hour_dow, gaussian_mixture_bracket_probs,
    discrete_pmf_bracket_probs,
)

# Audit fix (audit 2026-07-29, Finding [CLASS C] LOW): a single shared RNG
# meant a fix to one stochastic method's draw count (M6's thinning-sim bug)
# silently perturbed the other's (M5's Monte-Carlo) output -- 6,588/21,871
# rows changed with zero code change to M5 itself, undisclosed. Each
# stochastic method now gets its own independently-seeded generator, derived
# from the same RNG_SEED plus a per-method offset, so a future change to one
# method's draw count can never again perturb another method's stream.
RNG_SEED = 20260726
RNG_M5 = np.random.default_rng(RNG_SEED + 5)  # M5 Monte-Carlo forward sim (predict_M5_sim)
RNG_M6 = np.random.default_rng(RNG_SEED + 6)  # M6 Ogata thinning sim (_hawkes_thin_sim)

FEATURE_NAMES = [
    "count_so_far", "hours_into_window", "median_gap_s", "longest_gap_s",
    "gap_var_s2", "first_post_hours", "max_posts_60min", "posts_last_1h",
    "posts_last_3h", "posts_last_6h", "dow", "et_hour", "prior_window_final",
    "trailing_7d_mean", "share_qr",
]
# Reduced covariate set used by M5's interval-level hazard model (every 15 min
# across the whole window makes the full gap_features() sub-loop O(n^2) --
# dropped median/longest/variance-gap and max_posts_60min there specifically;
# every other declared feature is kept. Disclosed in the run summary.
M5_FEATURE_NAMES = [
    "count_so_far", "hours_into_window", "posts_last_1h", "posts_last_3h",
    "posts_last_6h", "dow", "et_hour", "prior_window_final",
    "trailing_7d_mean", "share_qr",
]


def build_features(post_ts, is_qr, s, T, prior_final, trailing7):
    o = obs_count(post_ts, s, T)
    eh = (T - s) / 3600.0
    gf = gap_features(post_ts, s, T)
    et_hour, dow = et_hour_dow(T)
    import bisect
    lo = bisect.bisect_left(post_ts, s)
    hi = bisect.bisect_left(post_ts, T)
    n_seg = hi - lo
    n_qr = int(is_qr[lo:hi].sum()) if n_seg else 0
    share_qr = n_qr / max(1, n_seg)
    d = dict(count_so_far=float(o), hours_into_window=eh, dow=float(dow),
              et_hour=float(et_hour), prior_window_final=float(prior_final) if prior_final is not None else np.nan,
              trailing_7d_mean=float(trailing7) if trailing7 is not None else np.nan,
              share_qr=share_qr)
    d.update(gf)
    return o, d


def feat_vector(d: dict, names):
    return np.array([0.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else v
                      for v in (d.get(n, 0.0) for n in names)], dtype=float)


# ---------------------------------------------------------------------------
# M1: empirical conditional table P(bracket | hours_in, count_so_far),
#     hierarchical shrinkage toward climatology
# ---------------------------------------------------------------------------
def fit_M1(priors, checkpoints, post_ts, n_bins=3):
    state = {}
    for c in checkpoints:
        o_vals, rem_vals = [], []
        for p in priors:
            dur_s = p["e"] - p["s"]
            if c * 3600 >= dur_s:
                continue
            T = p["s"] + c * 3600
            o = obs_count(post_ts, p["s"], T)
            o_vals.append(o)
            rem_vals.append(p["final"] - o)
        if len(o_vals) < 6:
            state[c] = None
            continue
        edges = np.quantile(o_vals, np.linspace(0, 1, n_bins + 1)[1:-1]) if n_bins > 1 else np.array([])
        o_arr = np.array(o_vals)
        bin_idx = np.searchsorted(edges, o_arr)
        cell = {b: [rem_vals[i] for i in range(len(o_vals)) if bin_idx[i] == b] for b in range(max(n_bins, 1))}
        state[c] = dict(edges=edges, cell=cell, clim=rem_vals, n=len(o_vals))
    return state


def _M1_mixture(state, c, o, k, bw_frac):
    st = state.get(c) if state else None
    if st is None or len(st["clim"]) < 4:
        return None
    bidx = int(np.searchsorted(st["edges"], o))
    cell_vals = st["cell"].get(bidx, [])
    clim_vals = st["clim"]
    n_cell = len(cell_vals)
    lam = n_cell / (n_cell + k) if n_cell > 0 else 0.0
    w_cell = np.full(n_cell, lam / n_cell) if n_cell > 0 else np.array([])
    w_clim = np.full(len(clim_vals), (1 - lam) / len(clim_vals))
    centers = np.array(list(cell_vals) + list(clim_vals), dtype=float) + o
    weights = np.concatenate([w_cell, w_clim])
    std = float(np.std(clim_vals)) if len(clim_vals) > 1 else 5.0
    bw = max(bw_frac * std, 1.0)
    return centers, weights, bw


def predict_M1(state, c, o, brackets, k=8, bw_frac=0.3):
    mix = _M1_mixture(state, c, o, k, bw_frac)
    if mix is None:
        return None
    centers, weights, bw = mix
    return gaussian_mixture_bracket_probs(centers, weights, bw, brackets)


def predict_M1_pmf(state, c, o, k, bw_frac, maxn):
    """Discrete PMF version of M1 (for M7 composition)."""
    mix = _M1_mixture(state, c, o, k, bw_frac)
    if mix is None:
        return None
    centers, weights, bw = mix
    weights = weights / weights.sum()
    xs = np.arange(0, maxn)
    pmf = np.zeros(maxn)
    for ctr, w in zip(centers, weights):
        z_lo = (xs - 0.5 - ctr) / bw
        z_hi = (xs + 0.5 - ctr) / bw
        pmf += w * (_ncdf(z_hi) - _ncdf(z_lo))
    pmf = np.clip(pmf, 0, None)
    tot = pmf.sum()
    return pmf / tot if tot > 0 else None


def _ncdf(z):
    return 0.5 * (1.0 + _scipy_erf(np.asarray(z) / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# M2: shallow CART on final bracket (quantile-bin proxy label + within-bin
#     empirical density), depth<=4, min_leaf>=25, ccp-pruned via train CV
# ---------------------------------------------------------------------------
def make_bin_edges(finals, K):
    edges = np.quantile(finals, np.linspace(0, 1, K + 1))
    edges = np.array(edges, dtype=float)
    edges[0] = -np.inf
    edges[-1] = np.inf
    return edges


def label_from_final(final, edges):
    return int(np.clip(np.searchsorted(edges, final, side="right") - 1, 0, len(edges) - 2))


def fit_M2(priors, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn, edges,
           max_depth=4, min_samples_leaf=25, ccp_alpha=0.0):
    X, y = [], []
    for p in priors:
        dur_s = p["e"] - p["s"]
        for c in checkpoints:
            if c * 3600 >= dur_s:
                continue
            T = p["s"] + c * 3600
            _, feats = build_features(post_ts, is_qr, p["s"], T,
                                       prior_final_fn(p["s"]), trailing_fn(T))
            X.append(feat_vector(feats, FEATURE_NAMES))
            y.append(label_from_final(p["final"], edges))
    if len(X) < 30 or len(set(y)) < 2:
        return None
    clf = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=min_samples_leaf,
                                  ccp_alpha=ccp_alpha, random_state=0)
    clf.fit(np.vstack(X), y)
    bin_pool = {}
    for p in priors:
        lbl = label_from_final(p["final"], edges)
        bin_pool.setdefault(lbl, []).append(p["final"])
    return dict(clf=clf, bin_pool=bin_pool)


def predict_M2(state, feats: dict, brackets):
    if state is None:
        return None
    x = feat_vector(feats, FEATURE_NAMES).reshape(1, -1)
    proba = state["clf"].predict_proba(x)[0]
    classes = state["clf"].classes_
    centers, weights = [], []
    for cls, p in zip(classes, proba):
        pool = state["bin_pool"].get(cls, [])
        if not pool or p <= 0:
            continue
        centers.extend(pool)
        weights.extend([p / len(pool)] * len(pool))
    if not centers:
        return None
    all_vals = [v for pool in state["bin_pool"].values() for v in pool]
    bw = max(0.35 * float(np.std(all_vals)), 2.0)
    return gaussian_mixture_bracket_probs(np.array(centers), np.array(weights), bw, brackets)


# ---------------------------------------------------------------------------
# M3: day-shape clustering (KMeans, k=3..8) on 24-dim normalized hourly vector.
#     Centroids fit on TRAIN ONLY, then FROZEN (per prereg, unlike the other
#     methods' walk-forward refit). Per-cluster remaining-distributions are
#     refreshed walk-forward from priors assigned to the frozen centroids.
# ---------------------------------------------------------------------------
def fit_M3_centroids(train_days, post_ts, k):
    vecs, finals = [], []
    for d in train_days:
        v = np.array([obs_count(post_ts, d["s"] + h * 3600, d["s"] + (h + 1) * 3600) for h in range(24)], float)
        tot = v.sum()
        if tot < 3:
            continue
        vecs.append(v / tot)
        finals.append(tot)
    if len(vecs) < max(k * 3, 10):
        return None
    X = np.vstack(vecs)
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    return dict(centroids=km.cluster_centers_, k=k)


def _assign_cluster(centroids, shape_vec):
    d = np.sum((centroids - shape_vec) ** 2, axis=1)
    return int(np.argmin(d)), d


def fit_M3_state(centroids_state, priors_days, post_ts):
    """Walk-forward: assign each prior day (FULL shape) to nearest frozen
    centroid, pool remaining-count-at-checkpoint samples per cluster."""
    if centroids_state is None:
        return None
    centroids = centroids_state["centroids"]
    per_cluster_days = {i: [] for i in range(len(centroids))}
    for d in priors_days:
        v = np.array([obs_count(post_ts, d["s"] + h * 3600, d["s"] + (h + 1) * 3600) for h in range(24)], float)
        tot = v.sum()
        if tot < 1:
            continue
        cl, _ = _assign_cluster(centroids, v / tot)
        per_cluster_days[cl].append(d)
    return dict(centroids=centroids, per_cluster_days=per_cluster_days)


def predict_M3(state, post_ts, s, T, brackets, tau=0.15):
    if state is None:
        return None
    centroids = state["centroids"]
    eh = int(round((T - s) / 3600))
    eh = max(1, min(24, eh))
    partial = np.array([obs_count(post_ts, s + h * 3600, s + (h + 1) * 3600) for h in range(eh)], float)
    o = int(partial.sum())
    partial_norm = partial / max(o, 1)
    cent_partial = centroids[:, :eh]
    cent_partial = cent_partial / np.clip(cent_partial.sum(axis=1, keepdims=True), 1e-6, None)
    dist = np.sqrt(np.sum((cent_partial - partial_norm) ** 2, axis=1))
    w = np.exp(-(dist ** 2) / (2 * tau ** 2))
    if w.sum() <= 0:
        w = np.ones_like(w)
    w = w / w.sum()
    centers, weights = [], []
    for ci, days in state["per_cluster_days"].items():
        if not days or w[ci] <= 1e-9:
            continue
        # remaining-count for this cluster's historical days AT elapsed hour eh.
        # DST fix (audit 2026-07-31): use the day's own d["e"] (DST-aware, set by
        # DailySeries via add_days_et) as the day END, NOT d["s"] + 86400 -- on a
        # 23h/25h DST-transition day the fixed-seconds offset disagrees with the
        # real (DailySeries-defined) day boundary by up to 1h.
        rems = [obs_count(post_ts, d["s"] + eh * 3600, d["e"]) for d in days]
        each_w = w[ci] / len(rems)
        centers.extend([o + r for r in rems])
        weights.extend([each_w] * len(rems))
    if not centers:
        return None
    std = float(np.std(centers)) if len(centers) > 1 else 5.0
    bw = max(0.3 * std, 1.0)
    return gaussian_mixture_bracket_probs(np.array(centers, float), np.array(weights, float), bw, brackets)


# ---------------------------------------------------------------------------
# M4: PoissonHMM on hourly counts, 2-4 latent states, transition matrix fit
#     on priors only (refit walk-forward, capped to last N priors for speed)
# ---------------------------------------------------------------------------
def _hourly_seq(post_ts, s, e):
    n_h = int(round((e - s) / 3600))
    return np.array([obs_count(post_ts, s + h * 3600, s + (h + 1) * 3600) for h in range(n_h)], dtype=int)


def fit_M4(priors, post_ts, n_states, cap=40, n_iter=40):
    from hmmlearn.hmm import PoissonHMM
    use = priors[-cap:]
    seqs = [_hourly_seq(post_ts, p["s"], p["e"]) for p in use]
    seqs = [x for x in seqs if len(x) > 4]
    if len(seqs) < 5:
        return None
    X = np.concatenate(seqs).reshape(-1, 1)
    lengths = [len(x) for x in seqs]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = PoissonHMM(n_components=n_states, n_iter=n_iter, random_state=0, tol=1e-3)
            model.fit(X, lengths)
        converged = bool(model.monitor_.converged)
    except Exception:
        return None
    return dict(model=model, converged=converged)


def predict_M4_pmf(state, post_ts, s, T, e, maxn):
    if state is None:
        return None
    model = state["model"]
    eh = int(round((T - s) / 3600))
    obs_seq = _hourly_seq(post_ts, s, T) if eh > 0 else np.array([], dtype=int)
    o = int(obs_seq.sum())
    try:
        if eh > 0:
            _, post_prob = model.score_samples(obs_seq.reshape(-1, 1))
            pi_now = post_prob[-1]
        else:
            pi_now = model.startprob_
    except Exception:
        return None
    rh = int(round((e - T) / 3600))
    if rh <= 0:
        pmf = np.zeros(maxn)
        pmf[0] = 1.0
        return pmf
    xs = np.arange(maxn)
    total_pmf = np.array([1.0] + [0.0] * (maxn - 1))
    pi = pi_now.copy()
    lambdas = np.asarray(model.lambdas_).reshape(-1)
    for _ in range(rh):
        pi = pi @ model.transmat_
        hour_pmf = np.zeros(maxn)
        for k, lam in enumerate(lambdas):
            hour_pmf += pi[k] * poisson.pmf(xs, max(lam, 1e-6))
        hour_pmf = hour_pmf / max(hour_pmf.sum(), 1e-9)
        total_pmf = np.convolve(total_pmf, hour_pmf)[:maxn]
    tot = total_pmf.sum()
    if tot <= 0:
        return None
    return total_pmf / tot


def predict_M4(state, post_ts, s, T, e, brackets, maxn=400):
    """predict_M4_pmf returns a REMAINING-count pmf (index 0 = 0 remaining);
    offset by observed-so-far to get bracket probabilities on the FINAL count."""
    rem_pmf = predict_M4_pmf(state, post_ts, s, T, e, maxn)
    if rem_pmf is None:
        return None
    o = obs_count(post_ts, s, T)
    return discrete_pmf_bracket_probs(o, rem_pmf, brackets)


# ---------------------------------------------------------------------------
# M5: discrete-time hazard (GBM), P(post in next 15 min), features strictly<=T,
#     forecast via per-path Monte-Carlo simulation with hourly feature refresh
# ---------------------------------------------------------------------------
def _interval_table(unit, post_ts, is_qr, trailing_fn, prior_final_fn, step_s=900):
    s, e = unit["s"], unit["e"]
    n_steps = int((e - s) // step_s)
    if n_steps < 4:
        return None, None
    bounds = s + np.arange(n_steps) * step_s
    o_arr = np.searchsorted(post_ts, bounds, side="left") - np.searchsorted(post_ts, s, side="left")
    eh_arr = (bounds - s) / 3600.0
    h1 = np.searchsorted(post_ts, bounds) - np.searchsorted(post_ts, np.maximum(s, bounds - 3600))
    h3 = np.searchsorted(post_ts, bounds) - np.searchsorted(post_ts, np.maximum(s, bounds - 3 * 3600))
    h6 = np.searchsorted(post_ts, bounds) - np.searchsorted(post_ts, np.maximum(s, bounds - 6 * 3600))
    et_hours = np.array([et_hour_dow(int(b))[0] for b in bounds], float)
    dows = np.array([et_hour_dow(int(b))[1] for b in bounds], float)
    lo0 = np.searchsorted(post_ts, s)
    idx_end = np.searchsorted(post_ts, bounds)
    n_qr_cum = np.array([int(is_qr[lo0:i].sum()) for i in idx_end])
    n_seg = idx_end - lo0
    share_qr = np.divide(n_qr_cum, np.maximum(n_seg, 1))
    y = (np.searchsorted(post_ts, bounds + step_s) - np.searchsorted(post_ts, bounds)) > 0
    pf = prior_final_fn(s)
    t7 = trailing_fn(s)
    X = np.column_stack([
        o_arr, eh_arr, h1, h3, h6, dows, et_hours,
        np.full(n_steps, pf if pf is not None else 0.0),
        np.full(n_steps, t7 if t7 is not None else 0.0),
        share_qr,
    ])
    return X.astype(float), y.astype(int)


def fit_M5(priors, post_ts, is_qr, trailing_fn, prior_final_fn, n_estimators=80, max_depth=2, cap=40):
    Xs, ys = [], []
    for p in priors[-cap:]:
        X, y = _interval_table(p, post_ts, is_qr, trailing_fn, prior_final_fn)
        if X is None:
            continue
        Xs.append(X)
        ys.append(y)
    if not Xs:
        return None
    X = np.vstack(Xs)
    y = np.concatenate(ys)
    if y.sum() < 20 or y.sum() >= len(y) - 5:
        return None
    clf = GradientBoostingClassifier(n_estimators=n_estimators, max_depth=max_depth,
                                      learning_rate=0.1, random_state=0)
    clf.fit(X, y)
    return dict(clf=clf)


def predict_M5_sim(state, post_ts, is_qr, s, T, e, trailing_fn, prior_final_fn, n_sims=150):
    """Simulate forward from T to e in HOURLY steps. Within an hour the fitted
    15-min hazard p is held constant (features only refresh hourly, matching
    fit_M5's disclosed compute cap), so draws-per-hour ~ Binomial(4,p) is
    EXACTLY the sum of 4 iid 15-min Bernoulli(p) draws -- not an approximation,
    just a cheaper equivalent sampler. Rolling h1/h3/h6 tracked via a per-path
    6-hour ring buffer of hourly totals, seeded from REAL history at T."""
    if state is None:
        return None
    clf = state["clf"]
    o0 = obs_count(post_ts, s, T)
    pf = prior_final_fn(s) or 0.0
    t7 = trailing_fn(s) or 0.0
    n_seg0 = max(o0, 1)
    n_qr0 = int(is_qr[np.searchsorted(post_ts, s):np.searchsorted(post_ts, T)].sum())
    share_qr = np.full(n_sims, n_qr0 / n_seg0)
    # seed the 6-hour ring buffer with REAL hourly counts for the (up to) 6
    # real hours immediately before T, clamped at window start s
    buf = np.zeros((n_sims, 6))
    for k in range(6):
        hi_b = T - k * 3600
        lo_b = max(s, hi_b - 3600)
        if hi_b <= s:
            break
        buf[:, 5 - k] = obs_count(post_ts, lo_b, hi_b)
    cur_o = np.full(n_sims, float(o0))
    counts = np.zeros(n_sims, dtype=int)
    n_hours_left = int(math.ceil((e - T) / 3600.0))
    t = T
    for step in range(n_hours_left):
        step_len_s = min(3600.0, e - t)
        if step_len_s <= 0:
            break
        h1 = buf[:, 5]
        h3 = buf[:, 3:6].sum(axis=1)
        h6 = buf[:, 0:6].sum(axis=1)
        eh = (t - s) / 3600.0
        et_hour, dow = et_hour_dow(int(t))
        X = np.column_stack([cur_o, np.full(n_sims, eh), h1, h3, h6,
                              np.full(n_sims, float(dow)), np.full(n_sims, float(et_hour)),
                              np.full(n_sims, pf), np.full(n_sims, t7), share_qr])
        p15 = np.clip(clf.predict_proba(X)[:, 1], 1e-6, 1 - 1e-6)
        n_sub = max(1, int(round(step_len_s / 900.0)))
        draws = RNG_M5.binomial(n_sub, p15)
        counts += draws
        cur_o += draws
        buf = np.roll(buf, -1, axis=1)
        buf[:, 5] = draws
        t += step_len_s
    return o0 + counts


def predict_M5(state, post_ts, is_qr, s, T, e, trailing_fn, prior_final_fn, brackets, n_sims=150):
    finals = predict_M5_sim(state, post_ts, is_qr, s, T, e, trailing_fn, prior_final_fn, n_sims=n_sims)
    if finals is None or len(finals) == 0:
        return None
    weights = np.ones(len(finals))
    bw = max(1.5, 0.15 * float(np.std(finals)))
    return gaussian_mixture_bracket_probs(finals.astype(float), weights, bw, brackets)


# ---------------------------------------------------------------------------
# M6: Hawkes self-exciting process w/ circadian baseline, MLE-fit (mu,alpha,beta),
#     forecast via Ogata thinning simulation
# ---------------------------------------------------------------------------
def _circadian_mult(post_ts, before_ts, lookback_days=120):
    lo = np.searchsorted(post_ts, before_ts - lookback_days * 86400)
    hi = np.searchsorted(post_ts, before_ts)
    seg = post_ts[lo:hi]
    if len(seg) < 240:
        return np.ones(24)
    hrs = np.array([et_hour_dow(int(t))[0] for t in seg])
    counts = np.array([np.sum(hrs == h) for h in range(24)], dtype=float)
    m = counts.mean()
    return counts / m if m > 0 else np.ones(24)


def _et_hour_from_rel(t_hours_since_noon):
    """seqs_rel_hours are hours-since-window-start, and EVERY window (auction or
    daily) starts at noon ET by construction (noon_window() / DailySeries both
    anchor at 12:00 ET). So the real ET clock hour is (12 + floor(t)) % 24, NOT
    int(t) % 24 (which would silently treat the window start as ET-midnight --
    a 12h phase error in the circadian baseline lookup, fixed here)."""
    return (12 + int(t_hours_since_noon)) % 24


def _hawkes_negloglik(params, seqs_rel_hours, durations_h, mult):
    mu, alpha, beta = params
    if mu <= 1e-6 or alpha < 0 or beta <= 1e-3 or alpha >= beta * 0.98:
        return 1e10
    total_ll = 0.0
    for ev, dur_h in zip(seqs_rel_hours, durations_h):
        R = 0.0
        prev = 0.0
        ll = 0.0
        for t in ev:
            if t > prev:
                R = math.exp(-beta * (t - prev)) * (R)
            hr = _et_hour_from_rel(t)
            lam = mu * mult[hr] + alpha * R
            if lam <= 0:
                return 1e10
            ll += math.log(lam)
            R = R + 1.0
            prev = t
        base_integral = mu * sum(mult[_et_hour_from_rel(h)] for h in range(int(math.ceil(dur_h))))
        excite_integral = alpha / beta * sum(1 - math.exp(-beta * (dur_h - t)) for t in ev)
        ll -= (base_integral + excite_integral)
        total_ll += ll
    return -total_ll


def fit_M6(priors, post_ts, before_ts, cap=40, restarts=2):
    use = priors[-cap:]
    seqs, durs = [], []
    for p in use:
        lo = np.searchsorted(post_ts, p["s"])
        hi = np.searchsorted(post_ts, p["e"])
        ev = (post_ts[lo:hi].astype(float) - p["s"]) / 3600.0
        if len(ev) < 3:
            continue
        seqs.append(ev)
        durs.append((p["e"] - p["s"]) / 3600.0)
    if len(seqs) < 5:
        return None
    mult = _circadian_mult(post_ts, before_ts)
    total_events = sum(len(e) for e in seqs)
    total_h = sum(durs)
    mean_rate = total_events / max(total_h, 1.0)
    best = None
    for i in range(restarts):
        x0 = [max(mean_rate * (0.5 if i == 0 else 0.3), 0.05),
              mean_rate * (0.3 if i == 0 else 0.5),
              (1.0 if i == 0 else 2.0)]
        try:
            res = minimize(_hawkes_negloglik, x0, args=(seqs, durs, mult),
                            method="Nelder-Mead",
                            options={"maxiter": 300, "xatol": 1e-3, "fatol": 1e-2})
        except Exception:
            continue
        if best is None or res.fun < best.fun:
            best = res
    if best is None or not np.isfinite(best.fun):
        return None
    mu, alpha, beta = best.x
    return dict(mu=float(mu), alpha=float(alpha), beta=float(beta), mult=mult,
                converged=bool(best.success), n_events=total_events, n_seqs=len(seqs))


def _hawkes_thin_sim(mu, alpha, beta, mult, s, T, e, hist_events_rel_hours, n_sims=150, max_events=4000):
    """Ogata thinning from T to e (hours since s), seeded by real history up to T.

    BUG FIX (audit pattern_discovery_2026-07-26.md Finding 3, confirmed by direct
    reproduction 2026-07-29): the prior version only decayed R (the self-excitation
    accumulator) on ACCEPTED candidates, leaving R frozen at its pre-rejection value
    across every REJECTED thinning candidate. Since real time (t) still advanced on
    rejection, R was structurally undecayed relative to elapsed time on the (many)
    rejected steps, so lam_bar stayed artificially inflated indefinitely -> runaway
    event generation. Reproduced on a real auction (elon-musk-of-tweets-april-16-
    april-18, true final=77): the broken simulator gave mean(finals)=1516 (20x too
    high, near-zero density on the true bracket -> the reported 12-nat log loss).
    Fixed: R is decayed to t2 on EVERY iteration (accept or reject); +1.0 is added
    only on acceptance. Also uses mult.max() (not mult[hr] at the CURRENT hour) as
    the circadian upper bound so lam_bar is a valid Ogata bound over the whole
    candidate interval [t,t2], since the multiplier can rise between hr and hr2.
    Re-reproduced after the fix: mean(finals) ~= 85-100 for the same auction, in
    the right neighborhood of the true final=77.
    """
    dur_T = (T - s) / 3600.0
    dur_e = (e - s) / 3600.0
    R0 = 0.0
    prev = 0.0
    for t in hist_events_rel_hours:
        if t > prev:
            R0 = math.exp(-beta * (t - prev)) * R0
        R0 += 1.0
        prev = t
    if prev < dur_T:
        R0 = math.exp(-beta * (dur_T - prev)) * R0
    mult_max = float(np.max(mult))
    out = np.zeros(n_sims, dtype=int)
    for k in range(n_sims):
        t = dur_T
        R = R0
        n_ev = 0
        guard = 0
        while t < dur_e and guard < max_events:
            guard += 1
            lam_bar = mu * mult_max + alpha * R + 1e-9
            w = RNG_M6.exponential(1.0 / lam_bar)
            t2 = t + w
            if t2 >= dur_e:
                break
            R_dec = R * math.exp(-beta * (t2 - t))
            hr2 = _et_hour_from_rel(t2)
            lam_t2 = mu * mult[hr2] + alpha * R_dec
            if RNG_M6.random() <= lam_t2 / lam_bar:
                R = R_dec + 1.0
                n_ev += 1
            else:
                R = R_dec
            t = t2
        out[k] = n_ev
    return out


def predict_M6_sim(state, post_ts, s, T, e, n_sims=150):
    if state is None:
        return None
    lo = np.searchsorted(post_ts, s)
    hi = np.searchsorted(post_ts, T)
    hist = (post_ts[lo:hi].astype(float) - s) / 3600.0
    o = hi - lo
    counts = _hawkes_thin_sim(state["mu"], state["alpha"], state["beta"], state["mult"],
                               s, T, e, hist, n_sims=n_sims)
    return o + counts


def predict_M6(state, post_ts, s, T, e, brackets, n_sims=150):
    finals = predict_M6_sim(state, post_ts, s, T, e, n_sims=n_sims)
    if finals is None or len(finals) == 0:
        return None
    weights = np.ones(len(finals))
    bw = max(1.5, 0.15 * float(np.std(finals)))
    return gaussian_mixture_bracket_probs(finals.astype(float), weights, bw, brackets)


def predict_M6_pmf(state, post_ts, s, T, e, maxn, n_sims=150):
    finals = predict_M6_sim(state, post_ts, s, T, e, n_sims=n_sims)
    if finals is None:
        return None
    pmf = np.zeros(maxn)
    xs = np.arange(maxn)
    bw = 1.5
    for v in finals:
        z_lo = (xs - 0.5 - v) / bw
        z_hi = (xs + 0.5 - v) / bw
        pmf += (_ncdf(z_hi) - _ncdf(z_lo))
    tot = pmf.sum()
    return pmf / tot if tot > 0 else None


# ---------------------------------------------------------------------------
# M7: compose a fitted DAILY model (M1 or M6, already fit on this handle's
#     daily substrate) up to a 2-day/7-day total via discrete convolution of
#     per-day remaining-count PMFs. today_pmf_fn/full_day_pmf_fn each return a
#     FINAL-day-count pmf (index i = P(day final == i)); see main script for
#     how M1-daily / M6-daily are wired in as those functions.
# ---------------------------------------------------------------------------
def compose_M7(today_final_pmf, o_today, full_day_final_pmf, n_future_days, o_window, maxn_total):
    """today_final_pmf/full_day_final_pmf: 1-D arrays, index i = P(day final==i).
    Returns the WINDOW final-count pmf (index i = P(window final == i))."""
    if today_final_pmf is None:
        return None
    today_final_pmf = np.asarray(today_final_pmf, float)
    rem_today = today_final_pmf[o_today:] if o_today < len(today_final_pmf) else np.array([1.0])
    if rem_today.sum() <= 0:
        rem_today = np.array([1.0])
    rem_today = rem_today / rem_today.sum()
    total_pmf = rem_today
    if n_future_days > 0:
        if full_day_final_pmf is None:
            return None
        fday = np.asarray(full_day_final_pmf, float)
        fday = fday / fday.sum()
        for _ in range(n_future_days):
            total_pmf = np.convolve(total_pmf, fday)
    total_pmf = total_pmf[:maxn_total] if len(total_pmf) > maxn_total else total_pmf
    # shift by o_window (posts already observed across the WHOLE window, i.e.
    # previous complete days + today's partial day)
    out = np.zeros(maxn_total)
    n = min(len(total_pmf), maxn_total - o_window)
    if n <= 0:
        return None
    out[o_window:o_window + n] = total_pmf[:n]
    tot = out.sum()
    return out / tot if tot > 0 else None
