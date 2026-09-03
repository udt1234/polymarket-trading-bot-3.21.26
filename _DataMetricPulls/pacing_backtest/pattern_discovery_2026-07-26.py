# -*- coding: utf-8 -*-
"""PRE-REGISTERED pattern-discovery study: do learnable post-cadence patterns beat
the market's implied bracket distribution? Built strictly against
`_DataMetricPulls/pacing_backtest/prereg/pattern_discovery_2026-07-26.md` -- read
that file for the fixed question, WALL dates, targets, checkpoints, methods,
baselines, and success criteria. This script does not certify its own result;
hand off to @backtest-auditor.

Scope: (b) pure forecast-accuracy / calibration diagnostic. No P&L, no fills.
"""
from __future__ import annotations

import math
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root for run_meta -> locked_pace

import pattern_discovery_lib as L
import pattern_discovery_methods as M
from run_meta import emit_run_meta
from api.modules.shared.locked_pace import build_priors as lp_build_priors, project_locked, bracket_fair, calib_sigma

warnings.filterwarnings("ignore")
RNG_SEED = 20260726
np.random.seed(RNG_SEED)

OUT_DIR = Path(__file__).resolve().parent / "pattern_discovery_out"
OUT_DIR.mkdir(exist_ok=True)
ET = L.ET

CHECKPOINTS_2DAY = [6, 12, 24, 36]
CHECKPOINTS_7DAY = [24, 48, 84, 120, 156]
CHECKPOINTS_DAILY = [6, 12, 15, 18, 21]          # target-1's OWN evaluation grid (not prereg-mandated hours,
                                                  # chosen to include the 18/21 null-check hours named in prereg)
CHECKPOINTS_DAILY_COMPOSE = list(range(0, 24, 2))  # denser internal grid M7 uses to query the daily model
SYNTHETIC_DAILY_K = 5                             # daily target has no real market bracket; quantile-bin
                                                  # scoring grid, frozen from TRAIN daily finals, for
                                                  # consistent log-loss/Brier scoring only (NOT tradeable)

WALL_ELON = int(pd.Timestamp("2026-04-01 00:00:00", tz=ET).timestamp())
WALL_TRUMP = int(pd.Timestamp("2026-01-01 00:00:00", tz=ET).timestamp())

TRIALS = {"n": 0, "by_method": {}}
DAILY_BRACKETS = None   # set in main(): synthetic quantile-bin scoring grid for
DAILY_BRACKET_LABEL = None  # target 1, frozen from TRAIN daily finals only.
COVERAGE = {}

# Audit 2026-07-29 (re-audit #2, Finding 2): minimum admissible-auction count a
# beats-baseline flag must clear before it is reported as a bare method list, in
# BOTH RUN_META and summary.md. Below this floor, block_bootstrap_ci (block_size=1)
# is bounded exactly by the handful of raw per-auction skill values, so "CI
# excludes zero" only requires those values to already share a sign -- at n=3 that
# is P=25% under a true null of zero skill, five times the nominal 5% a 95% CI
# implies, not evidence. This structurally enforces the prereg's own existing
# rule (CI including zero => unproven; n<10 => noise) instead of leaving it to a
# reader to find the right paragraph. Reporting gate only: underlying skill/CI/
# jackknife/n are never hidden, only the headline pass/fail label.
SUCCESS_N_FLOOR = 10


def _trial(method, k=1):
    TRIALS["n"] += k
    TRIALS["by_method"][method] = TRIALS["by_method"].get(method, 0) + k


def build_daily_brackets(train_finals, K):
    cuts = sorted(set(int(round(q)) for q in np.quantile(train_finals, np.linspace(0, 1, K + 1)[1:-1])))
    edges = [0] + [c + 1 for c in cuts]
    brackets = []
    for i, lo in enumerate(edges):
        hi = (edges[i + 1] - 1) if i + 1 < len(edges) else None
        label = (f"<{edges[1]}" if i == 0 and len(edges) > 1 else (f"{lo}+" if hi is None else f"{lo}-{hi}"))
        brackets.append((label, lo, hi))
    return brackets


def DAILY_BRACKET_LOOKUP(final):
    for label, lo, hi in DAILY_BRACKETS:
        if final >= lo and (hi is None or final <= hi):
            return label
    return DAILY_BRACKETS[-1][0]


# ---------------------------------------------------------------------------
# DST fix (audit 2026-07-31, Class-A data-integrity, dynamically confirmed):
# every function below that walks day-by-day across a span MUST re-anchor
# each day to noon America/New_York, never accumulate a fixed `+= 86400`
# offset. A fixed-seconds walk holds the UTC offset constant for the whole
# span; once the clock crosses a DST transition the window silently drifts by
# 1h (e.g. 11:00 ET instead of noon ET) until the next transition brings it
# back. `pd.DateOffset(days=n)` (calendar-aware) is used instead of
# `pd.Timedelta(days=n)` (fixed-duration, would reproduce the same bug).
# ---------------------------------------------------------------------------
def add_days_et(ts_unix: int, n: int) -> int:
    """Add n calendar days to a unix ts, preserving ET wall-clock time across
    DST transitions. NEVER `ts_unix + n * 86400`."""
    dt_et = pd.Timestamp(ts_unix, unit="s", tz="UTC").tz_convert(ET)
    return int((dt_et + pd.DateOffset(days=n)).timestamp())


# ---------------------------------------------------------------------------
# Daily series helper (used as: target-1 itself for Elon; M7's internal daily
# decomposition for Elon 2-day/7-day AND (interpretation, flagged in summary)
# for Trump 7-day, which has no declared standalone daily target)
# ---------------------------------------------------------------------------
class DailySeries:
    def __init__(self, post_ts, day0_noon_ts, day_end_ts):
        days = []
        i = 0
        while True:
            d = add_days_et(day0_noon_ts, i)
            e = add_days_et(day0_noon_ts, i + 1)
            if e > day_end_ts:
                break
            f = L.obs_count(post_ts, d, e)
            days.append(dict(slug=f"daily-{d}", handle="", s=d, e=e, dur="1-day", final=int(f)))
            i += 1
        self.days = days
        self.ends = np.array([x["e"] for x in days], dtype="int64")
        self.finals = np.array([x["final"] for x in days], dtype=float)

    def priors_before(self, T):
        idx = int(np.searchsorted(self.ends, T, side="left"))
        return self.days[:idx]

    def trailing_mean(self, T, n=7):
        idx = int(np.searchsorted(self.ends, T, side="left"))
        if idx == 0:
            return None
        w = self.finals[max(0, idx - n):idx]
        return float(w.mean()) if len(w) else None


def make_prior_final_fn(units):
    ends = np.array([u["e"] for u in units], dtype="int64")
    finals = np.array([u["final"] for u in units], dtype=float)

    def fn(T):
        idx = int(np.searchsorted(ends, T, side="left"))
        return float(finals[idx - 1]) if idx > 0 else None
    return fn


# ---------------------------------------------------------------------------
# Baselines. B1/B2 need SOME spread to be scored as a distribution (a point
# forecast has undefined log-loss); B1's sigma is a walk-forward error history
# exactly like the audited-clean reference calibration_test.py / odds_vs_market.py
# (`sig=std(past errors) if enough history else fallback`), never fit on the
# whole span. B2 (climatology) needs no sigma -- it IS the empirical mixture.
# ---------------------------------------------------------------------------
def B1_naive_proj(o, eh, rh):
    return o if eh <= 0 else o * (eh + rh) / eh


def B1_probs(o, eh, rh, brackets, err_hist):
    proj = B1_naive_proj(o, eh, rh)
    sigma = float(np.std(err_hist)) if len(err_hist) >= 5 else max(8.0, 0.2 * max(proj, 1))
    return L.normal_bracket_probs(proj, sigma, brackets), proj


def B2_probs(priors, brackets):
    finals = np.array([p["final"] for p in priors], dtype=float)
    if len(finals) < 4:
        return None
    std = float(np.std(finals)) if len(finals) > 1 else 5.0
    bw = max(0.35 * std, 2.0)
    return L.gaussian_mixture_bracket_probs(finals, np.ones(len(finals)), bw, brackets)


def B3_probs(post_ts, unit_s, dur_h, o, eh, rh, brackets):
    pri = lp_build_priors(list(post_ts), unit_s, dur_h, unit_s)
    if pri is None:
        return None
    rmean, Kk, share = pri
    proj = project_locked(o, eh, rh, dict(rmean=rmean, Kk=Kk, share=share))
    if proj is None:
        return None
    sigma = calib_sigma(rh)
    out = {label: bracket_fair(lo, hi if hi is not None else 1e9, proj, sigma) for label, lo, hi in brackets}
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()}


def B4_probs(price_idx, slug, brackets, T):
    probs, n_cov, n_tot = L.market_bracket_probs(price_idx, slug, brackets, T)
    return probs, n_cov, n_tot


# ---------------------------------------------------------------------------
# Train-only hyperparameter selection (chronological 70/30 holdout WITHIN the
# train span -- fit once on the first 70%, score once on the last 30%, both
# ends strictly before the WALL. This is a disclosed simplification of a full
# walk-forward-per-candidate grid search, done purely to keep the sweep
# tractable; it is still 100% causal (fit_pool always precedes eval_pool) and
# is NEVER used to pick anything using sealed-span outcomes.
# ---------------------------------------------------------------------------
def _cv_split(train_units, frac=0.7):
    idx = int(len(train_units) * frac)
    return train_units[:idx], train_units[idx:]


def select_M1(train_units, checkpoints, post_ts):
    fit_pool, eval_pool = _cv_split(train_units)
    default = dict(n_bins=3, k=8, bw_frac=0.3)
    if len(fit_pool) < 10 or len(eval_pool) < 5:
        return default, False
    best = None
    for n_bins in (2, 3):
        state = M.fit_M1(fit_pool, checkpoints, post_ts, n_bins=n_bins)
        for k in (5, 15):
            for bw_frac in (0.25, 0.4):
                losses = []
                for u in eval_pool:
                    for c in checkpoints:
                        if c * 3600 >= (u["e"] - u["s"]):
                            continue
                        T = u["s"] + c * 3600
                        o = L.obs_count(post_ts, u["s"], T)
                        probs = M.predict_M1(state, c, o, u["brackets"], k=k, bw_frac=bw_frac)
                        if probs is None:
                            continue
                        losses.append(L.log_loss_1(probs, u["winner"]))
                _trial("M1")
                if losses and (best is None or np.mean(losses) < best[0]):
                    best = (np.mean(losses), dict(n_bins=n_bins, k=k, bw_frac=bw_frac))
    return (best[1], True) if best else (default, False)


def select_M1_for_compose(train_days, checkpoints, post_ts, maxn=250):
    """M7's internal daily-support M1: scored via -log(pmf[final]) (no brackets
    needed -- brackets belong to the 2-day/7-day WINDOW, not the daily sub-model)."""
    fit_pool, eval_pool = _cv_split(train_days)
    default = dict(n_bins=3, k=8, bw_frac=0.3)
    if len(fit_pool) < 10 or len(eval_pool) < 5:
        return default, False
    best = None
    for n_bins in (2, 3):
        state = M.fit_M1(fit_pool, checkpoints, post_ts, n_bins=n_bins)
        for k in (5, 15):
            for bw_frac in (0.25, 0.4):
                nlls = []
                for d in eval_pool:
                    for c in checkpoints:
                        if c * 3600 >= (d["e"] - d["s"]):
                            continue
                        o = L.obs_count(post_ts, d["s"], d["s"] + c * 3600)
                        pmf = M.predict_M1_pmf(state, c, o, k, bw_frac, maxn)
                        if pmf is None:
                            continue
                        idx = min(d["final"], len(pmf) - 1)
                        nlls.append(-math.log(max(pmf[idx], 1e-9)))
                _trial("M1_compose")
                if nlls and (best is None or np.mean(nlls) < best[0]):
                    best = (np.mean(nlls), dict(n_bins=n_bins, k=k, bw_frac=bw_frac))
    return (best[1], True) if best else (default, False)


def select_M2(train_units, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn):
    fit_pool, eval_pool = _cv_split(train_units)
    default = dict(K=4, ccp_alpha=0.0)
    if len(fit_pool) < 10 or len(eval_pool) < 5:
        return default, False
    all_finals = [u["final"] for u in fit_pool]
    best = None
    for K in (3, 4):
        edges = M.make_bin_edges(all_finals, K)
        # candidate ccp_alphas from the pruning path on the pooled fit_pool
        X, y = [], []
        for p in fit_pool:
            for c in checkpoints:
                if c * 3600 >= (p["e"] - p["s"]):
                    continue
                T = p["s"] + c * 3600
                _, feats = M.build_features(post_ts, is_qr, p["s"], T, prior_final_fn(p["s"]), trailing_fn(p["s"]))
                X.append(M.feat_vector(feats, M.FEATURE_NAMES))
                y.append(M.label_from_final(p["final"], edges))
        if len(X) < 30 or len(set(y)) < 2:
            continue
        from sklearn.tree import DecisionTreeClassifier
        base = DecisionTreeClassifier(max_depth=4, min_samples_leaf=25, random_state=0)
        try:
            path = base.cost_complexity_pruning_path(np.vstack(X), y)
            alphas = sorted(set(np.round(path.ccp_alphas[-6:], 5).tolist() + [0.0]))
        except Exception:
            alphas = [0.0]
        for alpha in alphas:
            state = M.fit_M2(fit_pool, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn,
                              edges, ccp_alpha=alpha)
            if state is None:
                continue
            losses = []
            for u in eval_pool:
                for c in checkpoints:
                    if c * 3600 >= (u["e"] - u["s"]):
                        continue
                    T = u["s"] + c * 3600
                    _, feats = M.build_features(post_ts, is_qr, u["s"], T, prior_final_fn(u["s"]), trailing_fn(u["s"]))
                    probs = M.predict_M2(state, feats, u["brackets"])
                    if probs is None:
                        continue
                    losses.append(L.log_loss_1(probs, u["winner"]))
            _trial("M2")
            if losses and (best is None or np.mean(losses) < best[0]):
                best = (np.mean(losses), dict(K=K, ccp_alpha=alpha))
    return (best[1], True) if best else (default, False)


def select_M3(train_days, post_ts):
    idx = int(len(train_days) * 0.7)
    fit_pool, eval_pool = train_days[:idx], train_days[idx:]
    default = 5
    if len(fit_pool) < 30 or len(eval_pool) < 10:
        return default, False
    best = None
    for k in (3, 4, 5, 6):
        cstate = M.fit_M3_centroids(fit_pool, post_ts, k)
        if cstate is None:
            continue
        pstate = M.fit_M3_state(cstate, fit_pool, post_ts)
        losses = []
        for d in eval_pool:
            for c in CHECKPOINTS_DAILY:
                T = d["s"] + c * 3600
                probs = M.predict_M3(pstate, post_ts, d["s"], T, DAILY_BRACKETS)
                if probs is None:
                    continue
                losses.append(L.log_loss_1(probs, DAILY_BRACKET_LOOKUP(d["final"])))
        _trial("M3")
        if losses and (best is None or np.mean(losses) < best[0]):
            best = (np.mean(losses), k)
    return (best[1], True) if best else (default, False)


def select_M4(train_units, post_ts):
    fit_pool, eval_pool = _cv_split(train_units)
    default = 3
    if len(fit_pool) < 8 or len(eval_pool) < 5:
        return default, False
    best = None
    for n_states in (2, 3, 4):
        state = M.fit_M4(fit_pool, post_ts, n_states)
        _trial("M4")
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


def _score_row(rows, target, handle, slug, dur, checkpoint, method, label, prob, market_p,
                is_winner, n_price_cov, n_price_tot):
    rows.append(dict(target=target, handle=handle, auction_slug=slug, dur=dur,
                      checkpoint_hours=checkpoint, method=method, bracket=label,
                      model_prob=prob, market_price=market_p, is_winner=int(is_winner),
                      price_coverage_n=n_price_cov, price_coverage_tot=n_price_tot))


def _emit(rows, target, handle, slug, dur, checkpoint, method, probs, brackets, winner,
          market_probs=None, n_cov=0, n_tot=0):
    if probs is None:
        return
    for label, _, _ in brackets:
        mp = (market_probs or {}).get(label) if market_probs else None
        _score_row(rows, target, handle, slug, dur, checkpoint, method, label,
                   probs.get(label, 1e-6), mp, label == winner, n_cov, n_tot)


def run_auction_target(target_name, handle, units, checkpoints, wall_ts, price_idx, dur_hours,
                        post_ts, is_qr, daily_series, maxn=500, maxn_day=250, n_sims=150,
                        ckpt_path=None, ckpt_every=10):
    """Targets 2-4: Elon 2-day (primary tradeable), Trump 7-day (independent
    confirmation), Elon 7-day (reported, thin). B4=market IS scored here --
    it is the only baseline that decides tradeability.

    ckpt_path (optional): mid-target resumability only (exec-sandbox process-
    lifetime limits, not science). Saves (rows, errh_B1, n_b4_avail, next_i)
    every ckpt_every auctions so a killed process resumes the SAME loop state
    -- errh_B1 is order-dependent (running error history feeds B1's sigma), so
    it is restored exactly, never recomputed from a different starting point.
    """
    for u in units:
        u["handle"] = handle
    train_units = [u for u in units if u["s"] < wall_ts]
    if len(train_units) < 10:
        print(f"[WARN] {target_name}: train_units={len(train_units)} too small, skipping target")
        return []
    prior_final_fn = make_prior_final_fn(units)
    trailing_fn = lambda T: daily_series.trailing_mean(T)
    n_days_total = int(round(dur_hours / 24))

    hp_M1, ok1 = select_M1(train_units, checkpoints, post_ts)
    hp_M2, ok2 = select_M2(train_units, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn)
    edges_M2 = M.make_bin_edges([u["final"] for u in train_units], hp_M2["K"])
    hp_M4, ok4 = select_M4(train_units, post_ts)
    hp_M5, ok5 = select_M5(train_units, post_ts, is_qr, trailing_fn, prior_final_fn)
    daily_train = [d for d in daily_series.days if d["s"] < wall_ts]
    hp_M1_daily, ok1d = select_M1_for_compose(daily_train, CHECKPOINTS_DAILY_COMPOSE, post_ts)
    print(f"[{target_name}] n_train={len(train_units)} n_total={len(units)} "
          f"M1={hp_M1}(cv={ok1}) M2={hp_M2}(cv={ok2}) M4_states={hp_M4}(cv={ok4}) M5={hp_M5}(cv={ok5}) "
          f"M1_daily(for M7)={hp_M1_daily}(cv={ok1d})")

    rows = []
    errh_B1 = {c: [] for c in checkpoints}
    n_b4_avail = 0
    start_i = 0
    if ckpt_path is not None and Path(ckpt_path).exists():
        import pickle
        with open(ckpt_path, "rb") as f:
            rows, errh_B1, n_b4_avail, start_i = pickle.load(f)
        print(f"  [{target_name}] resumed from mid-target checkpoint at auction {start_i}/{len(units)} "
              f"({len(rows)} rows already scored)")
    for i, u in enumerate(units):
        if i < start_i:
            continue
        priors = [p for p in units if p["e"] < u["s"]]
        if len(priors) < 4:
            continue
        brackets = u["brackets"]
        st_M1 = M.fit_M1(priors, checkpoints, post_ts, n_bins=hp_M1["n_bins"])
        st_M2 = M.fit_M2(priors, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn,
                          edges_M2, ccp_alpha=hp_M2["ccp_alpha"])
        st_M4 = M.fit_M4(priors, post_ts, hp_M4)
        st_M5 = M.fit_M5(priors, post_ts, is_qr, trailing_fn, prior_final_fn,
                          n_estimators=hp_M5["n_estimators"], max_depth=hp_M5["max_depth"])
        st_M6 = M.fit_M6(priors, post_ts, u["s"])
        daily_priors = daily_series.priors_before(u["s"])
        st_M1_daily = M.fit_M1(daily_priors, CHECKPOINTS_DAILY_COMPOSE, post_ts, n_bins=hp_M1_daily["n_bins"]) \
            if len(daily_priors) >= 10 else None
        st_M6_daily = M.fit_M6(daily_priors, post_ts, u["s"]) if len(daily_priors) >= 10 else None

        for c in checkpoints:
            if c * 3600 >= (u["e"] - u["s"]):
                continue
            T = u["s"] + c * 3600
            o = L.obs_count(post_ts, u["s"], T)
            eh, rh = c, dur_hours - c

            p_b1, proj_b1 = B1_probs(o, eh, rh, brackets, errh_B1[c])
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "B1", p_b1, brackets, u["winner"])
            errh_B1[c].append(abs(u["final"] - proj_b1))
            p_b2 = B2_probs(priors, brackets)
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "B2", p_b2, brackets, u["winner"])
            p_b3 = B3_probs(post_ts, u["s"], dur_hours, o, eh, rh, brackets)
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "B3", p_b3, brackets, u["winner"])
            mkt_probs, n_cov, n_tot = B4_probs(price_idx, u["slug"], brackets, T)
            if mkt_probs is not None:
                n_b4_avail += 1
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "B4", mkt_probs, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)

            p_m1 = M.predict_M1(st_M1, c, o, brackets, k=hp_M1["k"], bw_frac=hp_M1["bw_frac"])
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M1", p_m1, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)
            _, feats = M.build_features(post_ts, is_qr, u["s"], T, prior_final_fn(u["s"]), trailing_fn(u["s"]))
            p_m2 = M.predict_M2(st_M2, feats, brackets)
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M2", p_m2, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)
            p_m4 = M.predict_M4(st_M4, post_ts, u["s"], T, u["e"], brackets, maxn=maxn)
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M4", p_m4, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)
            p_m5 = M.predict_M5(st_M5, post_ts, is_qr, u["s"], T, u["e"], trailing_fn, prior_final_fn,
                                 brackets, n_sims=n_sims)
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M5", p_m5, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)
            p_m6 = M.predict_M6(st_M6, post_ts, u["s"], T, u["e"], brackets, n_sims=n_sims)
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M6", p_m6, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)

            # --- M7: compose the DAILY M1/M6 models up to this window's total ---
            # DST fix (audit 2026-07-31): day_idx/day_start re-anchored to noon ET
            # via add_days_et() -- the auction window itself (u["s"]/u["e"]) is
            # already correctly noon-ET anchored via noon_window(), but a fixed
            # `// 86400` / `* 86400` walk to find INTERIOR day boundaries within a
            # multi-day (7-day) window would drift by 1h on any window that spans
            # a DST transition date, same bug as DailySeries.
            day_idx = 0
            while add_days_et(u["s"], day_idx + 1) <= T:
                day_idx += 1
            day_start = add_days_et(u["s"], day_idx)
            hour_into_day = (T - day_start) / 3600.0
            grid_c = max([g for g in CHECKPOINTS_DAILY_COMPOSE if g <= hour_into_day], default=0)
            o_today = L.obs_count(post_ts, day_start, T)
            n_future_days = n_days_total - day_idx - 1
            if st_M1_daily is not None:
                today_pmf = M.predict_M1_pmf(st_M1_daily, grid_c, o_today, hp_M1_daily["k"],
                                              hp_M1_daily["bw_frac"], maxn_day)
                full_pmf = (M.predict_M1_pmf(st_M1_daily, 0, 0, hp_M1_daily["k"], hp_M1_daily["bw_frac"], maxn_day)
                            if n_future_days > 0 else None)
                window_pmf = M.compose_M7(today_pmf, o_today, full_pmf, n_future_days, o, maxn)
                p_m7_m1 = L.discrete_pmf_bracket_probs(0, window_pmf, brackets) if window_pmf is not None else None
            else:
                p_m7_m1 = None
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M7(M1)", p_m7_m1, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)
            if st_M6_daily is not None:
                day_end = add_days_et(u["s"], day_idx + 1)  # == add_days_et(day_start, 1)
                today_pmf6 = M.predict_M6_pmf(st_M6_daily, post_ts, day_start, T, day_end,
                                               maxn_day, n_sims=n_sims)
                next_day_start = day_end
                next_day_end = add_days_et(u["s"], day_idx + 2)
                full_pmf6 = (M.predict_M6_pmf(st_M6_daily, post_ts, next_day_start,
                                               next_day_start, next_day_end,
                                               maxn_day, n_sims=n_sims) if n_future_days > 0 else None)
                window_pmf6 = M.compose_M7(today_pmf6, o_today, full_pmf6, n_future_days, o, maxn)
                p_m7_m6 = L.discrete_pmf_bracket_probs(0, window_pmf6, brackets) if window_pmf6 is not None else None
            else:
                p_m7_m6 = None
            _emit(rows, target_name, handle, u["slug"], u["dur"], c, "M7(M6)", p_m7_m6, brackets, u["winner"],
                  market_probs=mkt_probs, n_cov=n_cov, n_tot=n_tot)
        if (i + 1) % 20 == 0:
            print(f"  [{target_name}] {i+1}/{len(units)} auctions scored")
        if ckpt_path is not None and (i + 1) % ckpt_every == 0:
            import pickle
            with open(ckpt_path, "wb") as f:
                pickle.dump((rows, errh_B1, n_b4_avail, i + 1), f)
    print(f"[{target_name}] B4-available auction-checkpoints: {n_b4_avail}")
    if ckpt_path is not None and Path(ckpt_path).exists():
        Path(ckpt_path).unlink()  # target finished cleanly -- the outer _run_checkpointed pickle is now authoritative
    return rows


def check_token_price_coverage(handle, units, price_idx):
    """MANDATORY pre-check (prereg item 5 / audit Pass-A): does the WINNING
    bracket actually have a price series? Report the coverage % explicitly --
    do not trust B4 comparisons before this is known."""
    n_missing = 0
    for u in units:
        vals = {label for label, _, _ in u["brackets"] if (u["slug"], label) in price_idx}
        if u["winner"] not in vals:
            n_missing += 1
    n = len(units)
    pct_missing = 100.0 * n_missing / n if n else float("nan")
    return dict(handle=handle, n=n, n_winner_missing=n_missing, pct_winner_missing=round(pct_missing, 1))


def build_targets():
    t0 = time.time()
    elon_post_ts, elon_is_qr = L.load_elon_posts()
    trump_post_ts, trump_is_qr = L.load_trump_posts()
    elon_auc = L.load_auctions("elonmusk")
    trump_auc = L.load_auctions("realDonaldTrump")
    elon_price = L.load_prices("elonmusk")
    trump_price = L.load_prices("realDonaldTrump")

    for u in elon_auc + trump_auc:
        u["final"] = L.obs_count(elon_post_ts if u["handle"] == "elonmusk" else trump_post_ts, u["s"], u["e"])

    elon_clean_start = int(pd.Timestamp("2025-09-01 12:00:00", tz=ET).timestamp())
    elon_clean_end = int(pd.Timestamp("2026-06-27 12:00:00", tz=ET).timestamp())
    trump_max_post = int(trump_post_ts.max())

    elon_2day = [u for u in elon_auc if u["dur"] == "2-day" and u["s"] >= elon_clean_start]
    elon_7day = [u for u in elon_auc if u["dur"] == "7-day" and u["s"] >= elon_clean_start]
    trump_7day = [u for u in trump_auc if u["dur"] == "7-day" and u["e"] <= trump_max_post]

    trump_7day_excluded = [u["slug"] for u in trump_auc if u["dur"] == "7-day" and u["e"] > trump_max_post]

    daily_elon = DailySeries(elon_post_ts, elon_clean_start, elon_clean_end)
    # DST fix (audit 2026-07-31): construct noon ET directly (year/month/day + hour=12)
    # instead of midnight-ET-timestamp + 12*3600 -- the old form is a fixed-seconds
    # step that would misland by 1h if trump_post_ts[0]'s calendar date happened to
    # be a DST transition date itself (defensive; astronomically unlikely to matter
    # given the actual first-post date, but the same class of bug as DailySeries).
    trump_day0_date = pd.Timestamp(trump_post_ts[0], unit="s", tz="UTC").tz_convert(ET).date()
    trump_day0 = int(pd.Timestamp(year=trump_day0_date.year, month=trump_day0_date.month,
                                   day=trump_day0_date.day, hour=12, tz=ET).timestamp())
    daily_trump = DailySeries(trump_post_ts, trump_day0, trump_max_post)

    cov = {
        "elon_2day": check_token_price_coverage("elonmusk", elon_2day, elon_price),
        "elon_7day": check_token_price_coverage("elonmusk", elon_7day, elon_price),
        "trump_7day": check_token_price_coverage("realDonaldTrump", trump_7day, trump_price),
    }
    print("=== TOKEN->PRICE COVERAGE CHECK (mandatory pre-check) ===")
    for k, v in cov.items():
        print(f"  {k}: n={v['n']}  winner_missing={v['n_winner_missing']} ({v['pct_winner_missing']}%)")
    print(f"  trump_7day auctions EXCLUDED for post-data gap (end > {pd.Timestamp(trump_max_post, unit='s', tz='UTC')}): "
          f"{len(trump_7day_excluded)} -> {trump_7day_excluded}")
    print(f"[load] {time.time()-t0:.1f}s")

    data = dict(
        elon_post_ts=elon_post_ts, elon_is_qr=elon_is_qr,
        trump_post_ts=trump_post_ts, trump_is_qr=trump_is_qr,
        elon_2day=sorted(elon_2day, key=lambda u: u["s"]),
        elon_7day=sorted(elon_7day, key=lambda u: u["s"]),
        trump_7day=sorted(trump_7day, key=lambda u: u["s"]),
        trump_7day_excluded=trump_7day_excluded,
        elon_price=elon_price, trump_price=trump_price,
        daily_elon=daily_elon, daily_trump=daily_trump,
        coverage=cov,
    )
    return data


def run_daily_target(post_ts, is_qr, daily_series, wall_ts, checkpoints=CHECKPOINTS_DAILY,
                      refit_block=7, maxn=300):
    """Target 1: Elon daily count, research substrate. Not tradeable (no B4).
    Feeds M7's daily decomposition. Refit cadence: weekly (see run notes)."""
    global DAILY_BRACKETS
    units = daily_series.days
    for u in units:
        u["handle"] = "elonmusk"
        u["brackets"] = DAILY_BRACKETS
        u["winner"] = DAILY_BRACKET_LOOKUP(u["final"])
    train_units = [u for u in units if u["s"] < wall_ts]
    if len(train_units) < 10:
        print(f"[WARN] elon_daily: train_units={len(train_units)} too small, skipping target")
        return []
    prior_final_fn = make_prior_final_fn(units)
    trailing_fn = lambda T: daily_series.trailing_mean(T)

    hp_M1, ok1 = select_M1(train_units, checkpoints, post_ts)
    hp_M2, ok2 = select_M2(train_units, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn)
    edges_M2 = M.make_bin_edges([u["final"] for u in train_units], hp_M2["K"])
    k_M3, ok3 = select_M3(train_units, post_ts)
    m3_centroids = M.fit_M3_centroids(train_units, post_ts, k_M3)
    hp_M4, ok4 = select_M4(train_units, post_ts)
    hp_M5, ok5 = select_M5(train_units, post_ts, is_qr, trailing_fn, prior_final_fn)
    print(f"[daily] M1={hp_M1}(cv={ok1}) M2={hp_M2}(cv={ok2}) M3_k={k_M3}(cv={ok3}) "
          f"M4_states={hp_M4}(cv={ok4}) M5={hp_M5}(cv={ok5})")

    rows = []
    errh_B1 = {c: [] for c in checkpoints}
    n = len(units)
    for block_start in range(0, n, refit_block):
        block = units[block_start:block_start + refit_block]
        if not block:
            continue
        priors = [u for u in units if u["e"] < block[0]["s"]]
        if len(priors) < 10:
            continue
        st_M1 = M.fit_M1(priors, checkpoints, post_ts, n_bins=hp_M1["n_bins"])
        st_M2 = M.fit_M2(priors, checkpoints, post_ts, is_qr, trailing_fn, prior_final_fn,
                          edges_M2, ccp_alpha=hp_M2["ccp_alpha"])
        st_M3 = M.fit_M3_state(m3_centroids, priors, post_ts)
        st_M4 = M.fit_M4(priors, post_ts, hp_M4)
        st_M5 = M.fit_M5(priors, post_ts, is_qr, trailing_fn, prior_final_fn,
                          n_estimators=hp_M5["n_estimators"], max_depth=hp_M5["max_depth"])
        st_M6 = M.fit_M6(priors, post_ts, block[0]["s"])

        for u in block:
            brackets = u["brackets"]
            for c in checkpoints:
                T = u["s"] + c * 3600
                o = L.obs_count(post_ts, u["s"], T)
                eh, rh = c, 24 - c
                p_b1, proj_b1 = B1_probs(o, eh, rh, brackets, errh_B1[c])
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "B1", p_b1, brackets, u["winner"])
                errh_B1[c].append(abs(u["final"] - proj_b1))
                p_b2 = B2_probs(priors, brackets)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "B2", p_b2, brackets, u["winner"])
                p_b3 = B3_probs(post_ts, u["s"], 24, o, eh, rh, brackets)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "B3", p_b3, brackets, u["winner"])
                p_m1 = M.predict_M1(st_M1, c, o, brackets, k=hp_M1["k"], bw_frac=hp_M1["bw_frac"])
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "M1", p_m1, brackets, u["winner"])
                _, feats = M.build_features(post_ts, is_qr, u["s"], T, prior_final_fn(u["s"]), trailing_fn(u["s"]))
                p_m2 = M.predict_M2(st_M2, feats, brackets)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "M2", p_m2, brackets, u["winner"])
                p_m3 = M.predict_M3(st_M3, post_ts, u["s"], T, brackets)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "M3", p_m3, brackets, u["winner"])
                p_m4 = M.predict_M4(st_M4, post_ts, u["s"], T, u["e"], brackets, maxn=maxn)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "M4", p_m4, brackets, u["winner"])
                p_m5 = M.predict_M5(st_M5, post_ts, is_qr, u["s"], T, u["e"], trailing_fn, prior_final_fn, brackets)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "M5", p_m5, brackets, u["winner"])
                p_m6 = M.predict_M6(st_M6, post_ts, u["s"], T, u["e"], brackets)
                _emit(rows, "elon_daily", "elonmusk", u["slug"], "1-day", c, "M6", p_m6, brackets, u["winner"])
    return rows


def select_M5(train_units, post_ts, is_qr, trailing_fn, prior_final_fn):
    fit_pool, eval_pool = _cv_split(train_units)
    default = dict(n_estimators=80, max_depth=2)
    if len(fit_pool) < 8 or len(eval_pool) < 5:
        return default, False
    best = None
    for n_estimators, max_depth in ((50, 2), (100, 3)):
        state = M.fit_M5(fit_pool, post_ts, is_qr, trailing_fn, prior_final_fn,
                          n_estimators=n_estimators, max_depth=max_depth)
        _trial("M5")
        if state is None:
            continue
        Xs, ys = [], []
        for p in eval_pool[:15]:
            X, y = M._interval_table(p, post_ts, is_qr, trailing_fn, prior_final_fn)
            if X is None:
                continue
            Xs.append(X)
            ys.append(y)
        if not Xs:
            continue
        X = np.vstack(Xs)
        y = np.concatenate(ys)
        proba = np.clip(state["clf"].predict_proba(X)[:, 1], 1e-6, 1 - 1e-6)
        ll = -np.mean(y * np.log(proba) + (1 - y) * np.log(1 - proba))
        if best is None or ll < best[0]:
            best = (ll, dict(n_estimators=n_estimators, max_depth=max_depth))
    return (best[1], True) if best else (default, False)


# ---------------------------------------------------------------------------
# Aggregation: skill vs baselines, block bootstrap by auction (by week for the
# daily substrate), single-outlier jackknife. n_eff = distinct resolved
# auctions/days, never ticks/checkpoints/brackets.
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


def compute_skill_table(df, target, block_size, span):
    """Audit fix (pattern_discovery_2026-07-26.md Finding 1, FATAL/BLOCK): a
    (auction, checkpoint) is admissible for a B4 (market) comparison ONLY if the
    WINNING bracket itself had a real market price at T. B4's own model_prob
    defaults missing brackets to 1e-6 (kept as-is for B4's own logloss/brier so
    non-B4 comparisons are untouched), but that default must NEVER be trusted as
    "the market said the winner was ~0%" -- it means the market was never
    queried. Gate every B4-vs-method pair on the pre-computed `b4_admissible`
    column (df-level, derived from B4's own winner-row market_price before this
    function runs) and drop the SAME rows from both sides of the pair so they
    stay matched. Non-B4 comparisons (vs B1/B2/B3) are unaffected and keep the
    full sample.
    """
    sub = df[(df.target == target) & (df.span == span)]
    if sub.empty:
        return None
    winner_rows = sub[sub.is_winner == 1].copy()
    winner_rows["logloss"] = -np.log(np.clip(winner_rows.model_prob, 1e-9, 1.0))
    sq = (sub.model_prob - sub.is_winner) ** 2
    brier = sub.assign(sq=sq).groupby(["auction_slug", "checkpoint_hours", "method"])["sq"].sum().rename("brier")
    per = winner_rows.merge(brier, on=["auction_slug", "checkpoint_hours", "method"], how="left")
    piv_ll = per.pivot_table(index=["auction_slug", "checkpoint_hours"], columns="method", values="logloss")
    piv_br = per.pivot_table(index=["auction_slug", "checkpoint_hours"], columns="method", values="brier")
    # mean-over-checkpoints per auction (unit-level statistic for bootstrap/jackknife)
    ll_unit = piv_ll.groupby(level=0).mean()
    n_auctions = ll_unit.shape[0]

    admissible_keys = (winner_rows[(winner_rows.method == "B4") & (winner_rows.b4_admissible)]
                       .set_index(["auction_slug", "checkpoint_hours"]).index)
    piv_ll_b4 = piv_ll[piv_ll.index.isin(admissible_keys)]
    ll_unit_b4 = piv_ll_b4.groupby(level=0).mean()
    n_auctions_b4_admissible = ll_unit_b4.shape[0]

    out = {}
    for baseline in ("B1", "B2", "B3", "B4"):
        if baseline not in ll_unit.columns:
            continue
        use_unit = ll_unit_b4 if baseline == "B4" else ll_unit
        for method in use_unit.columns:
            if method == baseline:
                continue
            pair = use_unit[[baseline, method]].dropna()
            if pair.empty:
                continue
            skill = (pair[baseline] - pair[method]).to_numpy()  # positive = method beats baseline
            ci = block_bootstrap_ci(skill, block_size=block_size)
            jk = jackknife_drop_best(skill)
            out[(method, baseline)] = dict(
                n_auctions=int(len(pair)), mean_logloss_method=float(pair[method].mean()),
                mean_logloss_baseline=float(pair[baseline].mean()),
                skill_mean=ci["mean"], ci_lo=ci["lo"], ci_hi=ci["hi"],
                jk_full=jk["full_mean"], jk_dropbest=jk["dropbest_mean"], jk_sign_holds=jk["sign_holds"],
            )
    return dict(n_auctions_total=n_auctions, n_auctions_b4_admissible=n_auctions_b4_admissible,
                skill=out, brier_mean=piv_br.mean(axis=0).to_dict(),
                logloss_mean=ll_unit.mean(axis=0).to_dict())


def compute_excluded_subset_skill(df, target, block_size, span):
    """Disclosure ONLY (audit 2026-07-29, Finding A [CLASS D] MEDIUM, non-fatal):
    quantifies model-vs-B1 skill separately for (a) auctions with at least one
    B4-admissible checkpoint (the subset the PRIMARY/B4 headline is actually
    scored on) vs (b) auctions where the market NEVER priced the winner at ANY
    tested checkpoint (fully inadmissible -- unreachable by the B4 test by
    construction, since there is no market price to score a probability
    against). This is NOT a finding of edge on the excluded subset: a wider
    naive-vs-model gap there may simply reflect that unpriced brackets are
    structurally easier to forecast (thin/extreme/low-variance), not that a
    tradeable edge exists where the market can't be tested. Reported so the
    headline "no tradeable edge" is read with its correct scope (the
    admissible subset only) instead of silently generalizing to auctions the
    study cannot actually evaluate for tradeability.
    """
    sub = df[(df.target == target) & (df.span == span)]
    if sub.empty:
        return None
    winner_rows = sub[sub.is_winner == 1].copy()
    winner_rows["logloss"] = -np.log(np.clip(winner_rows.model_prob, 1e-9, 1.0))
    piv_ll = winner_rows.pivot_table(index=["auction_slug", "checkpoint_hours"], columns="method", values="logloss")
    ll_unit = piv_ll.groupby(level=0).mean()

    admissible_keys = (winner_rows[(winner_rows.method == "B4") & (winner_rows.b4_admissible)]
                       .set_index(["auction_slug", "checkpoint_hours"]).index)
    admissible_auctions = set(k[0] for k in admissible_keys)
    excluded_auctions = set(ll_unit.index) - admissible_auctions

    out = {}
    for group_name, auctions in (("admissible", admissible_auctions), ("excluded", excluded_auctions)):
        grp = ll_unit.loc[ll_unit.index.isin(auctions)]
        row = dict(n_auctions=int(grp.shape[0]),
                   b1_logloss_mean=float(grp["B1"].mean()) if ("B1" in grp.columns and not grp.empty) else float("nan"),
                   vs_b1={})
        if not grp.empty and "B1" in grp.columns:
            for method in grp.columns:
                if method in ("B1", "B4"):
                    continue
                pair = grp[["B1", method]].dropna()
                if pair.empty:
                    continue
                skill = (pair["B1"] - pair[method]).to_numpy()  # positive = method beats naive B1
                row["vs_b1"][method] = block_bootstrap_ci(skill, block_size=block_size)
        out[group_name] = row
    return out


def r2_null_check(post_ts, day0, day_end):
    """Verify the prereg's declared null: at hour 18/21 of a 1-day window,
    count_so_far alone already explains most of the final-count variance.
    DST fix (audit 2026-07-31): day boundaries re-anchored to noon ET via
    add_days_et() each iteration (same bug/fix as DailySeries). The intra-day
    +18h/+21h offsets stay fixed-second elapsed-time additions from the
    correctly-anchored day start -- consistent with the elapsed-hours
    checkpoint convention used everywhere else in this file
    (T = window_start + c*3600), not a wall-clock-hour convention."""
    finals, o18, o21 = [], [], []
    i = 0
    while True:
        d = add_days_et(day0, i)
        e = add_days_et(day0, i + 1)
        if e > day_end:
            break
        f = L.obs_count(post_ts, d, e)
        finals.append(f)
        o18.append(L.obs_count(post_ts, d, d + 18 * 3600))
        o21.append(L.obs_count(post_ts, d, d + 21 * 3600))
        i += 1
    finals = np.array(finals, dtype=float)
    out = {}
    for name, o in (("hour18", o18), ("hour21", o21)):
        o = np.array(o, dtype=float)
        if o.std() == 0 or finals.std() == 0:
            out[name] = float("nan")
            continue
        r = np.corrcoef(o, finals)[0, 1]
        out[name] = float(r ** 2)
    return out


def _headline_flag(results, target, baseline):
    sealed = results.get(target, {}).get("sealed")
    if not sealed:
        return "no_sealed_data"
    # Audit fix (re-audit #2, Finding 2): gate on the n the comparison was
    # actually scored on (B4 pairs use the admissible n; B1/B3 pairs use the
    # full n) BEFORE returning a bare method list -- a positive flag below
    # SUCCESS_N_FLOOR is a mathematical artifact of too few auctions, not a
    # green light. See SUCCESS_N_FLOOR's definition for the justification.
    n_for_gate = sealed["n_auctions_b4_admissible"] if baseline == "B4" else sealed["n_auctions_total"]
    if n_for_gate < SUCCESS_N_FLOOR:
        return f"noise (n={n_for_gate}, below admissible floor of {SUCCESS_N_FLOOR})"
    hits = []
    for (method, base), stat in sealed["skill"].items():
        if base == baseline and stat["ci_lo"] > 0:
            hits.append(method)
    return hits if hits else "none"


def compute_elon_activity_shift(daily_elon, wall_ts):
    """Disclosure ONLY (audit 2026-07-31, undisclosed TRAIN/SEALED base-rate
    shift, found while auditing the sibling regime_discovery study). Computed
    independently here from THIS script's own daily_elon series + WALL (not
    copied from regime_discovery_2026-07-29.py) so the figure matches exactly
    what this study's own train/sealed split saw. TRAIN-frozen tercile cuts
    (33rd/67th percentile of TRAIN daily finals) are then applied to BOTH
    spans to show how a threshold frozen on TRAIN misclassifies SEALED's
    quieter regime by construction. Purely informational: feeds no model,
    hyperparameter, bin edge, or success gate used anywhere else in this file."""
    train_finals = np.array([d["final"] for d in daily_elon.days if d["s"] < wall_ts], dtype=float)
    sealed_finals = np.array([d["final"] for d in daily_elon.days if d["s"] >= wall_ts], dtype=float)
    if len(train_finals) == 0 or len(sealed_finals) == 0:
        return None
    lo_cut, hi_cut = np.quantile(train_finals, [1 / 3, 2 / 3])
    return dict(
        n_train=len(train_finals), n_sealed=len(sealed_finals),
        mean_train=float(train_finals.mean()), mean_sealed=float(sealed_finals.mean()),
        low_cut=float(lo_cut), high_cut=float(hi_cut),
        pct_low_train=100.0 * float((train_finals <= lo_cut).mean()),
        pct_low_sealed=100.0 * float((sealed_finals <= lo_cut).mean()),
    )


def write_summary(df, results, data, null_check, excluded_subset):
    lines = []
    lines.append("# Pattern Discovery -- Post-Cadence Study (2026-07-26)")
    lines.append("")
    lines.append("Pre-registration: `_DataMetricPulls/pacing_backtest/prereg/pattern_discovery_2026-07-26.md`. "
                 "Scope: (b) pure forecast-accuracy / calibration diagnostic. No P&L, no fills. "
                 "This is a hypothesis, not a certified result -- hand off to @backtest-auditor.")
    lines.append("")
    lines.append("## ⚠️ Undisclosed TRAIN/SEALED activity shift (audit 2026-07-31 -- read this before any "
                 "headline below)")
    shift = compute_elon_activity_shift(data["daily_elon"], WALL_ELON)
    if shift:
        lines.append(f"- Elon's daily posting rate dropped materially across the WALL: mean daily posts "
                     f"**{shift['mean_train']:.1f}** on TRAIN (n={shift['n_train']} days) versus "
                     f"**{shift['mean_sealed']:.1f}** on SEALED (n={shift['n_sealed']} days).")
        lines.append(f"- TRAIN-frozen tercile cuts (LOW <= {shift['low_cut']:.1f} posts/day, HIGH > "
                     f"{shift['high_cut']:.1f}, computed on TRAIN only) classify **{shift['pct_low_sealed']:.1f}%** "
                     f"of SEALED days LOW versus **{shift['pct_low_train']:.1f}%** of TRAIN days.")
        lines.append("- This is legitimate wall behaviour, not a bug -- Elon simply posted less after the WALL "
                     "date. But it means every sealed-span number in this report was measured in a much quieter "
                     "posting regime than the one every model, baseline, and TRAIN-frozen bin/quantile edge "
                     "(including this study's own `DAILY_BRACKETS`, `M2` bin edges, and hyperparameter-selection "
                     "holdouts) was fit on. A threshold frozen on TRAIN will misclassify a quieter SEALED period "
                     "by construction. Read every 'no tradeable edge' / 'unproven' verdict below with this regime "
                     "shift in mind -- it is a reason for caution about what SEALED represents, not evidence the "
                     "models themselves are broken.")
    else:
        lines.append("- Could not compute (insufficient TRAIN or SEALED daily data).")
    lines.append("")
    lines.append("## Token -> price coverage (mandatory pre-check)")
    for k, v in data["coverage"].items():
        lines.append(f"- **{k}**: n={v['n']}, winner bracket missing from canonical/prices for "
                      f"{v['n_winner_missing']} auctions ({v['pct_winner_missing']}%)")
    lines.append(f"- trump_7day auctions excluded for post-data gap (posts stop {pd.Timestamp(int(data['trump_post_ts'].max()), unit='s', tz='UTC')}): "
                 f"{len(data['trump_7day_excluded'])} of 51 -> {data['trump_7day_excluded']}")
    lines.append("- **Historical note, resolved 2026-07-30:** when this study was first run, the winner-bracket "
                 "price was missing for 63.6% of elon_2day auctions and 78.2% of elon_7day auctions (trump_7day "
                 "was 0.0% missing throughout) -- far worse than the historically-quoted ~27% (that figure was "
                 "measured on a smaller, 22-auction pmxt-covered subset). The gap was Elon-specific, did not "
                 "correlate with the winner being an extreme/thin bracket (median winner rank was mid-pack, not "
                 "edge), and `confidence=='high'` was NOT a reliable filter for Elon price completeness -- likely "
                 "`03_build_auctions.py` re-running after `08_normalize_bucket_labels.py`'s demotion pass "
                 "silently reverted the demotions. That gap is why the earlier admissible-n figures behind this "
                 "study's headline were elon_2day=19, trump_7day=20 (unaffected), elon_7day=3, rather than the "
                 "current 27/20/19. A canonical/prices rebuild on 2026-07-30 12:36 (separate work, external to "
                 "this script) fixed the gap. **Current state, this run: coverage is 0.0% missing on all three "
                 "targets** (see the three lines directly above), independently re-verified against the raw "
                 "canonical/prices parquet directly for the 2026-07-31 audit round, not merely trusted from this "
                 "script's own self-report. Any B4 comparison below is scored ONLY on auction-checkpoints where "
                 "the winner's own price exists; read the coverage % as the effective sample shrinkage on the "
                 "primary/secondary success criteria.")
    lines.append("")
    lines.append("## B4 admissibility fix (audit 2026-07-29, Finding 1, FATAL/BLOCK -- corrected in this run)")
    b4_winner_mask = (df.method == "B4") & (df.is_winner == 1)
    n_b4_winner_rows = int(b4_winner_mask.sum())
    n_inadmissible = int((~df.loc[b4_winner_mask, "b4_admissible"]).sum())
    lines.append(f"- The prior run defaulted a missing winner price to 1e-6 and scored -log(1e-6) against it, "
                 f"inflating B4's apparent log loss whenever the winning bracket itself had no price at "
                 f"decision time T. This run instead EXCLUDES that (auction, checkpoint) from every B4 "
                 f"comparison entirely (both sides of the pair, so they stay matched) via the `b4_admissible` "
                 f"boolean column persisted in `per_row.csv`. Non-B4 comparisons (vs B1/B2/B3) are untouched "
                 f"and keep the full sample.")
    lines.append(f"- Of {n_b4_winner_rows} (target, auction, checkpoint) rows where B4 had a winner-row at all, "
                 f"{n_inadmissible} ({100.0*n_inadmissible/n_b4_winner_rows:.1f}%) are inadmissible (winner "
                 f"never priced at T) and are dropped from every B4 pair below, not defaulted.")
    lines.append("- Every headline line below reports TWO different n's: `n_auctions_full` (used for B1/B2/B3 "
                 "pairs) and `n_auctions_b4_admissible` (used for B4 pairs specifically, always <= the full n). "
                 "Do not conflate them.")
    lines.append("")
    lines.append(f"## Null-model check (prereg verification)\nR2(count_so_far -> final count), Elon daily: "
                 f"hour18={null_check['hour18']:.3f}, hour21={null_check['hour21']:.3f} "
                 f"(prereg declared 0.76 / 0.93 -- {'CONFIRMED, same order of magnitude' if null_check['hour18'] > 0.5 else 'NOT reproduced, investigate'}).")
    lines.append("")
    lines.append("## DST window-drift fix (audit 2026-07-31)")
    lines.append("A five-site DST/day-boundary bug was found while auditing a sibling regime study and confirmed "
                 "to also affect this script. Before the fix, day-boundary anchors built by absolute-duration "
                 "arithmetic (`+ Timedelta(hours=24)` / `+ 86400s`) drifted by exactly one hour during US "
                 "standard time, landing on **11:00 ET instead of noon ET** for every TRAIN-span day inside the "
                 "drift window. Independently re-derived, not trusted from the description: exactly 126 of 285 "
                 "daily anchors for the elon_daily target differ between the pre-fix and post-fix runs, all by "
                 "exactly +3600s, spanning **2025-11-02 to 2026-03-07** (the 2025-2026 US DST-standard-time "
                 "window, fall-back to spring-forward) -- 0 drifted anchors remain after the fix.")
    lines.append("")
    lines.append("Fixed sites (5, all now route through the same `add_days_et()` calendar-aware helper -- "
                 "`pd.Timestamp(...).tz_convert(ET) + pd.DateOffset(days=n)`, wall-clock-preserving across both "
                 "transition dates):")
    lines.append("1. `DailySeries` -- the per-day activity series every trailing/prior-window feature reads")
    lines.append("2. `r2_null_check` -- the prereg's own R2 null-model verification (see below)")
    lines.append("3. `run_auction_target`'s M7 daily decomposition (day_idx/day_start/day_end/next_day_end)")
    lines.append("4. `build_targets`'s Trump day-zero anchor -- a defensive fix only: this anchor was already "
                 "built via a direct single-instant `pd.Timestamp(year=,month=,day=,hour=12,tz=ET)` construction "
                 "rather than an accumulated walk, so it was never actually exposed to this bug class")
    lines.append("5. `pattern_discovery_methods.py:282` -- M3's within-day remaining-count feature, "
                 "`d[\"s\"] + 86400` changed to `d[\"e\"]` (the `DailySeries`-defined, DST-aware day end)")
    lines.append("")
    lines.append("**Why it mattered despite SEALED windows not being drifted themselves:** the TRAIN span "
                 "contains all 126 drifted days, so every frozen artefact fit on TRAIN -- bin edges, terciles, "
                 "CV-selected hyperparameters, cluster centroids, HMM parameters -- was fit on misaligned "
                 "(11:00 ET) windows, then applied to correctly-aligned (noon ET) SEALED data.")
    lines.append("")
    lines.append("**Measured effect, isolated from the coverage repair above (separate diff):** on the three "
                 "auction-scored targets (elon_2day, trump_7day, elon_7day), 32,132 model_prob rows changed "
                 "across **M2 (5,017 rows, up to 0.39 abs diff), M5 (2,296 rows, up to 0.59), M6 (8,076 rows, up "
                 "to 0.14), M7(M1) (7,791 rows, up to 0.07), M7(M6) (8,952 rows, up to 0.17)**. A further 2,671 "
                 "rows changed on elon_daily, 100% M3 (the standalone `pattern_discovery_methods.py:282` fix, "
                 "isolated in its own diff). The true magnitude range across the full DST-fix diff is **up to "
                 "0.76 on the TRAIN span / 0.59 on SEALED** -- an earlier informal characterization of this diff "
                 "as \"only M6/M7 moved, by 0.003-0.17\" was inaccurate on both the method list and the magnitude "
                 "and is corrected here. **B1, B2, B3, M1 and M4 were unchanged (bit-identical) on the auction "
                 "targets** -- they do not consume `trailing_fn`/`prior_final_fn` (B1 uses o/eh/rh plus its own "
                 "error history; M1 is an empirical table on c,o; M4 is an hourly-count HMM; B3 is `locked_pace`; "
                 "B4 is the market price), while M2 and M5 consume those `DailySeries`-derived features directly "
                 "as declared prereg inputs, and M6/M7/M3 are themselves built directly from `DailySeries`/"
                 "`add_days_et` day-boundaries.")
    lines.append("")
    lines.append(f"**The R2 null check itself moved**, as a direct consequence of being one of the 5 fixed "
                 f"sites: hour18 0.764 -> {null_check['hour18']:.3f}, hour21 0.856 -> {null_check['hour21']:.3f} "
                 f"(the \"Null-model check\" section above already reports the corrected figures -- this note "
                 f"records that they moved, and why, since this figure is the benchmark other work in this repo "
                 f"has been judged against).")
    lines.append("")
    lines.append("**No PRIMARY 'beats B4' verdict changed as a result of this fix.** All three remained 'none' "
                 "before and after -- the coverage repair above, not this DST fix, is what moved elon_7day "
                 "sealed from an n=3 noise-gated sentinel to a real n=19 test. Verified deterministic and "
                 "complete: two independently-triggered cold runs post-fix reproduce a byte-identical "
                 "`per_row.csv` (MD5 match), `summary.md`, and RUN_META; all 5 declared sites were re-grepped "
                 "for any remaining `86400`/`Timedelta(days`/`Timedelta(hours` day-boundary construction and "
                 "none were found (the study's own noon-ET slug parser, `pattern_discovery_lib.py`, was never "
                 "exposed to this bug class and was not touched).")
    lines.append("")
    lines.append("## Headline: skill vs each baseline, TRAIN vs SEALED span")
    lines.append("Skill = baseline_logloss - method_logloss, mean over checkpoints then block-bootstrapped BY "
                 "AUCTION (by week for elon_daily). Positive = method beats baseline. CI including zero = unproven.")
    for target in ("elon_daily", "elon_2day", "trump_7day", "elon_7day"):
        lines.append(f"\n### {target}")
        for span in ("train", "sealed"):
            res = results[target][span]
            if res is None:
                lines.append(f"- **{span}**: no data")
                continue
            lines.append(f"- **{span}** (n_auctions_full={res['n_auctions_total']}, "
                         f"n_auctions_b4_admissible={res['n_auctions_b4_admissible']})")
            for (method, baseline), stat in sorted(res["skill"].items()):
                sig = "BEATS" if stat["ci_lo"] > 0 else ("LOSES" if stat["ci_hi"] < 0 else "unproven (CI incl. 0)")
                jk = "sign holds" if stat["jk_sign_holds"] else ("SIGN FLIPS on dropping best auction" if stat["jk_sign_holds"] is False else "n/a")
                lines.append(f"  - {method} vs {baseline}: skill={stat['skill_mean']:+.4f} "
                             f"CI[{stat['ci_lo']:+.4f},{stat['ci_hi']:+.4f}] n={stat['n_auctions']} -> {sig}; jackknife: {jk}")
    lines.append("")
    lines.append("## Success criteria verdict (fixed by prereg, not movable)")
    lines.append(f"**Reporting floor (audit 2026-07-29, re-audit #2, Finding 2):** any PRIMARY/SECONDARY/TERTIARY "
                 f"line below whose comparison was scored on fewer than {SUCCESS_N_FLOOR} admissible auctions is "
                 f"printed as an explicit `noise (n=..., below admissible floor of {SUCCESS_N_FLOOR})` sentinel "
                 f"instead of a bare method list, in both this file and RUN_META -- this implements the prereg's "
                 f"own existing rule (CI including zero => unproven; n<10 => noise) as a structural gate rather "
                 f"than prose a reader could miss. The full skill/CI/jackknife numbers are never hidden -- see "
                 f"the per-baseline table in the 'Headline' section above for the raw values behind any gated line.")
    for target in ("elon_2day", "trump_7day", "elon_7day"):
        sealed = results[target]["sealed"]
        lines.append(f"\n### {target} (sealed span only -- the only accepted multiple-testing gate)")
        if sealed is None:
            lines.append("- no sealed-span data")
            continue
        lines.append(f"- n_auctions_full={sealed['n_auctions_total']}, "
                     f"n_auctions_b4_admissible={sealed['n_auctions_b4_admissible']} "
                     f"(the B4/PRIMARY line below is scored on the admissible n only)")
        for baseline, tag in (("B4", "PRIMARY (tradeable)"), ("B3", "SECONDARY"), ("B1", "TERTIARY")):
            n_for_gate = sealed["n_auctions_b4_admissible"] if baseline == "B4" else sealed["n_auctions_total"]
            winners = [m for (m, b), s in sealed["skill"].items() if b == baseline and s["ci_lo"] > 0]
            losers_all = [m for (m, b), s in sealed["skill"].items() if b == baseline and s["ci_hi"] < 0]
            if n_for_gate < SUCCESS_N_FLOOR:
                lines.append(f"- {tag} beats {baseline}: noise (n={n_for_gate}, below admissible floor of "
                             f"{SUCCESS_N_FLOOR}) -- see the per-baseline skill/CI/jackknife table above for "
                             f"the raw numbers; not a usable signal at this n.")
            else:
                lines.append(f"- {tag} beats {baseline}: {winners if winners else 'NONE'}"
                             + (f" (all methods lose to {baseline})" if not winners and len(losers_all) > 0 else ""))
        if sealed["n_auctions_b4_admissible"] < 15:
            lines.append(f"- **B4/PRIMARY comparison is statistically thin**: only "
                         f"{sealed['n_auctions_b4_admissible']} admissible auctions after excluding "
                         f"unpriced-winner checkpoints -- treat the PRIMARY line above as too small to call, "
                         f"not a code defect.")
        b4_winners = [m for (m, b), s in sealed["skill"].items() if b == "B4" and s["ci_lo"] > 0]
        b1_winners = [m for (m, b), s in sealed["skill"].items() if b == "B1" and s["ci_lo"] > 0]
        n_full = sealed["n_auctions_total"]
        n_adm = sealed["n_auctions_b4_admissible"]
        pct_adm = f"{100.0*n_adm/n_full:.0f}%" if n_full else "n/a"
        # Audit fix (Finding A, MEDIUM): scope the headline sentence itself to the
        # admissible subset it was actually tested on -- do not let "no tradeable
        # edge" read as an unqualified claim about every auction in the target.
        scope = (f"scored on the {n_adm} of {n_full} {target} sealed-span auctions the market actually "
                 f"priced the winning bracket in ({pct_adm}) -- see 'Excluded-subset disclosure' below for "
                 f"the other {n_full - n_adm}, which this test cannot evaluate for tradeability at all")
        if not b4_winners and b1_winners:
            lines.append(f"- **NO TRADEABLE EDGE** ({scope}): {b1_winners} beat B1/naive but none beat "
                         f"B4/market. Reported plainly per prereg -- this is a valid, expected outcome, not a "
                         f"failure to fix.")
        elif not b4_winners:
            lines.append(f"- **NO TRADEABLE EDGE** ({scope}), and no method beats even the naive baseline "
                         f"either.")
    lines.append("")
    lines.append("## Excluded-subset disclosure (OPEN QUESTION -- NOT a finding; audit 2026-07-29, Finding A)")
    lines.append("The B4/PRIMARY comparison above is scored ONLY on auctions where the market actually priced "
                 "the winning bracket at some tested checkpoint. This section quantifies the auctions it "
                 "excludes (the market NEVER priced the winner at ANY tested checkpoint for that auction) "
                 "instead of leaving the headline silent on them. **This is not a positive result and must not "
                 "be read as one**: there is no market price to score a 'beats B4' claim against on these "
                 "auctions, so B4/PRIMARY is fundamentally untestable there, not merely unproven. A wider "
                 "model-vs-naive gap on the excluded subset may simply mean unpriced brackets are structurally "
                 "easier to forecast (thin, extreme, or low-variance -- exactly the brackets a market maker has "
                 "least reason to quote), not that a tradeable edge exists. Whether these auctions were "
                 "genuinely untraded by the market or merely unrecorded in canonical/prices is UNRESOLVED and "
                 "material to that question, and this study cannot resolve it with the data on hand.")
    for target in ("elon_2day", "elon_7day"):
        ex = excluded_subset.get(target)
        if not ex:
            lines.append(f"\n### {target} (sealed span) -- no data")
            continue
        lines.append(f"\n### {target} (sealed span)")
        for group_name, label in (("admissible", "admissible (used for the PRIMARY/B4 headline above)"),
                                   ("excluded", "excluded (winner never priced by the market -- untestable vs B4)")):
            g = ex.get(group_name) or {}
            n_a = g.get("n_auctions", 0)
            b1ll = g.get("b1_logloss_mean", float("nan"))
            lines.append(f"- **{group_name}** ({label}): n_auctions={n_a}, B1 (naive) raw logloss={b1ll:.3f}")
            for method, ci in sorted((g.get("vs_b1") or {}).items()):
                sig = "BEATS naive" if ci["lo"] > 0 else ("LOSES to naive" if ci["hi"] < 0 else "unproven (CI incl. 0)")
                lines.append(f"    - {method} vs B1: skill={ci['mean']:+.4f} CI[{ci['lo']:+.4f},{ci['hi']:+.4f}] "
                             f"n={ci['n']} -> {sig}")
    lines.append("")
    lines.append("## Per-method estimator disclosure (what was actually fit)")
    lines.append("""
- **M1** (empirical conditional table): nonparametric mixture-of-Gaussians over historical remaining-count
  samples, cell = count_so_far quantile bin (n_bins in {2,3}) at this checkpoint, shrunk toward climatology
  via pseudo-count k in {5,15}; bandwidth = frac*std(climatology), frac in {0.25,0.4}. Hyperparameters chosen
  by a 70/30 CHRONOLOGICAL holdout within TRAIN only (fit on first 70% of train units, scored on last 30%,
  both ends strictly before the WALL) -- a disclosed simplification of a full walk-forward grid search, done
  to keep the sweep tractable; still 100% causal.
- **M2** (CART): real `sklearn.tree.DecisionTreeClassifier`, max_depth=4, min_samples_leaf=25 (prereg caps,
  never exceeded), predicting a quantile-bin-of-final-count label (K in {3,4}); ccp_alpha chosen from the
  tree's own `cost_complexity_pruning_path` via the same train-only holdout. Within-bin bracket probabilities
  come from a Gaussian-smoothed empirical density of historical final counts in that bin.
- **M3** (day-shape clustering, DAILY TARGET ONLY -- not applicable to 2-day/7-day by construction, a 24-dim
  shape vector doesn't generalize to a 48h/168h window): real `sklearn.cluster.KMeans`, k in {3,4,5,6} (within
  the prereg's 3..8 cap), selected via train-only chronological holdout. Centroids fit on TRAIN ONLY and
  FROZEN per the prereg's explicit instruction for M3 specifically (unlike the other methods' walk-forward
  refit allowance); only the per-cluster remaining-count pools are refreshed walk-forward.
- **M4** (HMM): real `hmmlearn.hmm.PoissonHMM`, n_components in {2,3,4} (prereg's 2-4 cap), selected via
  train-only chronological holdout log-likelihood. Refit per decision-unit (or per week for elon_daily) on
  up to the last 40 prior sequences (bounded for tractability). Forecast = state posterior at T (via
  `.score_samples`, causal since it only sees the sequence up to T) propagated forward through the fitted
  transition matrix, hour-by-hour Poisson-mixture PMF convolved to a total. Convergence (`monitor_.converged`)
  is tracked per fit; non-converged/failed fits emit no prediction for that row rather than a fabricated one.
- **M5** (discrete-time hazard): real `sklearn.ensemble.GradientBoostingClassifier` fit on a 15-minute
  interval-expanded person-period table (P(post in next 15 min)), using a REDUCED covariate set
  (count_so_far, hours_into_window, posts_last_1h/3h/6h, dow, et_hour, prior_window_final, trailing_7d_mean,
  share_qr) -- median/longest/variance-gap and max_posts_60min were dropped from this specific model only,
  because computing them at every 15-min boundary for every prior auction is O(n^2) and intractable at this
  n; every other declared feature is present. n_estimators in {50,100}, max_depth in {2,3}, selected via
  train-only holdout log-loss on the interval classification task. Forecast = Monte-Carlo simulation forward
  from T (150 paths), hourly feature refresh, Binomial(4,p) draws per hour (exactly equivalent in
  distribution to 4 independent 15-min Bernoulli(p) draws when p is held constant within the hour, which is
  how the features are refreshed -- not an approximation of the model, a cheaper equivalent sampler).
- **M6** (Hawkes): real MLE fit of an exponential-kernel self-exciting process (mu, alpha, beta) via
  `scipy.optimize.minimize` (Nelder-Mead, 2 restarts, best log-likelihood kept) on real event timestamps
  from up to the last 40 prior sequences, with a circadian baseline mu(hour) = mu0 * empirical hour-of-day
  multiplier (frozen per refit from up to 120 days of prior history, analogous to the audited `diurnal()`
  pattern elsewhere in this repo -- only alpha/beta/mu0 are genuinely MLE-fit, not the baseline shape).
  Forecast = Ogata thinning simulation (150 paths) seeded by the real observed history up to T. No
  hyperparameter grid (fixed structure), so it contributes 1 trial per target evaluated (see Trial count),
  not a CV-searched candidate count like M1-M5.
  **Bug found and fixed 2026-07-29** (audit Finding 3): the thinning simulator only decayed the
  self-excitation accumulator R on ACCEPTED candidates, leaving it frozen (undecayed) across every rejected
  candidate even though simulated time kept advancing -- this caused runaway over-simulation (reproduced on
  a real auction: mean simulated final = 1516 vs true final = 77, a ~20x blowup, explaining the previously
  reported ~12-nat log loss). Fixed to decay R every step (accept or reject) and to use the circadian
  multiplier's max (not the current-hour value) as the Ogata upper bound. Re-reproduced post-fix on the same
  auction: mean simulated final ~= 85-100, in the right neighborhood of 77. This run's M6/M7(M6) numbers are
  from the FIXED simulator.
  **RNG split fixed 2026-07-29** (re-audit Finding B, LOW): M5 and M6 previously drew from one shared global
  `RNG` (`pattern_discovery_methods.py`). Fixing M6's draw count (above) silently changed how many draws it
  consumed per call, which shifted every subsequent M5 draw for the rest of the run even though M5's own code
  was untouched (6,588 of 21,871 M5 rows changed, undisclosed at the time). M5 and M6 now each draw from their
  own independently-seeded generator (`RNG_M5`, `RNG_M6`, both derived from `RNG_SEED`), so a future change to
  either method's draw count can never again silently perturb the other's numbers.
  **Correction (audit 2026-07-29, re-audit #2, Finding 1): one PRIMARY flag DID flip -- an earlier draft of
  this note wrongly claimed "unchanged." That claim was false and has been removed.**
  `primary_success_elon_7day_sealed_beats_B4` moved from `"none"` (pre-split run) to `["M7(M6)"]` (this run):
  M7(M6) vs B4 on elon_7day sealed went from skill=+0.2711 CI[-0.0056,+0.6654] to skill=+0.2597
  CI[+0.0032,+0.7573], both at n=3. The auditor's full-column diff of `per_row.csv` (225,039 rows) against the
  pre-split backup attributes this, and only this, to the RNG reseed: `model_prob` differs on exactly 35,029
  rows, 100% of them M5/M6/M7(M6); every deterministic method (B1-B4, M1-M4, M7(M1)) is string-identical across
  166,721/166,721 rows. No other logic, data, or gate changed. **This is noise, not a discovery**: at n=3 with
  block_size=1, `block_bootstrap_ci`'s support is bounded exactly by the 3 raw per-auction skill values
  (elon-musk-of-tweets-may-29-june-5: +0.0186, elon-musk-of-tweets-june-2-june-9: +0.0032,
  elon-musk-of-tweets-june-5-june-12: +0.7573), so "CI excludes zero" here only requires those 3 values to
  already share a sign -- P=25% under a true null of zero skill, five times the nominal 5% a 95% CI implies,
  not evidence. The entire mean is carried by one auction; jackknife-drop-best collapses it from +0.2597 to
  +0.0109. This flag is now structurally disqualified rather than left to a reader to catch -- see the
  `SUCCESS_N_FLOOR` reporting gate in the "Success criteria verdict" section below.
- **M7** (composition): M1-daily and M6-daily (same estimators as above, refit on this handle's own daily
  substrate, using an M1 hyperparameter set selected separately on the denser internal
  compose-checkpoint grid) convolved via discrete PMF convolution to the window total. Trump has no
  declared standalone daily target in the prereg; a Trump daily substrate was built ANALOGOUSLY (same
  construction as Elon's) purely as M7's internal mechanism -- flagged here as an interpretation choice for
  the auditor, not a silently-added target. M7(M6) inherits the M6 thinning-simulator fix above.
""")
    lines.append(f"## Trial count\nRealized total: **{TRIALS['n']}** (declared upper bound: 7 methods x up to "
                f"9 checkpoints x 2 handles + hyperparameter grids). By method: {TRIALS['by_method']}. "
                f"M1/M2/M3/M4/M5/M1_compose counts are CV-grid candidate evaluations (see per-method "
                f"disclosure above). M6/M7(M6) have no such grid (fixed-structure MLE fit / composition of "
                f"fixed-structure fits) -- per audit Finding 2, they are now counted at 1 trial per target "
                f"evaluated in (M6: 4 targets = elon_daily, elon_2day, trump_7day, elon_7day; M7(M6): 3 "
                f"auction targets only) so the declared count matches everything actually tried, rather than "
                f"silently omitting a fully-fit-and-reported method. "
                f"Winners (if any) above were re-scored on the disjoint sealed span as the multiple-testing gate; "
                f"no further out-of-sample re-score was performed beyond that split.")
    lines.append("")
    lines.append("## What is too thin to call")
    for target in ("trump_7day", "elon_7day", "elon_2day"):
        sealed = results[target]["sealed"]
        if sealed and sealed["n_auctions_total"] < 15:
            lines.append(f"- **{target}** sealed span has only {sealed['n_auctions_total']} auctions (full "
                         f"sample, B1/B2/B3 comparisons) -- any 'beats' verdict there is noise until more "
                         f"data accrues, not a code defect.")
        if sealed and sealed["n_auctions_b4_admissible"] < 15:
            lines.append(f"- **{target}** sealed span has only {sealed['n_auctions_b4_admissible']} "
                         f"B4-admissible auctions (winner actually priced by the market) -- the PRIMARY "
                         f"(beats-market) verdict for this target is noise until more admissible data accrues.")
    lines.append("- Elon 7-day is the thinnest cell by design (prereg calls it 'reported, not leaned on').")
    lines.append("")
    (OUT_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[output] summary: {OUT_DIR/'summary.md'}")


CKPT_DIR = OUT_DIR / "checkpoints"


def _run_checkpointed(name, compute_fn):
    """Resumability only (process-lifetime limits in the exec sandbox, not
    science): pickle each target's row-list (+ that target's realized trial
    count, so RUN_META's trial_count stays exact across a resumed run) to disk
    once computed, and reuse it on a re-invocation of main() instead of
    recomputing. Purely an I/O cache around the exact same walk-forward
    computation -- never changes what gets fit, never reads sealed data early,
    just avoids re-paying multi-hour Monte-Carlo cost if the process is killed
    between targets."""
    import pickle
    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    p = CKPT_DIR / f"{name}.pkl"
    if p.exists():
        with open(p, "rb") as f:
            rows, trials_snapshot = pickle.load(f)
        TRIALS["n"] += trials_snapshot["n"]
        for k, v in trials_snapshot["by_method"].items():
            TRIALS["by_method"][k] = TRIALS["by_method"].get(k, 0) + v
        print(f"[checkpoint] {name}: loaded {len(rows)} rows from {p} (+{trials_snapshot['n']} trials)")
        return rows
    n0 = TRIALS["n"]
    by0 = dict(TRIALS["by_method"])
    rows = compute_fn()
    trials_snapshot = dict(n=TRIALS["n"] - n0,
                           by_method={k: TRIALS["by_method"].get(k, 0) - by0.get(k, 0)
                                      for k in TRIALS["by_method"]})
    with open(p, "wb") as f:
        pickle.dump((rows, trials_snapshot), f)
    print(f"[checkpoint] {name}: computed + saved {len(rows)} rows to {p}")
    return rows


def main():
    global DAILY_BRACKETS
    t_start = time.time()
    data = build_targets()
    elon_post_ts, elon_is_qr = data["elon_post_ts"], data["elon_is_qr"]
    trump_post_ts, trump_is_qr = data["trump_post_ts"], data["trump_is_qr"]
    daily_elon, daily_trump = data["daily_elon"], data["daily_trump"]

    elon_daily_train_finals = [d["final"] for d in daily_elon.days if d["s"] < WALL_ELON]
    DAILY_BRACKETS = build_daily_brackets(elon_daily_train_finals, SYNTHETIC_DAILY_K)
    print(f"[daily brackets] synthetic K={SYNTHETIC_DAILY_K} (TRAIN-only, frozen): {DAILY_BRACKETS}")

    null_check = r2_null_check(elon_post_ts, daily_elon.days[0]["s"], daily_elon.days[-1]["e"])
    print(f"[null check] R2(count_so_far -> final) daily target: {null_check}")

    all_rows = []
    span_lookup = {}

    print("\n--- Target 1: elon_daily ---")
    rows1 = _run_checkpointed("elon_daily",
        lambda: run_daily_target(elon_post_ts, elon_is_qr, daily_elon, WALL_ELON))
    all_rows += rows1
    # Audit fix (Finding 2): M6 has no hyperparameter grid (fixed-structure MLE,
    # not CV-searched like M1-M5/M1_compose), so it never called _trial() and
    # was silently missing from trial_count. Count it as 1 trial per target it
    # is evaluated in (the same unit other methods' _trial() calls use per
    # select_* call), placed here (not inside compute_fn) so it is charged
    # every run regardless of whether this target's checkpoint was warm or cold.
    _trial("M6")
    for d in daily_elon.days:
        span_lookup[("elon_daily", d["slug"])] = "train" if d["s"] < WALL_ELON else "sealed"

    print("\n--- Target 2: elon_2day ---")
    rows2 = _run_checkpointed("elon_2day",
        lambda: run_auction_target("elon_2day", "elonmusk", data["elon_2day"], CHECKPOINTS_2DAY, WALL_ELON,
                                    data["elon_price"], 48, elon_post_ts, elon_is_qr, daily_elon,
                                    ckpt_path=CKPT_DIR / "elon_2day.mid.pkl"))
    all_rows += rows2
    _trial("M6")
    _trial("M7(M6)")  # M7(M6) only applies to auction targets, not elon_daily itself
    for u in data["elon_2day"]:
        span_lookup[("elon_2day", u["slug"])] = "train" if u["s"] < WALL_ELON else "sealed"

    print("\n--- Target 3: trump_7day ---")
    rows3 = _run_checkpointed("trump_7day",
        lambda: run_auction_target("trump_7day", "realDonaldTrump", data["trump_7day"], CHECKPOINTS_7DAY, WALL_TRUMP,
                                    data["trump_price"], 168, trump_post_ts, trump_is_qr, daily_trump,
                                    maxn=600, maxn_day=250, ckpt_path=CKPT_DIR / "trump_7day.mid.pkl"))
    all_rows += rows3
    _trial("M6")
    _trial("M7(M6)")
    for u in data["trump_7day"]:
        span_lookup[("trump_7day", u["slug"])] = "train" if u["s"] < WALL_TRUMP else "sealed"

    print("\n--- Target 4: elon_7day ---")
    rows4 = _run_checkpointed("elon_7day",
        lambda: run_auction_target("elon_7day", "elonmusk", data["elon_7day"], CHECKPOINTS_7DAY, WALL_ELON,
                                    data["elon_price"], 168, elon_post_ts, elon_is_qr, daily_elon,
                                    maxn=900, maxn_day=250, ckpt_path=CKPT_DIR / "elon_7day.mid.pkl"))
    all_rows += rows4
    _trial("M6")
    _trial("M7(M6)")
    for u in data["elon_7day"]:
        span_lookup[("elon_7day", u["slug"])] = "train" if u["s"] < WALL_ELON else "sealed"

    df = pd.DataFrame(all_rows)
    df["span"] = df.apply(lambda r: span_lookup.get((r["target"], r["auction_slug"]), "unknown"), axis=1)

    # Audit fix (Finding 1, FATAL/BLOCK): flag every row with whether its own
    # (target, auction_slug, checkpoint_hours) had the WINNING bracket actually
    # priced by the market at T. Derived directly from B4's own winner-row
    # market_price (NaN there iff the winner's price was never found) -- no
    # re-emission needed, this is a pure post-hoc column so every row (including
    # the excluded ones) stays in per_row.csv for third-party reproduction.
    b4_cov = (df[(df.method == "B4") & (df.is_winner == 1)]
              [["target", "auction_slug", "checkpoint_hours", "market_price"]]
              .rename(columns={"market_price": "_b4_winner_price"}))
    df = df.merge(b4_cov, on=["target", "auction_slug", "checkpoint_hours"], how="left")
    df["b4_admissible"] = df["_b4_winner_price"].notna()
    df = df.drop(columns=["_b4_winner_price"])

    csv_path = OUT_DIR / "per_row.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n[output] per-row CSV: {csv_path} ({len(df):,} rows)")
    b4_winner_mask = (df.method == "B4") & (df.is_winner == 1)
    n_b4_winner_rows = int(b4_winner_mask.sum())
    n_inadmissible = int((~df.loc[b4_winner_mask, "b4_admissible"]).sum())
    print(f"[b4_admissible] B4 winner rows: {n_b4_winner_rows}, inadmissible (winner never priced at T): {n_inadmissible}")

    results = {}
    for target, block_size in (("elon_daily", 7), ("elon_2day", 1), ("trump_7day", 1), ("elon_7day", 1)):
        results[target] = {}
        for span in ("train", "sealed"):
            results[target][span] = compute_skill_table(df, target, block_size, span)

    # Audit fix (Finding A, MEDIUM, non-fatal): quantify the excluded subset
    # (auctions the market never priced the winner for) instead of leaving the
    # headline silent on it. trump_7day has 0% winner-missing (see coverage
    # above) so it has no excluded subset to disclose; elon_daily has no B4
    # comparison at all (n_auctions_b4_admissible=0 for both spans).
    excluded_subset = {}
    for target in ("elon_2day", "elon_7day"):
        excluded_subset[target] = compute_excluded_subset_skill(df, target, 1, "sealed")

    emit_run_meta(
        script=__file__,
        headline={
            "primary_success_elon_2day_sealed_beats_B4": _headline_flag(results, "elon_2day", "B4"),
            "primary_success_trump_7day_sealed_beats_B4": _headline_flag(results, "trump_7day", "B4"),
            "primary_success_elon_7day_sealed_beats_B4": _headline_flag(results, "elon_7day", "B4"),
            "n_auctions": {t: (results[t]["sealed"] or {}).get("n_auctions_total") for t in results},  # alias kept for emit_run_meta's top-level n_auctions field
            "n_auctions_full": {t: (results[t]["sealed"] or {}).get("n_auctions_total") for t in results},
            "n_auctions_b4_admissible": {t: (results[t]["sealed"] or {}).get("n_auctions_b4_admissible") for t in results},
            "token_price_coverage_pct_winner_missing": {k: v["pct_winner_missing"] for k, v in data["coverage"].items()},
        },
        data_paths=[
            "_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet",
            "_DataMetricPulls/canonical/posts/realDonaldTrump/*.parquet",
            "_DataMetricPulls/canonical/auctions/{elonmusk,realDonaldTrump}/*.parquet",
            "_DataMetricPulls/canonical/prices/{elonmusk,realDonaldTrump}/*.parquet",
            "api/modules/shared/locked_pace.py",
        ],
        window_basis="noon-ET parsed from market slug (generalized bracket_hit_backtest.py::noon()), "
                      "NEVER trade-derived start_utc/end_utc",
        fills="N/A -- scope (b) pure forecast-accuracy/calibration diagnostic, no P&L, no fills simulated",
        trial_count=TRIALS["n"],
        scope="pure forecast-accuracy / calibration diagnostic (prereg pattern_discovery_2026-07-26.md)",
        notes=f"trials_by_method={TRIALS['by_method']}; null_check={null_check}; "
              f"coverage={data['coverage']}; trump_7day_excluded_no_post_data={len(data['trump_7day_excluded'])}; "
              f"audit_2026-07-29_fixes=[Finding1: B4 comparisons now gated on b4_admissible "
              f"(winner actually priced at T), never defaulted to 1e-6 -- see n_auctions_b4_admissible; "
              f"Finding2: M6/M7(M6) now counted in trial_count; "
              f"Finding3: fixed Hawkes thinning-sim R-decay-on-rejection bug (was causing ~20x runaway "
              f"over-simulation, 12-nat log loss)]; "
              f"reaudit_2026-07-29_fixes=[FindingA(MEDIUM): headline scoped to n_auctions_b4_admissible, "
              f"excluded-subset (winner never priced by market) disclosed separately as an OPEN QUESTION, "
              f"not a finding -- see 'Excluded-subset disclosure' section and excluded_subset={excluded_subset}; "
              f"FindingB(LOW): M5 and M6 now use independently-seeded generators (RNG_M5/RNG_M6, "
              f"pattern_discovery_methods.py) instead of one shared RNG, so a future single-method fix can't "
              f"silently perturb the other's draws]; "
              f"reaudit2_2026-07-29_fixes=[Finding1(MEDIUM-HIGH): removed a FALSE claim in the M6 disclosure "
              f"text that every headline verdict was 'unchanged' after the RNG split -- "
              f"primary_success_elon_7day_sealed_beats_B4 in fact moved from 'none' to ['M7(M6)'] (RNG reseed "
              f"alone: 35,029/225,039 model_prob rows changed, 100% M5/M6/M7(M6); all other methods "
              f"166,721/166,721 rows string-identical), and this is now stated plainly with the degenerate-CI "
              f"reasoning in the M6 per-method disclosure; "
              f"Finding2(MEDIUM): added SUCCESS_N_FLOOR={SUCCESS_N_FLOOR} -- any primary_success_*_beats_B4/B3/B1 "
              f"whose comparison n falls below this floor is now emitted as an explicit "
              f"'noise (n=..., below admissible floor of {SUCCESS_N_FLOOR})' sentinel instead of a bare method "
              f"list, in both this RUN_META and summary.md, implementing the prereg's own CI-including-zero/"
              f"n<10 noise rule as a structural gate rather than prose. Underlying skill/CI/jackknife/n values "
              f"are never hidden by this gate, only the pass/fail headline label. Only "
              f"primary_success_elon_7day_sealed_beats_B4 (n_auctions_b4_admissible=3) is currently affected]; "
              f"dstfix_2026-07-31_fixes=[Finding2(MEDIUM, re-audit #4, 2026-07-31): 5-site DST/day-boundary fix "
              f"found while auditing a sibling regime study, confirmed to also affect this script -- DailySeries, "
              f"r2_null_check, run_auction_target's M7 daily decomposition, build_targets's Trump day-zero anchor "
              f"(defensive fix -- built via a direct single-instant Timestamp construction, never actually "
              f"exposed to this bug class), and pattern_discovery_methods.py:282 (M3's within-day remaining-count "
              f"feature, d['s']+86400 -> d['e']); all now route through add_days_et() (calendar-aware "
              f"tz_convert(ET) + DateOffset(days=n), wall-clock-preserving across both US transition dates). "
              f"Drift: 126 of 285 elon_daily day anchors landed on 11:00 ET instead of noon ET (off by exactly "
              f"+3600s), spanning 2025-11-02 to 2026-03-07 (the US DST-standard-time window), 0 after the fix. "
              f"Why it mattered despite sealed windows self-correcting: the TRAIN span contains all 126 drifted "
              f"days, so every frozen artefact fit on TRAIN (bin edges, terciles, CV-selected hyperparameters, "
              f"cluster centroids, HMM parameters) was fit on misaligned windows, then applied to correctly-"
              f"aligned SEALED data. Measured effect, isolated from the coverage repair: 32,132 model_prob rows "
              f"changed on the three auction-scored targets across M2 (5,017 rows, up to 0.39 abs diff), M5 "
              f"(2,296 rows, up to 0.59), M6 (8,076 rows, up to 0.14), M7(M1) (7,791 rows, up to 0.07), M7(M6) "
              f"(8,952 rows, up to 0.17); plus 2,671 rows on elon_daily, 100% M3 (isolated fix). True magnitude "
              f"range up to 0.76 on TRAIN / 0.59 on SEALED -- an earlier informal 'only M6/M7 moved, by "
              f"0.003-0.17' characterization was inaccurate on both the method list and the magnitude and is "
              f"corrected here. B1/B2/B3/M1/M4 are bit-identical on the auction targets (they do not consume "
              f"DailySeries-derived trailing_fn/prior_final_fn); M2 and M5 consume those features directly as "
              f"declared prereg inputs; M6/M7/M3 are themselves built directly from DailySeries/add_days_et "
              f"day-boundaries. r2_null_check moved as a direct consequence of being one of the 5 fixed sites: "
              f"hour18 0.764->0.744, hour21 0.856->0.870 (see null_check= above for the exact post-fix floats). "
              f"No PRIMARY beats-B4 verdict changed as a result of this fix (elon_7day sealed's n=3->19 move was "
              f"the separate coverage repair, not this fix). Verified via two independently-triggered cold runs "
              f"post-fix reproducing a byte-identical per_row.csv (MD5), summary.md, and this RUN_META]",
        out_dir="pattern_discovery_out",
    )

    write_summary(df, results, data, null_check, excluded_subset)
    print(f"\n[total runtime] {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
