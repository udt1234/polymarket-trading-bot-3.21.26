# -*- coding: utf-8 -*-
"""EXTRACTION PASS over the already-fitted pattern-discovery study
(`pattern_discovery_2026-07-26.py`). This is NOT a new study and NOT a re-fit
of the study's conclusions -- it prints what the fitted models actually
LEARNED as human-readable rules. No hyperparameter, wall date, or model is
changed anywhere in this file.

Reuse policy (per task instructions): the fitted DecisionTreeClassifier (M2),
KMeans centroids (M3), PoissonHMM (M4), and GradientBoostingClassifier (M5)
objects were NEVER PERSISTED by the original run -- `pattern_discovery_out/
checkpoints/*.pkl` only cache the per-row prediction rows, not the fitted
estimator objects (verified by inspection before writing this script). So
every model below is REFIT here, using:
  (a) the EXACT train-only data construction from `pattern_discovery_2026-
      07-26.py::build_targets()` (imported and called directly, not
      reimplemented, so there is zero risk of a transcription drift), and
  (b) the EXACT hyperparameters recorded in `pattern_discovery_out/
      summary.md`'s "Per-method estimator disclosure" section /
      `pattern_discovery_out/run_dstfix_2026-07-31.log` (the frozen,
      byte-identical-on-two-cold-reruns post-DST-fix log; hardcoded as
      constants below, never re-searched).
This is explicitly disclosed at every refit site below and in RUN_META.

2026-07-31 update: a 5-site DST bug fix landed upstream in
pattern_discovery_2026-07-26.py / pattern_discovery_methods.py after this
file's prior audited run. The daily target's disclosed hyperparameter
selection genuinely changed under that fix; the constants below were
re-diffed against the fresh `run_dstfix_2026-07-31.log`, not re-selected.
Leaf IDs and rule counts in this run's outputs do NOT correspond to any
earlier run's -- see the SUPERSESSION NOTICE in each output file.

Scope: (b) pure descriptive/interpretability extraction. NO P&L, no fills,
NO tradeability claim attached to any rule (per prereg: "nothing beat the
market where the market priced the winner" already answered that question).

Reads (read-only): pattern_discovery_2026-07-26.py, pattern_discovery_lib.py,
pattern_discovery_methods.py, pattern_discovery_out/summary.md (for the
disclosed hyperparameters), and the same canonical parquet paths those
scripts read. WRITES ONLY to `rules_out/` and this file itself.

Hands off to @backtest-auditor -- this script does not certify its own
output.
"""
from __future__ import annotations

import importlib.util
import math
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PB = Path(__file__).resolve().parent
ROOT = PB.parents[1]
sys.path.insert(0, str(PB))
sys.path.insert(0, str(ROOT))

import pattern_discovery_lib as L                       # noqa: E402  (reuse, not reinvent)
import pattern_discovery_methods as M                    # noqa: E402
from run_meta import emit_run_meta                        # noqa: E402
from sklearn.tree import DecisionTreeClassifier, export_text  # noqa: E402

OUT_DIR = PB / "rules_out"
OUT_DIR.mkdir(exist_ok=True)
RNG_SEED = 20260726  # same seed as the original study; nothing here is randomized further
np.random.seed(RNG_SEED)

# ---------------------------------------------------------------------------
# Load the original study module WITHOUT running its main() (module-level
# code only: constants, class/function defs, sys.path setup -- all idempotent
# and side-effect-free; verified by reading the file before importing it).
# This is the "reuse, don't reinvent" path for WALL dates, checkpoint grids,
# and the exact `build_targets()` data-construction pipeline.
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location("pd_main_readonly", PB / "pattern_discovery_2026-07-26.py")
PD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PD)

# ---------------------------------------------------------------------------
# FROZEN hyperparameters, copied verbatim from pattern_discovery_out/
# run_dstfix_2026-07-31.log (the log of the post-DST-fix run, verified frozen
# by two cold back-to-back re-runs with byte-identical per_row.csv/summary.md/
# RUN_META -- this SUPERSEDES the pre-fix run_reaudit_fix.log this script
# previously cited) and cross-checked against the same log's disclosed values.
# NEVER re-searched here -- select_M1/select_M2/... are not called by this
# script at all. audit 2026-07-31 round-2: the daily target's disclosed
# selection genuinely changed under the DST fix (K 4->3, ccp_alpha 0.0->
# 0.01636, M3_k 4->3, M4_states 3->4) -- caught by diffing against the fresh
# log rather than trusting the old hardcoded comment; elon_2day's disclosed
# selection is unchanged.
#   [daily]     M2={'K': 3, 'ccp_alpha': 0.01636}  M3_k=3  M4_states=4  M5={'n_estimators': 50, 'max_depth': 2}
#   [elon_2day] M2={'K': 4, 'ccp_alpha': 0.0}              M4_states=4  M5={'n_estimators': 50, 'max_depth': 2}
# ---------------------------------------------------------------------------
DAILY_M2_HP = dict(K=3, ccp_alpha=0.01636)
DAILY_M3_K = 3
DAILY_M4_STATES = 4
DAILY_M5_HP = dict(n_estimators=50, max_depth=2)

E2D_M2_HP = dict(K=4, ccp_alpha=0.0)
E2D_M4_STATES = 4

TREE_MAX_DEPTH = 4          # prereg cap, M2 disclosure
TREE_MIN_SAMPLES_LEAF = 25  # prereg cap, M2 disclosure

MIN_N_FLAG = 30  # non-negotiable: flag any rule resting on <30 matching days
DAILY_N_EFF_FRAC = 0.39  # disclosed: daily counts autocorrelate at lag-1 rho=0.44 -> N_eff ~ 39% of nominal

print("=" * 78)
print("EXTRACTION PASS -- reading fitted-model structure from "
      "pattern_discovery_2026-07-26.py's exact data pipeline + disclosed hyperparameters.")
print("=" * 78)

# ---------------------------------------------------------------------------
# Rebuild the EXACT same data the audited run used (calls the original
# build_targets() directly -- zero reimplementation, zero risk of drift).
# ---------------------------------------------------------------------------
DATA = PD.build_targets()
elon_post_ts, elon_is_qr = DATA["elon_post_ts"], DATA["elon_is_qr"]
daily_elon = DATA["daily_elon"]
elon_2day_all = DATA["elon_2day"]
WALL_ELON = PD.WALL_ELON
CHECKPOINTS_DAILY = PD.CHECKPOINTS_DAILY
CHECKPOINTS_2DAY = PD.CHECKPOINTS_2DAY

daily_train = [d for d in daily_elon.days if d["s"] < WALL_ELON]
daily_sealed = [d for d in daily_elon.days if d["s"] >= WALL_ELON]
e2d_train = [u for u in elon_2day_all if u["s"] < WALL_ELON]
e2d_sealed = [u for u in elon_2day_all if u["s"] >= WALL_ELON]

print(f"[data] elon_daily: n_train={len(daily_train)} n_sealed={len(daily_sealed)} "
      f"(disclosed run reported n_auctions_full=198 train/87 sealed in summary.md's skill table -- that "
      f"198 is a STRICTER subset: the original walk-forward loop additionally requires >=10 PRIOR days "
      f"before it emits any scoring row, so it skips the first 2 refit_block=7 blocks [14 calendar days] "
      f"outright. 212 = ALL calendar train days in [2025-09-01, WALL); this is also the exact pool the "
      f"original main() used to build DAILY_BRACKETS -- confirmed below by exact reproduction. This "
      f"extraction fits one representative tree/cluster/HMM/hazard model on the FULL 212-day pool since a "
      f"single-shot fit needs no such priors-only-for-scoring gate; sealed n=87 matches exactly either way.)")
print(f"[data] elon_2day:  n_train={len(e2d_train)} n_sealed={len(e2d_sealed)} "
      f"(disclosed run: train=38, sealed=28)")

trailing_fn = lambda T: daily_elon.trailing_mean(T)
prior_final_fn_daily = PD.make_prior_final_fn(daily_elon.days)
prior_final_fn_e2d = PD.make_prior_final_fn(elon_2day_all)

DAILY_BRACKETS = PD.build_daily_brackets([d["final"] for d in daily_train], PD.SYNTHETIC_DAILY_K)
_expected_brackets = [('<26', 0, 25), ('26-35', 26, 35), ('36-47', 36, 47), ('48-61', 48, 61), ('62+', 62, None)]
assert DAILY_BRACKETS == _expected_brackets, (
    f"DAILY_BRACKETS drifted from the disclosed run: got {DAILY_BRACKETS}, expected {_expected_brackets}")
print(f"[sanity] DAILY_BRACKETS reproduced exactly: {DAILY_BRACKETS}")


def daily_bracket_lookup(final):
    for label, lo, hi in DAILY_BRACKETS:
        if final >= lo and (hi is None or final <= hi):
            return label
    return DAILY_BRACKETS[-1][0]


# ===========================================================================
# SECTION 1 -- DECISION TREE (M2), full print + hand-formatted leaves
# ===========================================================================
def bin_labels_from_edges(edges):
    labels = []
    K = len(edges) - 1
    for i in range(K):
        lo, hi = edges[i], edges[i + 1]
        if not np.isfinite(lo):
            labels.append(f"<{int(round(hi))}")
        elif not np.isfinite(hi):
            labels.append(f"{int(round(lo))}+")
        else:
            labels.append(f"{int(round(lo))}-{int(round(hi)) - 1}")
    return labels


def build_M2_rows(units, checkpoints, post_ts, is_qr, trailing_fn_, prior_final_fn_, edges):
    """Replicates pattern_discovery_methods.py::fit_M2's own row-construction
    loop EXACTLY (same build_features/feat_vector calls, same trailing_fn(T)
    convention -- verified against fit_M2 source), only ADDING provenance
    (slug, checkpoint hour, final count) that fit_M2 itself doesn't expose."""
    X, y, prov = [], [], []
    for u in units:
        dur_s = u["e"] - u["s"]
        for c in checkpoints:
            if c * 3600 >= dur_s:
                continue
            T = u["s"] + c * 3600
            _, feats = M.build_features(post_ts, is_qr, u["s"], T,
                                         prior_final_fn_(u["s"]), trailing_fn_(T))
            X.append(M.feat_vector(feats, M.FEATURE_NAMES))
            y.append(M.label_from_final(u["final"], edges))
            prov.append(dict(slug=u["slug"], s=u["s"], checkpoint_hours=c, T=T, final=u["final"]))
    if not X:
        return np.zeros((0, len(M.FEATURE_NAMES))), np.array([], dtype=int), []
    return np.vstack(X), np.array(y, dtype=int), prov


def extract_leaf_paths(clf, feature_names):
    tree = clf.tree_
    paths = {}

    def rec(node, path):
        if tree.children_left[node] == -1:
            paths[node] = path
            return
        f = feature_names[tree.feature[node]]
        t = float(tree.threshold[node])
        rec(tree.children_left[node], path + [(f, "<=", t)])
        rec(tree.children_right[node], path + [(f, ">", t)])

    rec(0, [])
    return paths


def _checkpoint_clock_labels(checkpoints):
    """audit 2026-07-31 [C][LOW] fix: a checkpoint hour h into a noon-ET window
    lands at ET clock (12+h)%24, on calendar day (12+h)//24 relative to window
    start (0=same day, 1=next day, ...). Used to render the ACTUAL evaluated
    checkpoint times inline instead of leaving a reader to infer a decision
    time from a raw hours_into_window threshold."""
    labels = []
    for c in checkpoints:
        day_off = (12 + c) // 24
        clock = (12 + c) % 24
        day_txt = {0: "same day", 1: "next day"}.get(day_off, f"{day_off} days later")
        labels.append(f"{c}h(~{clock:02d}:00 ET {day_txt})")
    return labels


def format_condition(feat_name, op, thr, checkpoints=None):
    if feat_name in ("median_gap_s", "longest_gap_s"):
        label = "median gap between posts" if feat_name == "median_gap_s" else "longest gap between posts"
        return f"{label} {op} {thr / 3600:.2f}h"
    if feat_name == "gap_var_s2":
        return f"gap variability (std) {op} {math.sqrt(max(thr, 0)) / 3600:.2f}h"
    if feat_name == "first_post_hours":
        clock = (12 + thr) % 24
        return f"first post {op} {thr:.1f}h after window start (~{clock:04.1f}:00 ET)"
    if feat_name == "hours_into_window":
        base = f"hours into window {op} {thr:.1f}h"
        if checkpoints:
            # audit 2026-07-31 [C][LOW]: only the discrete evaluated checkpoints ever
            # actually satisfy this split (rows only exist at checkpoint hours) --
            # render those, not just the raw threshold, so the rule text can't be
            # misread as a continuous decision time (e.g. "16.5h" parsed as ~04:30 ET
            # when the real fixed checkpoints are 06:00/09:00 ET).
            matched = [c for c in checkpoints if (c <= thr if op == "<=" else c > thr)]
            if matched:
                base += f" [only fires at checkpoint(s): {', '.join(_checkpoint_clock_labels(matched))}]"
        return base
    if feat_name == "count_so_far":
        return f"posts so far {op} {thr:.1f}"
    if feat_name in ("posts_last_1h", "posts_last_3h", "posts_last_6h"):
        hh = feat_name.split("_")[-1]
        return f"posts in last {hh} {op} {thr:.1f}"
    if feat_name == "max_posts_60min":
        return f"max posts in any 60-min window {op} {thr:.1f}"
    if feat_name == "dow":
        return f"day-of-week code {op} {thr:.1f} (0=Mon..6=Sun)"
    if feat_name == "et_hour":
        return f"ET hour-of-day {op} {thr:.1f}"
    if feat_name == "prior_window_final":
        return f"previous window's final count {op} {thr:.1f}"
    if feat_name == "trailing_7d_mean":
        return f"trailing 7-day mean count {op} {thr:.1f}"
    if feat_name == "share_qr":
        return f"share of quotes/reposts so far {op} {thr:.2f}"
    return f"{feat_name} {op} {thr:.3f}"


# ---------------------------------------------------------------------------
# Audit 2026-07-31 [D][MEDIUM] fix: for EVERY rule in the ranked table, fit a
# single-feature (count_so_far) decision-stump baseline over the SAME pool
# this rule draws from (ALL units at that rule's own decision checkpoint(s)/
# hour, NOT filtered to the rule's own membership condition -- a naive rule
# that only had to match the rule's own subset would be tautological).
# TRAIN-only fit, subject to n>=TREE_MIN_SAMPLES_LEAF (the CART's own
# disclosed min_samples_leaf=25 -- reused, not a new/re-selected
# hyperparameter), frozen, then applied unchanged to the SEALED pool at that
# rule's own sealed checkpoint(s)/hour.
#
# 2026-07-31 round-3 fix (audit finding [HIGH] #2, leaf9): the search now
# covers TWO-SIDED BANDS (lo<=x<=hi) in addition to one-sided thresholds, not
# one-sided-only as before. A one-sided threshold cannot isolate an interior
# (middle) ordinal bin the way a band can, and the auditor's dynamic probe
# showed a bare band on count_so_far ALONE gets within ~5pp of leaf9's own
# 90.5% sealed hit rate using the identical single feature -- the old
# one-sided-only baseline was too weak to catch this. Implementation: every
# observed value is a candidate lo AND a candidate hi (lo<=hi); choosing
# lo=min(observed) recovers the old "<=hi" case exactly, choosing
# hi=max(observed) recovers the old ">lo'" case exactly (lo' = the next
# observed value above the old threshold -- exactly the same mask on this
# data, since no unobserved value sits between two consecutive uniques), so
# the new search space is a strict SUPERSET of the old one -- a stronger
# baseline can only make survival harder, never easier. Built via 2D... err
# 1D cumulative-sum tables so the O(U^2) pair search costs O(1) per pair
# (U = count of distinct observed values), not O(U^2 * n).
# Ties in the search (equal train hit-rate) are broken by (a) larger n, then
# (b) the earliest-scanned (lo, hi) pair in ascending-lo-then-ascending-hi
# order -- deterministic, no randomness.
# ---------------------------------------------------------------------------
def fit_naive_threshold(counts, y_bool, min_n):
    counts = np.asarray(counts, dtype=float)
    y_bool = np.asarray(y_bool, dtype=bool)
    if len(counts) == 0:
        return None
    uniq = np.unique(counts)
    U = len(uniq)
    idx = np.searchsorted(uniq, counts)
    cnt = np.bincount(idx, minlength=U).astype(float)
    hit_cnt = np.bincount(idx, weights=y_bool.astype(float), minlength=U)
    pcnt = np.concatenate(([0.0], np.cumsum(cnt)))       # pcnt[k] = count in uniq[:k]
    phit = np.concatenate(([0.0], np.cumsum(hit_cnt)))
    best = None
    for i_lo in range(U):
        for i_hi in range(i_lo, U):
            n = int(pcnt[i_hi + 1] - pcnt[i_lo])
            if n < min_n:
                continue
            hit = float((phit[i_hi + 1] - phit[i_lo]) / n)
            key = (hit, n)
            if best is None or key > best[0]:
                best = (key, float(uniq[i_lo]), float(uniq[i_hi]), n, hit)
    if best is None:
        return None
    _, lo, hi, n_tr, hit_tr = best
    if lo <= uniq[0] and hi < uniq[-1]:
        kind = "<="
    elif hi >= uniq[-1] and lo > uniq[0]:
        kind = ">="
    elif lo <= uniq[0] and hi >= uniq[-1]:
        kind = "all"
    else:
        kind = "band"
    return dict(lo=lo, hi=hi, kind=kind, n_train=n_tr, hit_train=hit_tr)


def naive_threshold_mask(rule, counts):
    """Boolean mask for `counts` under an ALREADY-FIT naive rule (frozen lo/hi band) --
    no re-fit, just recovers which rows a given (frozen) band selects, so those rows'
    UNIQUE auctions can be counted (see jackknife_loo_auction / the n_train/n_sealed
    auction-count fix below). rule=None (no band reached min_n) -> all-False."""
    counts = np.asarray(counts, dtype=float)
    if rule is None:
        return np.zeros(len(counts), dtype=bool)
    return (counts >= rule["lo"]) & (counts <= rule["hi"])


def apply_naive_threshold(rule, counts, y_bool):
    counts = np.asarray(counts, dtype=float)
    y_bool = np.asarray(y_bool, dtype=bool)
    if rule is None or len(counts) == 0:
        return 0, float("nan")
    mask = naive_threshold_mask(rule, counts)
    n = int(mask.sum())
    hit = float(y_bool[mask].mean()) if n else float("nan")
    return n, hit


def _fmt_band(lo, hi, kind, feat_name="count_so_far"):
    if kind == "<=":
        return f"{feat_name} <= {hi:.1f}"
    if kind == ">=":
        return f"{feat_name} >= {lo:.1f}"
    if kind == "all":
        return f"{feat_name} in [{lo:.1f}, {hi:.1f}] (whole pool)"
    return f"{feat_name} in [{lo:.1f}, {hi:.1f}]"


# audit 2026-07-31 [D][MEDIUM] round-2 fix: effective-n for ANY reliability gate in this
# project is resolved AUCTIONS, never ticks/rows/checkpoints (standing rule, see
# lesson_tiny_n_ci_degenerate.md) -- re-applied here after the re-audit caught its absence
# in this script's new naive-baseline scorecard (a single auction can hit multiple
# checkpoints, e.g. 6/12/15 or 18/21, that all route to the SAME CART leaf, inflating n).
def jackknife_loo_auction(slugs, hit_bool):
    """Leave-one-AUCTION(slug)-out jackknife of a row-level hit rate. Dropping an auction
    drops ALL of its checkpoint-rows at once -- checkpoint-rows from the same auction are
    not independent draws, so this is genuinely leave-one-auction-out, not leave-one-row-out.
    Returns None if fewer than 2 unique auctions (jackknife undefined at n<2)."""
    slugs = np.asarray(slugs)
    hit_bool = np.asarray(hit_bool, dtype=bool)
    uniq = np.unique(slugs)
    if len(uniq) < 2:
        return None
    rates = []
    for s in uniq:
        keep = slugs != s
        if keep.sum() == 0:
            continue
        rates.append(float(hit_bool[keep].mean()))
    if not rates:
        return None
    return dict(jk_n_auctions=int(len(uniq)), jk_hit_min=min(rates), jk_hit_max=max(rates))


# ---------------------------------------------------------------------------
# Audit 2026-07-31 round-3 [D][HIGH] fix (finding #1): a raw point comparison
# (rule_hit_sealed > naive_hit_sealed) says nothing about whether the margin
# is distinguishable from sampling noise -- the shipped jackknife only ranges
# the rule's OWN raw hit rate, never the DIFFERENCE against naive (which has
# its own, different-population sampling variance). This block-bootstraps
# incremental_lift_over_naive (= rule_hit / naive_hit) AT THE AUCTION LEVEL,
# mirroring the auditor's own 2026-07-31 dynamic confirmation exactly: the
# rule's own matching auctions and the naive rule's own matching auctions are
# resampled WITH REPLACEMENT, INDEPENDENTLY of each other (same discipline
# the audit log describes), 5,000 times. Each resample draws AUCTIONS, not
# rows -- an auction's checkpoint-rows travel together as one block (a drawn
# auction's rows all get the same resample weight), so within-auction rows
# are never treated as independent draws. seed is fixed for reproducibility.
# ---------------------------------------------------------------------------
N_BOOT = 5000
BOOT_SEED = 20260731


def _block_bootstrap_hitrate(slugs, y_bool, n_boot, rng):
    """Auction-level (block) bootstrap distribution of a row-level hit rate.
    Returns None if fewer than 2 unique auctions (bootstrap undefined at n<2,
    same floor convention as jackknife_loo_auction)."""
    slugs = np.asarray(slugs)
    y_bool = np.asarray(y_bool, dtype=float)
    uniq, inv = np.unique(slugs, return_inverse=True)
    U = len(uniq)
    if U < 2:
        return None
    auction_y_sum = np.bincount(inv, weights=y_bool, minlength=U)
    auction_n = np.bincount(inv, minlength=U)
    out = np.empty(n_boot)
    for b in range(n_boot):
        draw_idx = rng.integers(0, U, size=U)
        w = np.bincount(draw_idx, minlength=U).astype(float)
        den = float((w * auction_n).sum())
        out[b] = float((w * auction_y_sum).sum()) / den if den > 0 else np.nan
    return out


def bootstrap_incremental_lift_ci(rule_slugs, rule_y, naive_slugs, naive_y, n_boot=N_BOOT, seed=BOOT_SEED):
    """95% CI + P(lift<=1.0) on incremental_lift_over_naive = rule_hit/naive_hit,
    via independent auction-level block bootstraps of each side (see docstring
    above). Returns None if either side has fewer than 2 unique auctions."""
    rng = np.random.default_rng(seed)
    boot_rule = _block_bootstrap_hitrate(rule_slugs, rule_y, n_boot, rng)
    boot_naive = _block_bootstrap_hitrate(naive_slugs, naive_y, n_boot, rng)
    if boot_rule is None or boot_naive is None:
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        boot_lift = boot_rule / boot_naive
    boot_lift = boot_lift[np.isfinite(boot_lift)]
    if len(boot_lift) < 100:  # too few valid draws to trust a percentile CI
        return None
    ci_lo, ci_hi = np.percentile(boot_lift, [2.5, 97.5])
    p_le_1 = float((boot_lift <= 1.0).mean())
    return dict(ci_lo=float(ci_lo), ci_hi=float(ci_hi), p_lift_le_1=p_le_1, n_boot_used=int(len(boot_lift)))


def naive_verdict_from_ci(rule_hit_sealed, hit_se, ci):
    """3-category verdict per audit finding #1's fix: SURVIVES only if the
    incremental-lift CI EXCLUDES 1.0 (ci_lo > 1.0). A point estimate above
    naive whose CI straddles 1.0 is UNPROVEN, not SURVIVES -- distinct from
    COLLAPSES (point estimate at or below naive). UNTESTABLE = no naive
    baseline / no sealed rows / bootstrap undefined (e.g. n_sealed<2
    auctions on either side -- this is what disqualifies the n=1-auction
    M2-elon_2day-leaf6 row from ever reading SURVIVES)."""
    if hit_se is None or (isinstance(hit_se, float) and math.isnan(hit_se)) or \
       rule_hit_sealed is None or (isinstance(rule_hit_sealed, float) and math.isnan(rule_hit_sealed)):
        return "UNTESTABLE"
    if rule_hit_sealed <= hit_se:
        return "COLLAPSES"
    if ci is not None and ci["ci_lo"] > 1.0:
        return "SURVIVES"
    return "UNPROVEN"


def naive_baseline_report(rule_hit_sealed, naive, n_se, hit_se, ci=None):
    """Bundles the naive comparison into the fields every rule row carries.
    naive = fit_naive_threshold()'s return (TRAIN-side fit, or None if no
    band reached min_n). n_se/hit_se = apply_naive_threshold()'s result
    on the rule's own SEALED pool. ci = bootstrap_incremental_lift_ci()'s
    return (or None if undefined)."""
    if naive is None:
        return dict(naive_lo=None, naive_hi=None, naive_kind=None, naive_n_train=0,
                     naive_hit_train=float("nan"), naive_n_sealed=n_se, naive_hit_sealed=hit_se,
                     incremental_lift_over_naive=float("nan"), beats_naive_sealed=None,
                     incr_lift_ci_lo=float("nan"), incr_lift_ci_hi=float("nan"), p_lift_le_1=float("nan"),
                     naive_verdict="UNTESTABLE")
    inc = (rule_hit_sealed / hit_se) if (hit_se and hit_se > 0 and not math.isnan(rule_hit_sealed)) else float("nan")
    beats = (rule_hit_sealed > hit_se) if (n_se > 0 and not math.isnan(hit_se) and not math.isnan(rule_hit_sealed)) else None
    verdict = naive_verdict_from_ci(rule_hit_sealed, hit_se, ci)
    return dict(naive_lo=naive["lo"], naive_hi=naive["hi"], naive_kind=naive["kind"],
                naive_n_train=naive["n_train"], naive_hit_train=naive["hit_train"],
                naive_n_sealed=n_se, naive_hit_sealed=hit_se,
                incremental_lift_over_naive=inc, beats_naive_sealed=beats,
                incr_lift_ci_lo=(ci["ci_lo"] if ci else float("nan")),
                incr_lift_ci_hi=(ci["ci_hi"] if ci else float("nan")),
                p_lift_le_1=(ci["p_lift_le_1"] if ci else float("nan")),
                naive_verdict=verdict)


# ---------------------------------------------------------------------------
# Carried forward from @backtest-auditor's independent 2026-07-31 re-audit
# (audit-only probe there; made a permanent, disclosed check here per
# coordinator instruction): a strictly HARDER two-feature naive baseline --
# count_so_far AND max_posts_60min, same non-tautological pool (ALL units at
# the rule's own decision checkpoints), same TRAIN-fit/frozen/sealed-applied
# discipline, same min_n=TREE_MIN_SAMPLES_LEAF=25 floor on the combined mask.
# CART leaves only (matches the auditor's own probe scope) -- M3 clusters do
# not carry a count_so_far/max_posts_60min pair in the same sense
# (shape-based proxy instead), so no 2-feature check is invented for them.
#
# 2026-07-31 round-3 fix (audit finding [HIGH] #2's own instruction: "extend
# BOTH naive baselines to search two-sided bands as well as one-sided
# thresholds"): each feature is now searched as a BAND (lo<=x<=hi), not
# one-sided-only -- same superset argument as the 1-feature fix above. Built
# via a 2D histogram + 2D cumulative-sum table so every (band1 x band2)
# rectangle costs O(1) to score, with the feature-1 marginal used to prune
# infeasible band1 choices (n1<min_n) before ever entering the band2 loop.
# ---------------------------------------------------------------------------
def fit_naive_threshold_2d(counts1, counts2, y_bool, min_n):
    counts1 = np.asarray(counts1, dtype=float)
    counts2 = np.asarray(counts2, dtype=float)
    y_bool = np.asarray(y_bool, dtype=float)
    if len(counts1) == 0:
        return None
    uniq1 = np.unique(counts1)
    uniq2 = np.unique(counts2)
    U1, U2 = len(uniq1), len(uniq2)
    i1 = np.searchsorted(uniq1, counts1)
    i2 = np.searchsorted(uniq2, counts2)
    H = np.zeros((U1, U2))
    Hhit = np.zeros((U1, U2))
    np.add.at(H, (i1, i2), 1.0)
    np.add.at(Hhit, (i1, i2), y_bool)
    P = np.zeros((U1 + 1, U2 + 1))
    Phit = np.zeros((U1 + 1, U2 + 1))
    P[1:, 1:] = np.cumsum(np.cumsum(H, axis=0), axis=1)
    Phit[1:, 1:] = np.cumsum(np.cumsum(Hhit, axis=0), axis=1)
    row_marginal = H.sum(axis=1)                              # feature-1-only counts, for pruning
    row_pcnt = np.concatenate(([0.0], np.cumsum(row_marginal)))

    def rect(PP, a, b, c, d):  # inclusive index ranges [a,b] x [c,d]
        return PP[b + 1, d + 1] - PP[a, d + 1] - PP[b + 1, c] + PP[a, c]

    best = None
    for a in range(U1):
        for b in range(a, U1):
            n1 = row_pcnt[b + 1] - row_pcnt[a]
            if n1 < min_n:
                continue
            for c in range(U2):
                for d in range(c, U2):
                    n = int(rect(P, a, b, c, d))
                    if n < min_n:
                        continue
                    hit = float(rect(Phit, a, b, c, d) / n)
                    key = (hit, n)
                    if best is None or key > best[0]:
                        best = (key, float(uniq1[a]), float(uniq1[b]), float(uniq2[c]), float(uniq2[d]), n, hit)
    if best is None:
        return None
    _, lo1, hi1, lo2, hi2, n_tr, hit_tr = best
    return dict(lo1=lo1, hi1=hi1, lo2=lo2, hi2=hi2, n_train=n_tr, hit_train=hit_tr)


def naive_threshold_mask_2d(rule, counts1, counts2):
    counts1 = np.asarray(counts1, dtype=float)
    counts2 = np.asarray(counts2, dtype=float)
    if rule is None:
        return np.zeros(len(counts1), dtype=bool)
    m1 = (counts1 >= rule["lo1"]) & (counts1 <= rule["hi1"])
    m2 = (counts2 >= rule["lo2"]) & (counts2 <= rule["hi2"])
    return m1 & m2


def apply_naive_threshold_2d(rule, counts1, counts2, y_bool):
    y_bool = np.asarray(y_bool, dtype=bool)
    if rule is None or len(counts1) == 0:
        return 0, float("nan")
    mask = naive_threshold_mask_2d(rule, counts1, counts2)
    n = int(mask.sum())
    hit = float(y_bool[mask].mean()) if n else float("nan")
    return n, hit


def naive2_baseline_report(rule_hit_sealed, naive2, n_se, hit_se, ci=None):
    if naive2 is None:
        return dict(naive2_feature1="count_so_far", naive2_lo1=None, naive2_hi1=None,
                     naive2_feature2="max_posts_60min", naive2_lo2=None, naive2_hi2=None,
                     naive2_n_train=0, naive2_hit_train=float("nan"), naive2_n_sealed=n_se,
                     naive2_hit_sealed=hit_se, incremental_lift_over_naive2=float("nan"),
                     beats_naive2_sealed=None, incr_lift2_ci_lo=float("nan"), incr_lift2_ci_hi=float("nan"),
                     p_lift2_le_1=float("nan"), naive2_verdict="UNTESTABLE")
    inc = (rule_hit_sealed / hit_se) if (hit_se and hit_se > 0 and not math.isnan(rule_hit_sealed)) else float("nan")
    beats = (rule_hit_sealed > hit_se) if (n_se > 0 and not math.isnan(hit_se) and not math.isnan(rule_hit_sealed)) else None
    verdict = naive_verdict_from_ci(rule_hit_sealed, hit_se, ci)
    return dict(naive2_feature1="count_so_far", naive2_lo1=naive2["lo1"], naive2_hi1=naive2["hi1"],
                naive2_feature2="max_posts_60min", naive2_lo2=naive2["lo2"], naive2_hi2=naive2["hi2"],
                naive2_n_train=naive2["n_train"], naive2_hit_train=naive2["hit_train"],
                naive2_n_sealed=n_se, naive2_hit_sealed=hit_se,
                incremental_lift_over_naive2=inc, beats_naive2_sealed=beats,
                incr_lift2_ci_lo=(ci["ci_lo"] if ci else float("nan")),
                incr_lift2_ci_hi=(ci["ci_hi"] if ci else float("nan")),
                p_lift2_le_1=(ci["p_lift_le_1"] if ci else float("nan")),
                naive2_verdict=verdict)


def run_tree_extraction(name, train_units, sealed_units, checkpoints, is_qr, prior_final_fn_,
                         hp, n_eff_frac=None):
    finals_train = [u["final"] for u in train_units]
    edges = M.make_bin_edges(finals_train, hp["K"])
    labels = bin_labels_from_edges(edges)
    print(f"\n[M2/{name}] fitting on TRAIN-only ({len(train_units)} units), "
          f"K={hp['K']} bins={labels}, ccp_alpha={hp['ccp_alpha']}, "
          f"max_depth={TREE_MAX_DEPTH}, min_samples_leaf={TREE_MIN_SAMPLES_LEAF}")
    Xtr, ytr, provtr = build_M2_rows(train_units, checkpoints, elon_post_ts, is_qr,
                                      trailing_fn, prior_final_fn_, edges)
    clf = DecisionTreeClassifier(max_depth=TREE_MAX_DEPTH, min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
                                  ccp_alpha=hp["ccp_alpha"], random_state=0)
    clf.fit(Xtr, ytr)
    Xse, yse, provse = build_M2_rows(sealed_units, checkpoints, elon_post_ts, is_qr,
                                      trailing_fn, prior_final_fn_, edges)  # SAME frozen edges, no leak
    leaf_tr = clf.apply(Xtr)
    leaf_se = clf.apply(Xse) if len(Xse) else np.array([], dtype=int)
    paths = extract_leaf_paths(clf, M.FEATURE_NAMES)

    dftr = pd.DataFrame(provtr)
    dftr["leaf"], dftr["y"] = leaf_tr, ytr
    dfse = pd.DataFrame(provse)
    if len(dfse):
        dfse["leaf"], dfse["y"] = leaf_se, yse

    export_txt = export_text(clf, feature_names=M.FEATURE_NAMES)

    count_so_far_tr = Xtr[:, M.FEATURE_NAMES.index("count_so_far")]
    count_so_far_se = Xse[:, M.FEATURE_NAMES.index("count_so_far")] if len(Xse) else np.array([])
    max_burst_tr = Xtr[:, M.FEATURE_NAMES.index("max_posts_60min")]
    max_burst_se = Xse[:, M.FEATURE_NAMES.index("max_posts_60min")] if len(Xse) else np.array([])

    leaf_reports, rule_rows = [], []
    for leaf_id, path in sorted(paths.items()):
        sub_tr = dftr[dftr.leaf == leaf_id]
        n_tr = len(sub_tr)
        if n_tr == 0:
            continue
        counts_tr = sub_tr.y.value_counts().reindex(range(hp["K"]), fill_value=0)
        modal_bin = int(counts_tr.idxmax())
        hit_tr = float(counts_tr[modal_bin]) / n_tr
        sub_se = dfse[dfse.leaf == leaf_id] if len(dfse) else pd.DataFrame(columns=["y", "checkpoint_hours", "slug"])
        n_se = len(sub_se)
        hit_se = float((sub_se.y == modal_bin).mean()) if n_se else float("nan")
        base_rate_tr = float((ytr == modal_bin).mean())
        base_rate_se = float((yse == modal_bin).mean()) if len(yse) else float("nan")
        lift_tr = hit_tr / base_rate_tr if base_rate_tr > 0 else float("nan")
        lift_se = hit_se / base_rate_se if (n_se and base_rate_se and base_rate_se > 0) else float("nan")
        cps_tr = sorted(sub_tr.checkpoint_hours.unique().tolist())
        cps_se = sorted(sub_se.checkpoint_hours.unique().tolist()) if n_se else []
        rule_text = " AND ".join(format_condition(f, op, t, checkpoints=checkpoints) for f, op, t in path) \
            if path else "(root -- no split, tree is a stump)"
        if n_eff_frac is not None:
            n_eff_note = f" (n_eff~{int(round(n_tr * n_eff_frac))} after lag-1 autocorrelation discount)"
        else:
            # audit 2026-07-31 [D][LOW] fix: elon_2day is an overlapping-window
            # substrate whose lag-1 autocorrelation was never estimated in the
            # prereg (only "the daily substrate" rho=0.44 is scoped there, per
            # prereg/pattern_discovery_2026-07-26.md:74) -- say so explicitly
            # instead of silently leaving the field blank.
            n_eff_note = " (n_eff: UNQUANTIFIED for this substrate -- lag-1 autocorrelation was never " \
                         "estimated for overlapping elon_2day windows in the disclosed prereg; only the " \
                         "elon_daily rho=0.44 figure is scoped there, see prereg/pattern_discovery_2026-07-26.md:74)"

        # audit 2026-07-31 [D][MEDIUM] round-2 fix: n_tr/n_se above are CHECKPOINT-ROW
        # counts -- a single auction can hit multiple checkpoints (e.g. 6/12/15, or 18/21)
        # that all route to the SAME leaf, inflating n. The reliability gate (MIN_N_FLAG)
        # must run on unique AUCTIONS, never rows. Both are kept: n_train/n_sealed below
        # now report auctions (the gate basis); n_train_rows/n_sealed_rows preserve the
        # original checkpoint-row counts for transparency (nothing hidden).
        n_tr_auctions = int(sub_tr.slug.nunique())
        n_se_auctions = int(sub_se.slug.nunique()) if n_se else 0
        flag = (n_tr_auctions < MIN_N_FLAG) or (n_se_auctions > 0 and n_se_auctions < MIN_N_FLAG) or \
               (n_se_auctions == 0)
        jk = jackknife_loo_auction(sub_se.slug.values, sub_se.y.values == modal_bin) if n_se else None
        jk_fields = dict(jackknife_n_auctions=(jk["jk_n_auctions"] if jk else n_se_auctions),
                          jackknife_hit_min=(jk["jk_hit_min"] if jk else float("nan")),
                          jackknife_hit_max=(jk["jk_hit_max"] if jk else float("nan")))

        # audit 2026-07-31 [D][MEDIUM] fix (round-3: now a band search, see
        # fit_naive_threshold() docstring): single-feature naive baseline, fit on the
        # SAME pool (ALL units, not just this leaf) at this leaf's own decision
        # checkpoints. See fit_naive_threshold()/apply_naive_threshold() docstring.
        mask_cp_tr = dftr.checkpoint_hours.isin(cps_tr).values
        naive = fit_naive_threshold(count_so_far_tr[mask_cp_tr], ytr[mask_cp_tr] == modal_bin,
                                     min_n=TREE_MIN_SAMPLES_LEAF)
        naive_n_train_auctions = int(len(np.unique(
            dftr.slug.values[mask_cp_tr][naive_threshold_mask(naive, count_so_far_tr[mask_cp_tr])])))
        naive_ci = None
        if len(dfse) and cps_se:
            mask_cp_se = dfse.checkpoint_hours.isin(cps_se).values
            n_se_naive, hit_se_naive = apply_naive_threshold(
                naive, count_so_far_se[mask_cp_se], yse[mask_cp_se] == modal_bin)
            naive_mask_se = naive_threshold_mask(naive, count_so_far_se[mask_cp_se])
            naive_slugs_se = dfse.slug.values[mask_cp_se][naive_mask_se]
            naive_n_sealed_auctions = int(len(np.unique(naive_slugs_se)))
            # audit 2026-07-31 round-3 [D][HIGH] fix (finding #1): auction-level block
            # bootstrap of incremental_lift_over_naive -- see bootstrap_incremental_lift_ci()
            # docstring. Undefined (returns None -> UNTESTABLE-gated) if either side has <2
            # unique auctions, e.g. this is what disqualifies n_sealed=1 rows from SURVIVES.
            naive_ci = bootstrap_incremental_lift_ci(
                sub_se.slug.values, (sub_se.y.values == modal_bin),
                naive_slugs_se, (yse[mask_cp_se] == modal_bin)[naive_mask_se])
        else:
            mask_cp_se = np.array([], dtype=bool)
            n_se_naive, hit_se_naive = 0, float("nan")
            naive_n_sealed_auctions = 0
        naive_fields = naive_baseline_report(hit_se, naive, n_se_naive, hit_se_naive, ci=naive_ci)
        # audit 2026-07-31 [D][MEDIUM] round-2 fix: re-point naive_n_train/naive_n_sealed at
        # unique AUCTIONS too, so the rule's n and its own naive baseline's n are compared
        # like-for-like on the same unit. naive_hit_train/naive_hit_sealed/naive_lo/naive_hi/
        # incremental_lift_over_naive/beats_naive_sealed are UNCHANGED (still computed on the
        # original row-level masks) -- only the n labels are re-pointed. Row counts preserved
        # as naive_n_train_rows/naive_n_sealed_rows.
        naive_fields["naive_n_train_rows"] = naive_fields["naive_n_train"]
        naive_fields["naive_n_sealed_rows"] = naive_fields["naive_n_sealed"]
        naive_fields["naive_n_train"] = naive_n_train_auctions
        naive_fields["naive_n_sealed"] = naive_n_sealed_auctions

        # Carried forward from @backtest-auditor's independent 2026-07-31 re-audit: a
        # strictly HARDER two-feature (count_so_far AND max_posts_60min) naive baseline,
        # same non-tautological pool/checkpoints, TRAIN-fit/frozen/sealed-applied, now also
        # band-searched (round-3). See fit_naive_threshold_2d() docstring.
        naive2 = fit_naive_threshold_2d(count_so_far_tr[mask_cp_tr], max_burst_tr[mask_cp_tr],
                                         ytr[mask_cp_tr] == modal_bin, min_n=TREE_MIN_SAMPLES_LEAF)
        naive2_n_train_auctions = int(len(np.unique(
            dftr.slug.values[mask_cp_tr][naive_threshold_mask_2d(
                naive2, count_so_far_tr[mask_cp_tr], max_burst_tr[mask_cp_tr])])))
        naive2_ci = None
        if len(dfse) and cps_se:
            n_se_naive2, hit_se_naive2 = apply_naive_threshold_2d(
                naive2, count_so_far_se[mask_cp_se], max_burst_se[mask_cp_se], yse[mask_cp_se] == modal_bin)
            naive2_mask_se = naive_threshold_mask_2d(naive2, count_so_far_se[mask_cp_se], max_burst_se[mask_cp_se])
            naive2_slugs_se = dfse.slug.values[mask_cp_se][naive2_mask_se]
            naive2_n_sealed_auctions = int(len(np.unique(naive2_slugs_se)))
            naive2_ci = bootstrap_incremental_lift_ci(
                sub_se.slug.values, (sub_se.y.values == modal_bin),
                naive2_slugs_se, (yse[mask_cp_se] == modal_bin)[naive2_mask_se])
        else:
            n_se_naive2, hit_se_naive2 = 0, float("nan")
            naive2_n_sealed_auctions = 0
        naive2_fields = naive2_baseline_report(hit_se, naive2, n_se_naive2, hit_se_naive2, ci=naive2_ci)
        naive2_fields["naive2_n_train_rows"] = naive2_fields["naive2_n_train"]
        naive2_fields["naive2_n_sealed_rows"] = naive2_fields["naive2_n_sealed"]
        naive2_fields["naive2_n_train"] = naive2_n_train_auctions
        naive2_fields["naive2_n_sealed"] = naive2_n_sealed_auctions

        leaf_reports.append(dict(
            leaf_id=int(leaf_id), rule_text=rule_text, decision_checkpoints_train=cps_tr,
            decision_checkpoints_sealed=cps_se, modal_bin_label=labels[modal_bin],
            n_train=n_tr_auctions, n_train_rows=n_tr,
            train_outcome_dist={labels[i]: int(counts_tr[i]) for i in range(hp["K"])},
            train_hit_rate=hit_tr, n_sealed=n_se_auctions, n_sealed_rows=n_se,
            sealed_outcome_dist=({labels[i]: int((sub_se.y == i).sum()) for i in range(hp["K"])} if n_se else {}),
            sealed_hit_rate=hit_se, base_rate_train=base_rate_tr, base_rate_sealed=base_rate_se,
            lift_train=lift_tr, lift_sealed=lift_se, flag_small_n=flag, n_eff_note=n_eff_note,
            **jk_fields, **naive_fields, **naive2_fields))
        rule_rows.append(dict(
            source=f"CART-{name}", rule_id=f"M2-{name}-leaf{leaf_id}", target=name,
            rule_text=rule_text,
            decision_time=f"checkpoint hour(s) into window: train={cps_tr} sealed={cps_se}",
            decision_checkpoint_max=(max(cps_tr) if cps_tr else None),
            outcome=f"final count in bracket {labels[modal_bin]}",
            n_train=n_tr_auctions, n_train_rows=n_tr, n_sealed=n_se_auctions, n_sealed_rows=n_se,
            train_hit_rate=hit_tr, sealed_hit_rate=hit_se,
            base_rate_train=base_rate_tr, base_rate_sealed=base_rate_se,
            lift_train=lift_tr, lift_sealed=lift_se, flag_small_n=flag,
            **jk_fields, **naive_fields, **naive2_fields))
    return dict(clf=clf, edges=edges, labels=labels, export_text=export_txt,
                leaf_reports=leaf_reports, rule_rows=rule_rows,
                dftr=dftr, dfse=dfse, n_train_total=len(Xtr), n_sealed_total=len(Xse))


tree_daily = run_tree_extraction("elon_daily", daily_train, daily_sealed, CHECKPOINTS_DAILY,
                                  elon_is_qr, prior_final_fn_daily, DAILY_M2_HP, n_eff_frac=DAILY_N_EFF_FRAC)
tree_e2d = run_tree_extraction("elon_2day", e2d_train, e2d_sealed, CHECKPOINTS_2DAY,
                                elon_is_qr, prior_final_fn_e2d, E2D_M2_HP, n_eff_frac=None)

for name, tr in (("elon_daily", tree_daily), ("elon_2day", tree_e2d)):
    lines = [f"# Decision tree (M2 CART) -- {name}",
             "",
             "REFIT DISCLOSURE: the original study refits this tree WALK-FORWARD per decision-block ",
             "(no single tree was persisted). This is a single representative tree fit ONCE on the FULL ",
             "TRAIN-only span (same feature construction, same frozen hyperparameters disclosed in ",
             "pattern_discovery_out/summary.md), then walked forward onto the (unseen-by-the-tree) sealed ",
             "span to report generalization. Outcome label = M2's OWN quantile-bin-of-final-count target ",
             "(K bins, edges frozen from TRAIN only) -- NOT the same as the B1-B4 scoring brackets used ",
             "elsewhere in the study.",
             "",
             f"n_train_rows={tr['n_train_total']}  n_sealed_rows={tr['n_sealed_total']}  "
             f"bins={tr['labels']}",
             "",
             "## SUPERSESSION NOTICE (coordinator, 2026-07-31): a 5-site DST bug fix landed upstream in "
             "pattern_discovery_2026-07-26.py / pattern_discovery_methods.py AFTER this file's prior version "
             "was audited (parent re-run cold twice, byte-identical -- the fix is now frozen/verified). The "
             "daily window shifted for 126 training days, so this tree legitimately rebuilds from scratch: "
             "leaf IDs, bin edges, and leaf count below do NOT correspond 1:1 to any prior run of this script. "
             "ANY leaf4 / leaf7 / leaf11 / leaf15 / leaf21 citation from an earlier version of this file or its "
             "audit logs is SUPERSEDED and must not be cited against the leaves printed below -- read this "
             "tree fresh, on its own leaf numbering.",
             "",
             "## AUCTION-COUNT DISCLOSURE (audit 2026-07-31 [D][MEDIUM] round-2 fix)",
             "Per-leaf n_train/n_sealed below are unique AUCTIONS (distinct slug), never checkpoint-rows -- a "
             "single auction can hit multiple checkpoints (e.g. 6/12/15, or 18/21) that route to the SAME "
             "leaf, which can inflate a naive row count well past a leaf's true independent sample size. "
             "Checkpoint-row counts are preserved alongside as n_train_rows/n_sealed_rows for transparency; "
             "nothing is hidden, only re-labeled. flag_small_n (MIN_N_FLAG=30) is now gated on the auction "
             "count. A leave-one-auction-out jackknife of the sealed hit rate is printed under each leaf's "
             "SEALED line as the honest stability measure at these small sizes.",
             "",
             "## 2-FEATURE NAIVE BASELINE (carried forward from @backtest-auditor's 2026-07-31 re-audit probe, "
             "made permanent here)",
             "Every leaf below also reports a strictly HARDER adversarial baseline -- a threshold on "
             "count_so_far AND a threshold on max_posts_60min jointly (vs the 1-feature count_so_far-only "
             "baseline above it), fit the same way (TRAIN-only, same non-tautological pool, frozen, applied "
             "to sealed). A leaf that beats BOTH baselines is carrying information beyond running-count alone "
             "AND beyond burst-intensity alone -- a stronger claim than beating either one individually.",
             ""]
    if name == "elon_daily":
        lines += [
            "## CAVEAT (audit 2026-07-31 [D][MEDIUM]): late-window leaves mostly restate a declared trivial null",
            "The parent study's OWN prereg-declared null (pattern_discovery_out/summary.md, 'Null-model check' "
            "section, post-DST-fix re-run, confirming prereg/pattern_discovery_2026-07-26.md:71): "
            "R2(count_so_far -> final count), Elon daily: hour18=0.744, hour21=0.870 (prereg declared 0.76 / "
            "0.93 -- confirmed, same order of magnitude; these are updated from the pre-DST-fix values "
            "0.764/0.856 an earlier version of this file cited). In plain terms: by the checkpoint-18/21 "
            "decision times (06:00/09:00 ET the next day), count_so_far ALONE already explains 74-87% of the "
            "variance in the final count, "
            "with zero modelling. ANY leaf below whose printed 'decision time (checkpoint hours into window)' "
            "is [18] and/or [21] ONLY (check each leaf's own printed checkpoints below -- the tree's split "
            "threshold on hours_into_window is refit per run and is NOT guaranteed to land at any particular "
            "value, so do not pattern-match on a hardcoded threshold number) is necessarily built mostly out "
            "of that null, not a new discriminative structure. The NAIVE 1-threshold baseline line under each "
            "leaf below (fit "
            "identically to that leaf's own decision checkpoints, on the same universe of rows, TRAIN-only, "
            "frozen, applied to sealed) is the honest test of how much a leaf adds BEYOND that null. See the "
            "'Naive-baseline summary' at the end of this file for which leaves survive that test and which "
            "collapse to it.",
            "",
            "## sklearn.tree.export_text (raw fidelity)",
            tr["export_text"],
            "",
            "## Hand-formatted leaves (every leaf printed, including thin/failing ones)",
            ""]
    else:
        lines += [
            "## sklearn.tree.export_text (raw fidelity)",
            tr["export_text"],
            "",
            "## Hand-formatted leaves (every leaf printed, including thin/failing ones)",
            ""]
    for r in tr["leaf_reports"]:
        flag = "  [FLAG: n<30 auctions]" if r["flag_small_n"] else ""
        lines.append(f"- LEAF {r['leaf_id']}: {r['rule_text']}")
        lines.append(f"    -> modal outcome: final count {r['modal_bin_label']}{flag}")
        lines.append(f"    decision time (checkpoint hours into window): train={r['decision_checkpoints_train']} "
                      f"sealed={r['decision_checkpoints_sealed']}")
        lines.append(f"    TRAIN:  n={r['n_train']} auctions ({r['n_train_rows']} checkpoint-rows)"
                      f"{r['n_eff_note']}  dist={r['train_outcome_dist']}  "
                      f"hit_rate={r['train_hit_rate']*100:.1f}%  base_rate={r['base_rate_train']*100:.1f}%  "
                      f"lift={r['lift_train']:.2f}x")
        se_line = (f"    SEALED: n={r['n_sealed']} auctions ({r['n_sealed_rows']} checkpoint-rows)  "
                   f"dist={r['sealed_outcome_dist']}  "
                   f"hit_rate={r['sealed_hit_rate']*100:.1f}%  base_rate={r['base_rate_sealed']*100:.1f}%  "
                   f"lift={r['lift_sealed']:.2f}x" if r["n_sealed"] > 0 else
                   "    SEALED: n=0 -- no sealed-span row ever reached this leaf (untestable OOS)")
        lines.append(se_line)
        if r["n_sealed"] > 0:
            if math.isnan(r["jackknife_hit_min"]):
                lines.append(f"    SEALED jackknife (leave-one-auction-out): insufficient distinct auctions "
                              f"(n={r['jackknife_n_auctions']}) -- undefined at n<2")
            else:
                lines.append(f"    SEALED jackknife (leave-one-auction-out, n_auctions="
                              f"{r['jackknife_n_auctions']}): hit_rate range "
                              f"[{r['jackknife_hit_min']*100:.1f}%, {r['jackknife_hit_max']*100:.1f}%] "
                              f"(full sealed hit_rate={r['sealed_hit_rate']*100:.1f}%)")
        if r["naive_kind"] is None:
            lines.append("    NAIVE baseline (count_so_far, band-or-one-sided search, same pool/checkpoints, "
                          "TRAIN-fit, frozen): no band reached n>=25 in the train pool -- baseline unavailable")
        else:
            hit_se_naive_str = f"{r['naive_hit_sealed']*100:.1f}%" if not math.isnan(r["naive_hit_sealed"]) else "n/a"
            inc_str = f"{r['incremental_lift_over_naive']:.2f}x" if not math.isnan(r["incremental_lift_over_naive"]) else "n/a"
            point_verdict = ("beats naive on point estimate" if r["beats_naive_sealed"] is True else
                              "does not beat naive on point estimate" if r["beats_naive_sealed"] is False else
                              "naive baseline has no sealed rows either")
            ci_str = (f"95% CI(incremental_lift)=[{r['incr_lift_ci_lo']:.2f}x, {r['incr_lift_ci_hi']:.2f}x] "
                      f"P(lift<=1.0)={r['p_lift_le_1']*100:.1f}%"
                      if not math.isnan(r["incr_lift_ci_lo"]) else
                      "CI UNDEFINED (fewer than 2 unique auctions on rule and/or naive side)")
            lines.append(f"    NAIVE baseline (audit 2026-07-31 round-3: band-or-one-sided search over "
                         f"{_fmt_band(r['naive_lo'], r['naive_hi'], r['naive_kind'])}, same pool/checkpoints, "
                         f"TRAIN-fit n={r['naive_n_train']} auctions ({r['naive_n_train_rows']} rows) "
                         f"hit={r['naive_hit_train']*100:.1f}%, frozen): SEALED n={r['naive_n_sealed']} auctions "
                         f"({r['naive_n_sealed_rows']} rows) hit={hit_se_naive_str}  "
                         f"incremental_lift_over_naive={inc_str} ({point_verdict})")
            lines.append(f"      auction-level block-bootstrap ({N_BOOT} resamples, independent per side): "
                         f"{ci_str}  -> CI-GATED VERDICT: {r['naive_verdict']}")
        if r["naive2_lo1"] is None:
            lines.append("    NAIVE 2-feature baseline (count_so_far AND max_posts_60min, band-or-one-sided "
                          "search on each, same pool/checkpoints, TRAIN-fit, frozen -- carried forward from "
                          "@backtest-auditor's 2026-07-31 re-audit probe): no combined band reached n>=25 in "
                          "the train pool -- baseline unavailable")
        else:
            hit_se_naive2_str = f"{r['naive2_hit_sealed']*100:.1f}%" if not math.isnan(r["naive2_hit_sealed"]) else "n/a"
            inc2_str = f"{r['incremental_lift_over_naive2']:.2f}x" if not math.isnan(r["incremental_lift_over_naive2"]) else "n/a"
            point_verdict2 = ("beats 2-feature naive on point estimate" if r["beats_naive2_sealed"] is True else
                               "does not beat 2-feature naive on point estimate" if r["beats_naive2_sealed"] is False else
                               "2-feature naive baseline has no sealed rows either")
            ci2_str = (f"95% CI(incremental_lift)=[{r['incr_lift2_ci_lo']:.2f}x, {r['incr_lift2_ci_hi']:.2f}x] "
                       f"P(lift<=1.0)={r['p_lift2_le_1']*100:.1f}%"
                       if not math.isnan(r["incr_lift2_ci_lo"]) else
                       "CI UNDEFINED (fewer than 2 unique auctions on rule and/or naive side)")
            lines.append(f"    NAIVE 2-feature baseline ({_fmt_band(r['naive2_lo1'], r['naive2_hi1'], 'band', 'count_so_far')} "
                         f"AND {_fmt_band(r['naive2_lo2'], r['naive2_hi2'], 'band', 'max_posts_60min')}, same "
                         f"pool/checkpoints, TRAIN-fit n={r['naive2_n_train']} auctions "
                         f"({r['naive2_n_train_rows']} rows) hit={r['naive2_hit_train']*100:.1f}%, frozen -- "
                         f"carried forward from @backtest-auditor's 2026-07-31 re-audit probe, now band-searched): "
                         f"SEALED n={r['naive2_n_sealed']} auctions ({r['naive2_n_sealed_rows']} rows) "
                         f"hit={hit_se_naive2_str}  incremental_lift_over_naive2={inc2_str} ({point_verdict2})")
            lines.append(f"      auction-level block-bootstrap ({N_BOOT} resamples, independent per side): "
                         f"{ci2_str}  -> CI-GATED VERDICT: {r['naive2_verdict']}")
        lines.append("")

    # audit 2026-07-31 round-3 [D][HIGH] fix (finding #1): the scorecard below is now
    # CI-GATED (naive_verdict), a THREE-category outcome, not the raw point-estimate
    # boolean (beats_naive_sealed) alone. SURVIVES requires the auction-level bootstrap CI
    # on incremental_lift_over_naive to EXCLUDE 1.0 (ci_lo>1.0); a rule whose point estimate
    # beats naive but whose CI straddles 1.0 is UNPROVEN, a distinct category from COLLAPSES
    # (point estimate at or below naive) and from UNTESTABLE (no naive baseline/no sealed
    # rows/bootstrap undefined, e.g. n_sealed<2 auctions on either side -- this is what
    # disqualifies the n_sealed=1 M2-elon_2day-leaf6 row from ever reading SURVIVES).
    survives = [r for r in tr["leaf_reports"] if r["naive_verdict"] == "SURVIVES"]
    unproven = [r for r in tr["leaf_reports"] if r["naive_verdict"] == "UNPROVEN"]
    collapses = [r for r in tr["leaf_reports"] if r["naive_verdict"] == "COLLAPSES"]
    untestable = [r for r in tr["leaf_reports"] if r["naive_verdict"] == "UNTESTABLE"]
    old_point_survives = [r for r in tr["leaf_reports"] if r["beats_naive_sealed"] is True]
    old_point_survives_ids = [f"leaf{r['leaf_id']}" for r in old_point_survives]
    n_moved_to_unproven = len([r for r in old_point_survives if r["naive_verdict"] != "SURVIVES"])
    early_survives = [r for r in survives if max(r["decision_checkpoints_train"] or [0]) <= 15]
    survives_ids = [f"leaf{r['leaf_id']}" for r in survives]
    unproven_ids = [f"leaf{r['leaf_id']}" for r in unproven]
    collapses_ids = [f"leaf{r['leaf_id']}" for r in collapses]
    untestable_ids = [f"leaf{r['leaf_id']}" for r in untestable]
    early_survives_desc = [f"leaf{r['leaf_id']} (incremental_lift_over_naive="
                            f"{r['incremental_lift_over_naive']:.2f}x, CI=[{r['incr_lift_ci_lo']:.2f}x,"
                            f"{r['incr_lift_ci_hi']:.2f}x])" for r in early_survives]
    lines.append("## Naive-baseline summary (audit 2026-07-31 round-3 [D][HIGH] fix: band search + "
                 "CI-gated 3-category verdict)")
    lines.append(f"  {len(survives)}/{len(tr['leaf_reports'])} leaves SURVIVE (incremental-lift-over-naive "
                 f"95% auction-level bootstrap CI EXCLUDES 1.0): {survives_ids or 'none'}")
    lines.append(f"  {len(unproven)}/{len(tr['leaf_reports'])} leaves UNPROVEN (point estimate beats naive, "
                 f"but the CI straddles 1.0 -- not distinguishable from no edge at this n, OR the CI is "
                 f"undefined because rule/naive side has <2 unique sealed auctions): {unproven_ids or 'none'}")
    lines.append(f"  {len(collapses)}/{len(tr['leaf_reports'])} leaves COLLAPSE (point estimate at or below "
                 f"naive -- most of their apparent accuracy is the naive baseline's, not the extra "
                 f"conditions'): {collapses_ids or 'none'}")
    lines.append(f"  {len(untestable)}/{len(tr['leaf_reports'])} leaves UNTESTABLE (naive baseline itself "
                 f"has 0 sealed rows at that leaf's checkpoints, or train pool never reached n>=25 for any "
                 f"band): {untestable_ids or 'none'}")
    lines.append(f"  (for reference, the OLD point-estimate-only scorecard -- pre-CI-gate -- would have "
                 f"called {len(old_point_survives)}/{len(tr['leaf_reports'])} leaves SURVIVE: "
                 f"{old_point_survives_ids or 'none'}; the CI gate moved {n_moved_to_unproven} of those "
                 f"into UNPROVEN)")
    if early_survives:
        lines.append(f"  EARLY rules (checkpoints <=15, i.e. hour 6/12/15 -- 18:00 ET/00:00 ET/03:00 ET, "
                     f"where the parent's trivial null is far weaker) that SURVIVE (CI-gated) the naive "
                     f"comparison: {early_survives_desc} "
                     f"-- THIS is the real finding of this pass if present: a genuinely early, non-trivial signal.")
    else:
        lines.append("  No EARLY rule (checkpoints <=15) SURVIVES (CI-gated) the naive comparison in this tree.")

    reliable_survives = [r for r in survives if r["n_sealed"] >= MIN_N_FLAG]
    reliable_survives_ids = [f"leaf{r['leaf_id']}" for r in reliable_survives]
    lines.append(f"  Of the {len(survives)} CI-gated 1-feature survivors, {len(reliable_survives)} also clear "
                 f"the n_sealed>=30 AUCTION reliability floor: {reliable_survives_ids or 'none'}")

    survives2 = [r for r in survives if r["naive2_verdict"] == "SURVIVES"]
    survives2_ids = [f"leaf{r['leaf_id']}" for r in survives2]
    not2 = [r for r in survives if r["naive2_verdict"] != "SURVIVES"]
    not2_ids = [f"leaf{r['leaf_id']}" for r in not2]
    lines.append("## 2-feature (count_so_far AND max_posts_60min) naive-baseline cross-check "
                 "(carried forward from @backtest-auditor's 2026-07-31 re-audit probe, made permanent here, "
                 "now band-searched + CI-gated)")
    lines.append(f"  Of the {len(survives)} CI-gated 1-feature survivors, "
                 f"{len(survives2)} ALSO CI-gated-SURVIVE against this strictly harder 2-feature adversary on "
                 f"sealed data: {survives2_ids or 'none'} -- these carry information beyond running-count AND "
                 f"beyond burst-intensity alone, individually, with statistical confidence at this n.")
    if not2:
        lines.append(f"  {len(not2)} 1-feature CI-gated survivor(s) do NOT also CI-gated-SURVIVE the "
                     f"2-feature bar: {not2_ids}")
    (OUT_DIR / f"decision_tree_{name}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"[output] {OUT_DIR / f'decision_tree_{name}.txt'} ({len(tr['leaf_reports'])} leaves)")


# ===========================================================================
# SECTION 2 -- DAY ARCHETYPES (M3 KMeans), daily target only (by construction)
# ===========================================================================
def day_shape_vec(post_ts, s):
    return np.array([L.obs_count(post_ts, s + h * 3600, s + (h + 1) * 3600) for h in range(24)], dtype=float)


def full_cluster_assign(centroids, shape_vec):
    tot = shape_vec.sum()
    if tot <= 0:
        return None
    cl, _ = M._assign_cluster(centroids, shape_vec / tot)
    return cl


def partial_cluster_assign(centroids, shape_vec, H):
    """Mirrors pattern_discovery_methods.py::predict_M3's partial-shape
    assignment math exactly (lines computing cent_partial/partial_norm/dist)."""
    partial = shape_vec[:H]
    o = partial.sum()
    if o <= 0:
        return None
    partial_norm = partial / o
    cent_partial = centroids[:, :H]
    cent_partial = cent_partial / np.clip(cent_partial.sum(axis=1, keepdims=True), 1e-6, None)
    dist = np.sqrt(np.sum((cent_partial - partial_norm) ** 2, axis=1))
    return int(np.argmin(dist))


print(f"\n[M3] fitting KMeans day-shape centroids on TRAIN-only ({len(daily_train)} days), k={DAILY_M3_K}")
m3_centroids_state = M.fit_M3_centroids(daily_train, elon_post_ts, DAILY_M3_K)
centroids = m3_centroids_state["centroids"]  # shape (k, 24), index h=0 -> ET 12:00 (window start)

PERIODS = [("overnight 00-05 ET", range(0, 6)), ("morning 06-11 ET", range(6, 12)),
           ("afternoon 12-17 ET", range(12, 18)), ("evening 18-23 ET", range(18, 24))]


def centroid_to_et_profile(centroid):
    et = np.zeros(24)
    for h in range(24):
        et[(12 + h) % 24] = centroid[h]
    return et


def describe_centroid(centroid):
    et = centroid_to_et_profile(centroid)
    shares = [(name, float(sum(et[h] for h in hrs))) for name, hrs in PERIODS]
    dominant = max(shares, key=lambda x: x[1])
    desc = ", ".join(f"{name} {s*100:.0f}%" for name, s in shares)
    return desc, dominant[0], et


H_GRID = [1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 21, 24]

all_days_full = []
for d in daily_train:
    v = day_shape_vec(elon_post_ts, d["s"])
    cl = full_cluster_assign(centroids, v)
    all_days_full.append(dict(slug=d["slug"], s=d["s"], final=d["final"], shape=v, cluster=cl, span="train"))
for d in daily_sealed:
    v = day_shape_vec(elon_post_ts, d["s"])
    cl = full_cluster_assign(centroids, v)
    all_days_full.append(dict(slug=d["slug"], s=d["s"], final=d["final"], shape=v, cluster=cl, span="sealed"))

# NOTE (found while extracting, disclosed rather than silently reported): at
# H=1, predict_M3's own normalization (cent_partial /= cent_partial.sum(axis=1))
# divides a SINGLE column by its own sum, which is 1.0 for every cluster and
# every observed partial shape whenever ANY posts have occurred (x/x==1.0
# regardless of x) -- so at H=1 every cluster is EQUIDISTANT (distance=0) and
# argmin silently always returns cluster index 0. This is an inherent artifact
# of the original study's predict_M3 formula at very small H, not a bug
# introduced here. Days with ZERO posts in [0,H) return None (unassignable) --
# these are now tracked SEPARATELY (not silently counted as a miss) so the
# reported accuracy is conditional on "shape is assignable at all by hour H".
acc_rows = []  # overall accuracy (partial matches own eventual full-day cluster), conditional on assignable
recall_rows = []  # per-cluster recall, conditional on assignable
for H in H_GRID:
    for span in ("train", "sealed"):
        days = [d for d in all_days_full if d["span"] == span and d["cluster"] is not None]
        n_total = len(days)
        if n_total == 0:
            continue
        assigns = [(d, partial_cluster_assign(centroids, d["shape"], H)) for d in days]
        assignable = [(d, a) for d, a in assigns if a is not None]
        n_unassignable = n_total - len(assignable)
        if assignable:
            matches = [1 if a == d["cluster"] else 0 for d, a in assignable]
            acc = float(np.mean(matches))
        else:
            acc = float("nan")
        acc_rows.append(dict(hours_elapsed=H, et_clock=f"{(12+H)%24:02d}:00", span=span,
                              accuracy=acc, n_assignable=len(assignable), n_unassignable=n_unassignable,
                              n_total=n_total,
                              degenerate_tie_at_H1=(H == 1)))
        for cl in range(DAILY_M3_K):
            sub = [(d, a) for d, a in assignable if d["cluster"] == cl]
            n_sub_total = len([d for d in days if d["cluster"] == cl])
            if n_sub_total == 0:
                continue
            m = [1 if a == cl else 0 for d, a in sub]
            recall_rows.append(dict(hours_elapsed=H, cluster=cl, span=span,
                                     recall=(float(np.mean(m)) if sub else float("nan")),
                                     n=len(sub), n_total=n_sub_total))

acc_df = pd.DataFrame(acc_rows)
recall_df = pd.DataFrame(recall_rows)
acc_df.to_csv(OUT_DIR / "day_archetype_early_id_accuracy.csv", index=False)
recall_df.to_csv(OUT_DIR / "day_archetype_early_id_recall_by_cluster.csv", index=False)

lines = ["# Day archetypes (M3 KMeans day-shape clustering) -- elon_daily only",
         "",
         "By construction (prereg + disclosure) this method applies ONLY to the daily target: a 24-dim ",
         "shape vector does not generalize to a 48h/168h window.",
         "",
         "REFIT DISCLOSURE: centroids were NOT persisted by the original run. Refit here via ",
         f"M.fit_M3_centroids on the exact TRAIN-only daily span (same as the audited run), k={DAILY_M3_K} "
         "(disclosed, frozen, never re-selected here). Per prereg, M3 centroids are fit ONCE on TRAIN and "
         "FROZEN (unlike the other methods' walk-forward refit) -- this is the same rule the original study "
         "used, not a new choice.",
         "",
         f"k={DAILY_M3_K} clusters selected (disclosed run_dstfix_2026-07-31.log, post-DST-fix -- supersedes "
         f"the pre-fix M3_k=4 an earlier version of this file cited)",
         ""]

for cl in range(DAILY_M3_K):
    desc, dominant, et_profile = describe_centroid(centroids[cl])
    train_days = [d for d in all_days_full if d["span"] == "train" and d["cluster"] == cl]
    sealed_days = [d for d in all_days_full if d["span"] == "sealed" and d["cluster"] == cl]
    n_tr, n_se = len(train_days), len(sealed_days)
    freq_tr = n_tr / max(1, len([d for d in all_days_full if d["span"] == "train"]))
    freq_se = n_se / max(1, len([d for d in all_days_full if d["span"] == "sealed"]))
    finals_tr = [d["final"] for d in train_days]
    finals_se = [d["final"] for d in sealed_days]
    lines.append(f"## Archetype {cl} -- dominant period: {dominant}")
    lines.append(f"  Hour-by-hour ET profile (share of the day's posts by hour):")
    prof_str = "  ".join(f"{h:02d}h:{et_profile[h]*100:4.1f}%" for h in range(24))
    lines.append(f"    {prof_str}")
    lines.append(f"  Plain description: {desc}")
    lines.append(f"  Frequency: {n_tr}/{len([d for d in all_days_full if d['span']=='train'])} train days "
                 f"({freq_tr*100:.1f}%), {n_se}/{len([d for d in all_days_full if d['span']=='sealed'])} "
                 f"sealed days ({freq_se*100:.1f}%){'  [FLAG: n<30 train]' if n_tr < MIN_N_FLAG else ''}")
    if finals_tr:
        lines.append(f"  Final-count distribution TRAIN: mean={np.mean(finals_tr):.1f} "
                     f"median={np.median(finals_tr):.1f} min={min(finals_tr)} max={max(finals_tr)} n={n_tr}")
    if finals_se:
        lines.append(f"  Final-count distribution SEALED: mean={np.mean(finals_se):.1f} "
                     f"median={np.median(finals_se):.1f} min={min(finals_se)} max={max(finals_se)} n={n_se}")
    else:
        lines.append("  Final-count distribution SEALED: n=0 -- no sealed day assigned to this archetype")
    # earliest hour with per-cluster recall >= 70%, else report the max achieved.
    # H=1 excluded from this search: predict_M3's own normalization degenerates
    # there (see note above acc_rows/recall_rows construction) -- any apparent
    # "hit" at H=1 would be the tie artifact, not real early discrimination.
    cl_curve = recall_df[(recall_df.cluster == cl) & (recall_df.span == "train") &
                          (recall_df.hours_elapsed > 1)].sort_values("hours_elapsed")
    hit70 = cl_curve[cl_curve.recall >= 0.70]
    if len(hit70):
        h_id = int(hit70.iloc[0].hours_elapsed)
        lines.append(f"  Early identifiability (TRAIN, recall>=70% threshold): first reached at hour "
                     f"{h_id} into the window (~{(12+h_id)%24:02d}:00 ET), recall="
                     f"{hit70.iloc[0].recall*100:.0f}% (n={int(hit70.iloc[0].n)})")
    elif len(cl_curve):
        best = cl_curve.loc[cl_curve.recall.idxmax()]
        lines.append(f"  Early identifiability (TRAIN): NEVER reaches 70% recall in the tested grid -- "
                     f"best is {best.recall*100:.0f}% at hour {int(best.hours_elapsed)} "
                     f"(n={int(best.n)}). A cluster only nameable this late is not useful for early action.")
    lines.append("")

lines.append("## Overall early-identifiability curve (partial-shape assignment vs. that SAME day's own "
             "eventual full-24h assignment -- a descriptive property of shape structure, not a live bet; "
             "decision time for accuracy at hour H = day_start + H hours, strictly causal)")
lines.append("CAVEAT (found during extraction): at H=1 the original predict_M3 normalization divides a "
             "single-column centroid slice by its own sum, which is always exactly 1.0 for EVERY cluster "
             "whenever any posts occurred -- all clusters tie at distance=0 and argmin silently always "
             "returns cluster 0. H=1 numbers below are dominated by this tie artifact, not real early "
             "signal; treat H>=2-3 as the first meaningful readings. 'n_unassignable' = days with zero "
             "posts observed in [0,H) (partial_cluster_assign returns None, EXCLUDED from the accuracy "
             "denominator here, not counted as a miss).")
for _, r in acc_df.sort_values(["span", "hours_elapsed"]).iterrows():
    tie_note = "  [DEGENERATE: H=1 tie artifact, see caveat]" if r.degenerate_tie_at_H1 else ""
    acc_str = f"{r.accuracy*100:5.1f}%" if pd.notna(r.accuracy) else "  n/a"
    lines.append(f"  hour={int(r.hours_elapsed):2d} (~{r.et_clock} ET)  span={r.span:6s}  "
                 f"accuracy={acc_str}  n_assignable={int(r.n_assignable)}  "
                 f"n_unassignable(no posts yet)={int(r.n_unassignable)}  n_total={int(r.n_total)}{tie_note}")
(OUT_DIR / "day_archetypes.txt").write_text("\n".join(lines), encoding="utf-8")
print(f"[output] {OUT_DIR / 'day_archetypes.txt'}  ({DAILY_M3_K} archetypes)")


# ===========================================================================
# SECTION 3 -- HMM STATES (M4), elon_daily PRIMARY (the +0.121 skill model) +
#              elon_2day secondary/brief
# ===========================================================================
def hmm_report(name, train_units, n_states, out_lines, cap=40):
    print(f"\n[M4/{name}] fitting PoissonHMM on TRAIN-only ({len(train_units)} units, capped to last 40 "
          f"per fit_M4's disclosed cap=40 default), n_states={n_states}")
    st = M.fit_M4(train_units, elon_post_ts, n_states)
    if st is None:
        out_lines.append(f"## {name}: HMM fit FAILED (insufficient data or non-convergence) -- reported plainly")
        return None
    # fit_M4 itself only returns {model, converged} -- replicate its own disclosed
    # cap=40/len>4 sequence filter here (read-only) purely to report n_events/n_seqs.
    use = train_units[-cap:]
    seqs_for_count = [M._hourly_seq(elon_post_ts, p["s"], p["e"]) for p in use]
    seqs_for_count = [x for x in seqs_for_count if len(x) > 4]
    st["n_events"] = int(sum(x.sum() for x in seqs_for_count))
    st["n_seqs"] = len(seqs_for_count)
    model = st["model"]
    lambdas = np.asarray(model.lambdas_).reshape(-1)
    order = np.argsort(lambdas)  # ascending: 0=lowest-rate state
    lam_sorted = lambdas[order]
    trans_sorted = model.transmat_[np.ix_(order, order)]
    start_sorted = model.startprob_[order]
    if n_states == 3:
        state_names = ["Low", "Mid", "High"]
    elif n_states == 4:
        state_names = ["Low", "Mid1", "Mid2", "High"]
    else:
        state_names = [f"S{i}" for i in range(n_states)]

    out_lines.append(f"## {name}: n_states={n_states}, converged={st['converged']}, "
                     f"n_events={st['n_events']}, n_sequences_used={st['n_seqs']}")
    out_lines.append("")
    out_lines.append("State posting rates (hourly Poisson lambda, ascending):")
    for i, nm in enumerate(state_names):
        dur = 1.0 / max(1e-6, 1 - trans_sorted[i, i])
        p_next_hr = 1.0 - math.exp(-lam_sorted[i])
        out_lines.append(f"  {nm:5s}: lambda={lam_sorted[i]:.3f} posts/hour (~{lam_sorted[i]*24:.1f}/day)  "
                         f"self-transition(stickiness)={trans_sorted[i,i]*100:.1f}%  "
                         f"expected duration={dur:.1f}h  "
                         f"P(>=1 post in next hour | in this state)={p_next_hr*100:.1f}%  "
                         f"start_prob={start_sorted[i]*100:.1f}%")
    out_lines.append("")
    out_lines.append("Full transition matrix (row=from, col=to; sorted low->high rate):")
    hdr = "         " + "  ".join(f"{nm:>7s}" for nm in state_names)
    out_lines.append(hdr)
    for i, nm in enumerate(state_names):
        row = "  ".join(f"{trans_sorted[i,j]*100:6.1f}%" for j in range(n_states))
        out_lines.append(f"  {nm:5s}  {row}")
    out_lines.append("")
    return dict(model=model, order=order, state_names=state_names, lam_sorted=lam_sorted, trans_sorted=trans_sorted)


def causal_state_path(model, seq, order):
    """Filtered (causal) state estimate at each hour h, using ONLY obs[:h+1] --
    NOT sklearn's smoothed .predict() Viterbi, which would look at future hours
    within the same day (a WALL violation for a 'live' interpretation). Matches
    the exact causal mechanism predict_M4_pmf uses live (score_samples on the
    prefix, take the posterior at the LAST timestep)."""
    out = []
    for h in range(1, len(seq) + 1):
        sub = seq[:h].reshape(-1, 1)
        try:
            _, post = model.score_samples(sub)
            pi = post[-1]
        except Exception:
            out.append(None)
            continue
        raw_state = int(np.argmax(pi))
        sorted_label = int(np.where(order == raw_state)[0][0])
        out.append(sorted_label)
    return out


hmm_lines = ["# HMM states (M4 PoissonHMM) -- elon_daily is PRIMARY (the model with real skill: "
             "M4 vs B1 skill=+0.1210 CI[+0.0286,+0.2056] n=87 sealed, per pattern_discovery_out/summary.md)",
             "",
             "REFIT DISCLOSURE: the HMM was NOT persisted by the original run (refit walk-forward per "
             "decision-block there). Refit here ONCE via M.fit_M4 on the TRAIN-only daily span with the "
             "disclosed n_states=3 and the function's own disclosed cap=40 default (uses the last 40 of "
             "the 198 train days -- i.e. the most recent train-era regime, exactly matching the walk-forward "
             "cap the study used everywhere else), never re-selected here.",
             ""]
hmm_daily = hmm_report("elon_daily", daily_train, DAILY_M4_STATES, hmm_lines)

if hmm_daily is not None:
    finals_tr_arr = [(d["final"], d) for d in daily_train]
    finals_tr_arr.sort(key=lambda x: x[0])
    low_day = finals_tr_arr[0][1]
    high_day = finals_tr_arr[-1][1]
    hmm_lines.append("## Illustration: state sequence, a HIGH day vs a LOW day (TRAIN span, for illustration "
                     "only -- full day shown post-hoc; each hour's decoded state is itself causal, using "
                     "only that day's own posts up to and including that hour)")
    for label, day in (("LOW", low_day), ("HIGH", high_day)):
        seq = M._hourly_seq(elon_post_ts, day["s"], day["e"])
        path = causal_state_path(hmm_daily["model"], seq, hmm_daily["order"])
        hmm_lines.append(f"  {label} day {day['slug']} (final={day['final']}):")
        for h in range(len(seq)):
            et = (12 + h) % 24
            nm = hmm_daily["state_names"][path[h]] if path[h] is not None else "?"
            hmm_lines.append(f"    hour {h:2d} (~{et:02d}:00 ET)  posts_this_hour={int(seq[h])}  state={nm}")
        hmm_lines.append("")

print(f"\n[M4/elon_2day] fitting PoissonHMM on TRAIN-only ({len(e2d_train)} units), n_states={E2D_M4_STATES} "
      f"(secondary/brief per task scope -- elon_daily is primary)")
hmm_lines.append("## elon_2day (secondary, brief -- structure only, no day-by-day illustration)")
hmm_e2d = hmm_report("elon_2day", e2d_train, E2D_M4_STATES, hmm_lines)

(OUT_DIR / "hmm_states.txt").write_text("\n".join(hmm_lines), encoding="utf-8")
print(f"[output] {OUT_DIR / 'hmm_states.txt'}")


# ===========================================================================
# SECTION 4 -- HAZARD CURVE (M5), elon_daily
# ===========================================================================
print(f"\n[M5] fitting GradientBoostingClassifier hazard model on TRAIN-only ({len(daily_train)} days, "
      f"capped to last 40 per fit_M5's disclosed cap=40 default), n_estimators={DAILY_M5_HP['n_estimators']}, "
      f"max_depth={DAILY_M5_HP['max_depth']}")
m5_state = M.fit_M5(daily_train, elon_post_ts, elon_is_qr, trailing_fn, prior_final_fn_daily,
                     n_estimators=DAILY_M5_HP["n_estimators"], max_depth=DAILY_M5_HP["max_depth"])
clf5 = m5_state["clf"]

train_finals_arr = np.array([d["final"] for d in daily_train], dtype=float)
pf_med = float(np.median(train_finals_arr))
t7_vals = [trailing_fn(d["s"]) for d in daily_train]
t7_vals = [v for v in t7_vals if v is not None]
t7_med = float(np.median(t7_vals)) if t7_vals else pf_med
mask_train_posts = elon_post_ts < WALL_ELON
share_qr_med = float(elon_is_qr[mask_train_posts].mean())
print(f"[M5] representative fixed covariates (held constant across the table): "
     f"prior_window_final={pf_med:.1f}, trailing_7d_mean={t7_med:.1f}, share_qr={share_qr_med:.3f}, dow=2(Wed)")


FEAT_IMPORTANCE = dict(zip(M.M5_FEATURE_NAMES, clf5.feature_importances_.tolist()))
print(f"[M5] feature importances: {FEAT_IMPORTANCE}")


def hazard_p15(hrs_silence, et_hour, posts_so_far, dow=2.0):
    """hrs_silence in {0,1,2,4,6} sets posts_last_1h/3h/6h to REALISTIC COUNT
    values consistent with genuine silence of that duration (0 for every
    lookback window the silence has lasted), not just a 0/1 flag -- a first
    draft of this probe used booleans and produced bit-identical rows for
    hrs_silence in {1,2,4,6}; verified by direct predict_proba perturbation
    (see FEAT_IMPORTANCE / disclosure note below) that this was the model's
    genuine behavior at boolean-scale inputs, not a code bug -- posts_last_1h
    dominates (~70% importance) and posts_last_3h/6h only move the estimate
    at COUNT values >=6, never at 0-vs-1. This version uses count-consistent
    zeros for the silent windows, which is the honest encoding either way
    (silence of 3h genuinely means posts_last_3h=0, not 1)."""
    h1 = 0.0 if hrs_silence >= 1 else 1.0
    h3 = 0.0 if hrs_silence >= 3 else 1.0
    h6 = 0.0 if hrs_silence >= 6 else 1.0
    hours_into_window = float((et_hour - 12) % 24)
    row = [posts_so_far, hours_into_window, h1, h3, h6, dow, float(et_hour), pf_med, t7_med, share_qr_med]
    return float(clf5.predict_proba(np.array([row]))[0, 1])


X_SILENCE = [0, 1, 2, 4, 6]
ET_HOURS_A = [0, 3, 6, 9, 12, 15, 18, 21]
tableA_rows = []
for X in X_SILENCE:
    row = {"hours_since_last_post": X}
    for eh in ET_HOURS_A:
        hours_into_window = (eh - 12) % 24
        posts_so_far = round(pf_med * hours_into_window / 24.0)
        row[f"et_{eh:02d}h"] = round(hazard_p15(X, eh, posts_so_far), 4)
    tableA_rows.append(row)
tableA = pd.DataFrame(tableA_rows)

POSTS_SO_FAR_B = [0, 5, 10, 20, 40]
tableB_rows = []
for X in X_SILENCE:
    row = {"hours_since_last_post": X}
    for pf in POSTS_SO_FAR_B:
        row[f"posts_so_far_{pf}"] = round(hazard_p15(X, 14, pf), 4)
    tableB_rows.append(row)
tableB = pd.DataFrame(tableB_rows)

# Secondary finer probe: sweep the RAW COUNT of posts_last_3h (not a 0/1 flag)
# at posts_last_1h=0 fixed, to show where/whether the model reacts to
# longer-lookback activity at all (directly answers "is there a rebound").
tableC_rows = []
for raw_count in range(0, 11):
    row = {"posts_last_3h_and_6h_raw_count": raw_count}
    for eh in (6, 14, 21):
        hours_into_window = float((eh - 12) % 24)
        x = [10, hours_into_window, 0.0, float(raw_count), float(raw_count), 2.0, float(eh),
             pf_med, t7_med, share_qr_med]
        row[f"et_{eh:02d}h"] = round(float(clf5.predict_proba(np.array([x]))[0, 1]), 4)
    tableC_rows.append(row)
tableC = pd.DataFrame(tableC_rows)

tableA.to_csv(OUT_DIR / "hazard_curve_by_et_hour.csv", index=False)
tableB.to_csv(OUT_DIR / "hazard_curve_by_posts_so_far.csv", index=False)
tableC.to_csv(OUT_DIR / "hazard_curve_raw_count_sensitivity.csv", index=False)

# circadian dip + post-silence rebound, read directly off the tables
row_x1 = tableA[tableA.hours_since_last_post == 1].iloc[0]
et_cols = [c for c in tableA.columns if c.startswith("et_")]
dip_col = min(et_cols, key=lambda c: row_x1[c])
peak_col = max(et_cols, key=lambda c: row_x1[c])
p_x0_14 = tableB[tableB.hours_since_last_post == 0].iloc[0]["posts_so_far_10"]
p_x6_14 = tableB[tableB.hours_since_last_post == 6].iloc[0]["posts_so_far_10"]
rebound_dir = "REBOUNDS (higher hazard after longer silence)" if p_x6_14 > p_x0_14 else \
              "DECAYS FURTHER (lower hazard after longer silence, momentum/self-exciting persistence)"
p_raw0_14 = tableC[tableC.posts_last_3h_and_6h_raw_count == 0].iloc[0]["et_14h"]
p_raw10_14 = tableC[tableC.posts_last_3h_and_6h_raw_count == 10].iloc[0]["et_14h"]

hazard_lines = ["# Hazard curve (M5 GradientBoostingClassifier) -- elon_daily",
                "",
                "REFIT DISCLOSURE: not persisted by the original run. Refit here once via M.fit_M5 on the "
                "TRAIN-only daily span with the disclosed n_estimators=50/max_depth=2 and the function's own "
                "disclosed cap=40 default, never re-selected here.",
                "",
                f"## Feature importances of the fitted GBM (read this FIRST -- it explains every table below): "
                f"{ {k: round(v,4) for k,v in sorted(FEAT_IMPORTANCE.items(), key=lambda kv:-kv[1])} }",
                "posts_last_1h alone carries ~70% of total importance. posts_last_3h/6h combined carry only "
                "~6%. This means the fitted model's PRACTICAL resolution for 'silence' is close to BINARY "
                "(posted in the last hour vs not) -- it does not encode a smooth decay curve over 1h/2h/4h/6h "
                "the way a hand-built hazard function might. This is reported as a property of THIS fitted "
                "model, not smoothed over.",
                "",
                "P(post in next 15 minutes), by hours-since-last-post bucket. 'hours_since_last_post' is "
                "approximated from the fitted model's own posts_last_1h/3h/6h covariates (the model has no "
                "literal 'time since last post' feature) -- each bucket sets the counts for every lookback "
                "window shorter than or equal to the stated silence to 0 (X=0: posts_last_1h=1 i.e. posted "
                "within the hour; X=1/2: posts_last_1h=0 but posts_last_3h/6h=1; X=4: posts_last_1h=posts_"
                "last_3h=0, posts_last_6h=1; X=6: all three =0). This is a disclosed APPROXIMATION built from "
                "the available feature set, not a literal model input.",
                "",
                f"Representative fixed covariates (held constant): prior_window_final={pf_med:.1f} "
                f"(train median), trailing_7d_mean={t7_med:.1f} (train median), "
                f"share_qr={share_qr_med:.3f} (train-era overall), dow=2 (Wednesday).",
                "",
                "## Table A: by hours-since-last-post x ET hour-of-day "
                "(posts_so_far scaled to a typical pace for that hour: prior_window_final_median * elapsed_frac)",
                tableA.to_string(index=False),
                "",
                "## Table B: by hours-since-last-post x posts-so-far-today (ET hour fixed at 14:00, afternoon)",
                tableB.to_string(index=False),
                "",
                "## Table C: SECONDARY finer probe -- sweeping the RAW COUNT (not 0/1) of posts_last_3h/6h "
                "with posts_last_1h=0 fixed, posts_so_far=10, across 3 ET hours. Directly shows where (if "
                "anywhere) the model reacts to longer-lookback activity once the last hour is quiet.",
                tableC.to_string(index=False),
                "",
                f"## Circadian dip: at hours_since_last_post=1, the QUIETEST ET hour column is {dip_col} "
                f"(p15={row_x1[dip_col]*100:.2f}%), the BUSIEST is {peak_col} (p15={row_x1[peak_col]*100:.2f}%).",
                f"## Post-silence rebound (ET 14:00, posts_so_far=10 fixed, X=0 vs X=6 buckets): "
                f"p15 at 0h silence={p_x0_14*100:.2f}% vs 6h silence={p_x6_14*100:.2f}% -> {rebound_dir}.",
                f"## Raw-count sensitivity check (ET 14:00, posts_last_1h=0 fixed): p15 at "
                f"posts_last_3h/6h=0 (genuine silence)={p_raw0_14*100:.2f}% vs =10 (recent burst before this "
                f"quiet hour)={p_raw10_14*100:.2f}% -- confirms the direction and magnitude of Table C's trend "
                f"using the model's native count scale rather than the boolean approximation above.",
                ""]
(OUT_DIR / "hazard_curve.txt").write_text("\n".join(hazard_lines), encoding="utf-8")
print(f"[output] {OUT_DIR / 'hazard_curve.txt'}")


# ===========================================================================
# SECTION 5 -- RANKED RULE TABLE (all discovered rules, sorted by SEALED lift)
# ===========================================================================
cluster_rule_rows = []
n_train_days_total = len([d for d in all_days_full if d["span"] == "train"])
n_sealed_days_total = len([d for d in all_days_full if d["span"] == "sealed"])
climatology_tr = Counter(daily_bracket_lookup(d["final"]) for d in daily_train)
climatology_se = Counter(daily_bracket_lookup(d["final"]) for d in daily_sealed)
for cl in range(DAILY_M3_K):
    train_days = [d for d in all_days_full if d["span"] == "train" and d["cluster"] == cl]
    sealed_days = [d for d in all_days_full if d["span"] == "sealed" and d["cluster"] == cl]
    if not train_days:
        continue
    n_tr, n_se = len(train_days), len(sealed_days)
    tr_brackets = Counter(daily_bracket_lookup(d["final"]) for d in train_days)
    modal_bracket, modal_n = tr_brackets.most_common(1)[0]
    hit_tr = modal_n / n_tr
    hit_se = (sum(1 for d in sealed_days if daily_bracket_lookup(d["final"]) == modal_bracket) / n_se) if n_se else float("nan")
    base_tr = climatology_tr.get(modal_bracket, 0) / max(1, n_train_days_total)
    base_se = climatology_se.get(modal_bracket, 0) / max(1, n_sealed_days_total) if n_sealed_days_total else float("nan")
    lift_tr = hit_tr / base_tr if base_tr > 0 else float("nan")
    lift_se = hit_se / base_se if (n_se and base_se and base_se > 0) else float("nan")
    # H=1 excluded: predict_M3's own normalization degenerates there (all
    # clusters tie at distance=0) -- see the caveat in day_archetypes.txt.
    cl_curve = recall_df[(recall_df.cluster == cl) & (recall_df.span == "train") &
                          (recall_df.hours_elapsed > 1)].sort_values("hours_elapsed")
    hit70 = cl_curve[cl_curve.recall >= 0.70]
    id_hour = int(hit70.iloc[0].hours_elapsed) if len(hit70) else None
    id_note = f"identifiable by hour {id_hour} (~{(12+id_hour)%24:02d}:00 ET)" if id_hour is not None else \
              "not reliably identifiable early (never reaches 70% recall in tested grid)"
    desc, dominant, _ = describe_centroid(centroids[cl])
    rule_text = f"day-shape matches Archetype {cl} ({dominant}), {id_note}"
    flag = (n_tr < MIN_N_FLAG) or (n_se > 0 and n_se < MIN_N_FLAG) or (n_se == 0)

    # audit 2026-07-31 [D][MEDIUM] fix (round-3: now band-searched, see
    # fit_naive_threshold() docstring): same naive baseline treatment as the CART leaves --
    # count_so_far at this cluster's own id_hour, over ALL days (not just this cluster's
    # members), TRAIN-fit/frozen/sealed-applied. shape[:id_hour].sum() = posts observed in
    # [day_start, day_start+id_hour) -- identical quantity to build_features()'s
    # count_so_far, read directly off the already-computed 24-dim shape vector (no
    # recomputation/re-derivation).
    sealed_slugs_cl = np.array([d["slug"] for d in sealed_days])
    sealed_hit_cl = np.array([daily_bracket_lookup(d["final"]) == modal_bracket for d in sealed_days])
    naive_ci_cl = None
    if id_hour is not None:
        pool_tr_days = [d for d in all_days_full if d["span"] == "train"]
        pool_se_days = [d for d in all_days_full if d["span"] == "sealed"]
        counts_cl_tr = np.array([d["shape"][:id_hour].sum() for d in pool_tr_days])
        y_bool_cl_tr = np.array([daily_bracket_lookup(d["final"]) == modal_bracket for d in pool_tr_days])
        naive_cl = fit_naive_threshold(counts_cl_tr, y_bool_cl_tr, min_n=TREE_MIN_SAMPLES_LEAF)
        counts_cl_se = np.array([d["shape"][:id_hour].sum() for d in pool_se_days])
        y_bool_cl_se = np.array([daily_bracket_lookup(d["final"]) == modal_bracket for d in pool_se_days])
        n_se_naive_cl, hit_se_naive_cl = apply_naive_threshold(naive_cl, counts_cl_se, y_bool_cl_se)
        naive_mask_cl_se = naive_threshold_mask(naive_cl, counts_cl_se)
        naive_slugs_cl_se = np.array([d["slug"] for d in pool_se_days])[naive_mask_cl_se]
        if n_se:  # rule (cluster) side needs >=2 unique auctions too -- bootstrap handles that internally
            naive_ci_cl = bootstrap_incremental_lift_ci(
                sealed_slugs_cl, sealed_hit_cl, naive_slugs_cl_se, y_bool_cl_se[naive_mask_cl_se])
    else:
        naive_cl, n_se_naive_cl, hit_se_naive_cl = None, 0, float("nan")
    naive_fields_cl = naive_baseline_report(hit_se, naive_cl, n_se_naive_cl, hit_se_naive_cl, ci=naive_ci_cl)
    # audit 2026-07-31 [D][MEDIUM] round-2 fix: M3 cluster n_tr/n_se (and naive_cl's n) are
    # ALREADY unique-auction counts -- all_days_full/pool_*_days hold exactly one row per
    # calendar day (full-shape assignment is a per-day operation, unlike the CART's
    # per-checkpoint rows), so no row-vs-auction gap exists here. Adding the same
    # n_train_rows/n_sealed_rows/naive_*_rows companion columns anyway, mirroring the CART
    # leaves' values, purely for a consistent ranked_rules.csv schema across all rule sources.
    naive_fields_cl["naive_n_train_rows"] = naive_fields_cl["naive_n_train"]
    naive_fields_cl["naive_n_sealed_rows"] = naive_fields_cl["naive_n_sealed"]
    jk_cl = jackknife_loo_auction(sealed_slugs_cl, sealed_hit_cl) if n_se else None
    jk_fields_cl = dict(jackknife_n_auctions=(jk_cl["jk_n_auctions"] if jk_cl else n_se),
                         jackknife_hit_min=(jk_cl["jk_hit_min"] if jk_cl else float("nan")),
                         jackknife_hit_max=(jk_cl["jk_hit_max"] if jk_cl else float("nan")))

    cluster_rule_rows.append(dict(
        source="M3-cluster", rule_id=f"M3-elon_daily-cluster{cl}", target="elon_daily",
        rule_text=rule_text,
        decision_time=f"day_start + {id_hour}h" if id_hour is not None else "n/a (not early-identifiable)",
        decision_checkpoint_max=id_hour,
        outcome=f"final count bracket {modal_bracket}",
        n_train=n_tr, n_train_rows=n_tr, n_sealed=n_se, n_sealed_rows=n_se,
        **jk_fields_cl,
        train_hit_rate=hit_tr, sealed_hit_rate=hit_se,
        base_rate_train=base_tr, base_rate_sealed=base_se, lift_train=lift_tr, lift_sealed=lift_se,
        flag_small_n=flag, **naive_fields_cl))

all_rules = tree_daily["rule_rows"] + tree_e2d["rule_rows"] + cluster_rule_rows
rules_df = pd.DataFrame(all_rules)
# audit 2026-07-31 [D][MEDIUM] fix: re-sort by incremental_lift_over_naive (how
# much the rule beats a single-feature count_so_far threshold fit at its OWN
# decision times), not by raw sealed_lift (which conflates the rule's real
# discriminative power with a late-window decision time's own trivial null --
# see decision_tree_elon_daily.txt's "Naive-baseline summary"). lift_sealed
# itself is UNCHANGED -- this only changes row ORDER, kept as a column for
# comparison. Rules with no computable naive baseline (naive_hit_sealed=NaN)
# sort last, same fillna(-999) convention as the prior lift_sealed sort.
rules_df["_sort_key"] = rules_df["incremental_lift_over_naive"].fillna(-999)
rules_df = rules_df.sort_values(["_sort_key", "sealed_hit_rate"], ascending=False).drop(columns=["_sort_key"])
rules_df.to_csv(OUT_DIR / "ranked_rules.csv", index=False)
print(f"\n[output] {OUT_DIR / 'ranked_rules.csv'} ({len(rules_df)} rules, sorted by "
      f"incremental_lift_over_naive)")
print("NOTE: M4 (HMM) and M5 (hazard) are reported separately in hmm_states.txt / hazard_curve.txt -- "
      "their natural output (a transition matrix / continuous hazard function) does not reduce to a "
      "leaf-style n/hit-rate rule without fabricating an arbitrary threshold the study never fit; forcing "
      "them into this table would be an ADDED claim, not an extracted one.")

top10 = rules_df[rules_df.n_sealed >= MIN_N_FLAG].head(10)
print("\n=== TOP 10 RULES BY INCREMENTAL LIFT OVER NAIVE BASELINE (n_sealed >= 30 only) ===")
for _, r in top10.iterrows():
    inc_str = f"{r.incremental_lift_over_naive:.2f}x" if pd.notna(r.incremental_lift_over_naive) else "n/a"
    ci_str = (f"CI=[{r.incr_lift_ci_lo:.2f}x,{r.incr_lift_ci_hi:.2f}x] P(lift<=1)={r.p_lift_le_1*100:.1f}%"
              if pd.notna(r.incr_lift_ci_lo) else "CI n/a")
    print(f"  [{r.source}] {r.rule_text}")
    print(f"      -> {r.outcome}  |  train: n={r.n_train} hit={r.train_hit_rate*100:.1f}%  |  "
         f"sealed: n={r.n_sealed} hit={r.sealed_hit_rate*100:.1f}% lift_vs_climatology={r.lift_sealed:.2f}x  |  "
         f"naive baseline ({r.naive_kind} on count_so_far, lo={r.naive_lo} hi={r.naive_hi}): "
         f"sealed hit={r.naive_hit_sealed*100:.1f}% (n={r.naive_n_sealed})  "
         f"incremental_lift_over_naive={inc_str}  {ci_str}  -> {r.naive_verdict}")

# audit 2026-07-31 round-3 [D][HIGH] fix (finding #1): scorecard is now CI-GATED
# (naive_verdict, a 3-category outcome), not the raw point-estimate boolean
# (beats_naive_sealed) alone. See naive_verdict_from_ci() docstring.
n_survive = int((rules_df.naive_verdict == "SURVIVES").sum())
n_unproven = int((rules_df.naive_verdict == "UNPROVEN").sum())
n_collapse = int((rules_df.naive_verdict == "COLLAPSES").sum())
n_untestable = int((rules_df.naive_verdict == "UNTESTABLE").sum())
n_old_point_survive = int((rules_df.beats_naive_sealed == True).sum())  # noqa: E712 (pandas bool col)
# "early" = elon_daily rules whose latest TRAIN decision checkpoint is <=15h into the
# window (checkpoints 6/12/15 -- 18:00 ET/00:00 ET/03:00 ET), where the parent's own
# R2 null (0.744 at h18, 0.870 at h21) does NOT yet apply -- computed dynamically off
# decision_checkpoint_max, never hardcoded rule IDs, so this is stable if the tree
# structure changes on a future refit.
early_mask = (rules_df.target == "elon_daily") & rules_df.decision_checkpoint_max.notna() & \
             (rules_df.decision_checkpoint_max <= 15)
early_survivors = rules_df[early_mask & (rules_df.naive_verdict == "SURVIVES")]
print(f"\n=== NAIVE-BASELINE SCORECARD (all {len(rules_df)} rules, CI-gated) === "
      f"SURVIVES={n_survive}  UNPROVEN={n_unproven}  COLLAPSES={n_collapse}  UNTESTABLE={n_untestable}  "
      f"(old point-estimate-only count would have been {n_old_point_survive} survive)")
if len(early_survivors):
    print("EARLY rules (checkpoints 6/12/15 only) that SURVIVE (CI-gated) their naive baseline on sealed data:")
    for _, r in early_survivors.iterrows():
        print(f"  [{r.rule_id}] {r.rule_text}  incremental_lift_over_naive={r.incremental_lift_over_naive:.2f}x "
             f"CI=[{r.incr_lift_ci_lo:.2f}x,{r.incr_lift_ci_hi:.2f}x] "
             f"(sealed hit={r.sealed_hit_rate*100:.1f}% vs naive {r.naive_hit_sealed*100:.1f}%, n_sealed={r.n_sealed})")
else:
    print("EARLY rules (checkpoints 6/12/15 only): NONE SURVIVE (CI-gated) their own naive baseline on sealed "
          "data -- the parent's null is weaker there (per prereg) but the tree's extra conditions still do "
          "not add statistically-confirmed discriminative power beyond one band/threshold, out of sample.")

# ---------------------------------------------------------------------------
# Persist provenance CSVs (per THE WALL / reproducibility rules -- every
# number above must be recomputable from these files alone)
# ---------------------------------------------------------------------------
tree_daily["dftr"].assign(span="train").to_csv(OUT_DIR / "tree_elon_daily_train_rows.csv", index=False)
if len(tree_daily["dfse"]):
    tree_daily["dfse"].assign(span="sealed").to_csv(OUT_DIR / "tree_elon_daily_sealed_rows.csv", index=False)
tree_e2d["dftr"].assign(span="train").to_csv(OUT_DIR / "tree_elon_2day_train_rows.csv", index=False)
if len(tree_e2d["dfse"]):
    tree_e2d["dfse"].assign(span="sealed").to_csv(OUT_DIR / "tree_elon_2day_sealed_rows.csv", index=False)
pd.DataFrame([{k: v for k, v in d.items() if k != "shape"} for d in all_days_full]).to_csv(
    OUT_DIR / "cluster_assignments.csv", index=False)

# ===========================================================================
# RUN_META
# ===========================================================================
n_leaves_daily = len(tree_daily["leaf_reports"])
n_leaves_e2d = len(tree_e2d["leaf_reports"])
# Headline top rule must come from the n_sealed>=30 subset -- otherwise a
# tiny-n (flagged) leaf with an inflated lift silently becomes "the" headline
# number, exactly the failure mode lesson_tiny_n_ci_degenerate.md warns about.
rules_df_reliable = rules_df[rules_df.n_sealed >= MIN_N_FLAG]
# audit 2026-07-31 [D][MEDIUM] fix: rules_df's row order is now PRIMARILY sorted
# by incremental_lift_over_naive (see Section 5) -- this is the new, more honest
# ranking. The OLD ranking (raw lift_sealed vs climatology, what "the headline"
# meant before this fix) is recomputed independently here on its OWN sort so
# that number is UNCHANGED and can be diffed against the pre-fix RUN_META.
top_rule_new = rules_df_reliable.iloc[0] if len(rules_df_reliable) else None  # already sorted desc by this
top_rule_old = (rules_df_reliable.sort_values("lift_sealed", ascending=False).iloc[0]
                if len(rules_df_reliable) else None)
top_rule_unfiltered = rules_df.iloc[0] if len(rules_df) else None
# audit 2026-07-31 round-3 [D][HIGH] fix (finding #1): the HEADLINE top rule must be
# CI-GATED SURVIVES, not merely the highest point-estimate incremental_lift_over_naive
# among the reliable-n subset -- a point estimate can rank first while its own CI still
# straddles 1.0 (this was exactly leaf6's situation before this fix). rules_df_reliable
# is already sorted desc by incremental_lift_over_naive, so filtering preserves rank order.
rules_df_reliable_ci_survives = rules_df_reliable[rules_df_reliable.naive_verdict == "SURVIVES"]
top_rule_ci = rules_df_reliable_ci_survives.iloc[0] if len(rules_df_reliable_ci_survives) else None
early_reliable_survivors = rules_df[early_mask & (rules_df.naive_verdict == "SURVIVES") &
                                     (rules_df.n_sealed >= MIN_N_FLAG)]
top_rule_old_inc_str = (f"{float(top_rule_old.incremental_lift_over_naive):.3f}"
                        if top_rule_old is not None else "n/a")

# audit 2026-07-31 round-3 [D][HIGH] fix: 3-category scorecard (SURVIVES/UNPROVEN/COLLAPSES/
# UNTESTABLE) replaces the old point-estimate boolean. Preserved alongside for diffability.
n_survive_ci = int((rules_df.naive_verdict == "SURVIVES").sum())
n_unproven_ci = int((rules_df.naive_verdict == "UNPROVEN").sum())
n_collapse_ci = int((rules_df.naive_verdict == "COLLAPSES").sum())
n_untestable_ci = int((rules_df.naive_verdict == "UNTESTABLE").sum())
n_survive1_old_point = int((rules_df.beats_naive_sealed == True).sum())  # noqa: E712

# audit 2026-07-31 [D][MEDIUM] round-2: 2-feature naive-baseline cross-check (carried forward
# from @backtest-auditor's re-audit probe) -- of the rules that CI-gated-SURVIVE the 1-feature
# naive baseline, how many ALSO CI-gated-SURVIVE the strictly harder 2-feature (count_so_far
# AND max_posts_60min) adversary. NaN-valued naive2 columns (M3 cluster rows, which have no
# 2-feature check) never equal "SURVIVES", so they're correctly excluded here.
survive1_mask = (rules_df.naive_verdict == "SURVIVES")
survive2_mask = survive1_mask & (rules_df.naive2_verdict == "SURVIVES")
n_survive1 = int(survive1_mask.sum())
n_survive2 = int(survive2_mask.sum())
survive2_ids = rules_df.loc[survive2_mask, "rule_id"].tolist()

emit_run_meta(
    script=__file__,
    headline={
        "extraction_only": True,
        "n_cart_leaves_elon_daily": n_leaves_daily,
        "n_cart_leaves_elon_2day": n_leaves_e2d,
        "n_kmeans_clusters_elon_daily": DAILY_M3_K,
        "n_hmm_states_elon_daily": DAILY_M4_STATES,
        "n_hmm_states_elon_2day": E2D_M4_STATES,
        "n_rules_total": int(len(rules_df)),
        "n_rules_flagged_small_n": int(rules_df.flag_small_n.sum()) if len(rules_df) else 0,
        # --- audit 2026-07-31 [D][MEDIUM] fix: naive single-threshold baseline scorecard ---
        "naive_baseline_min_n": TREE_MIN_SAMPLES_LEAF,
        "naive_baseline_parent_R2_null": "R2(count_so_far->final), elon_daily: hour18=0.744 hour21=0.870 "
            "(pattern_discovery_out/summary.md 'Null-model check', post-DST-fix re-run; supersedes the "
            "0.764/0.856 an earlier version of this file cited) -- any elon_daily rule firing only at "
            "checkpoint 18/21 is largely restating this, per decision_tree_elon_daily.txt's Naive-baseline "
            "summary.",
        # --- audit 2026-07-31 round-3 [D][HIGH] fix: CI-GATED 3-category scorecard is now
        # the headline (SURVIVES requires the auction-level bootstrap CI on
        # incremental_lift_over_naive to EXCLUDE 1.0, not just beat naive on point estimate) ---
        "n_rules_survive_naive_baseline_CI_GATED": n_survive_ci,
        "n_rules_unproven_ci_straddles_1": n_unproven_ci,
        "n_rules_collapse_to_naive_baseline": n_collapse_ci,
        "n_rules_untestable_naive_baseline": n_untestable_ci,
        "n_rules_survive_naive_baseline_OLD_point_estimate_only": n_survive1_old_point,
        "top_rule_by_incremental_lift_over_naive_n_ge_30_CI_GATED": (
            top_rule_ci.rule_text if top_rule_ci is not None else
            "none SURVIVE (CI-gated) at n_sealed(auctions)>=30 -- see n_rules_unproven_ci_straddles_1"),
        "top_rule_incremental_lift_over_naive": (
            float(top_rule_ci.incremental_lift_over_naive) if top_rule_ci is not None else None),
        "top_rule_incremental_lift_ci": (
            [round(float(top_rule_ci.incr_lift_ci_lo), 4), round(float(top_rule_ci.incr_lift_ci_hi), 4)]
            if top_rule_ci is not None else None),
        "top_rule_incremental_lift_sealed_n": (int(top_rule_ci.n_sealed) if top_rule_ci is not None else None),
        "top_rule_incremental_lift_sealed_hit": (
            float(top_rule_ci.sealed_hit_rate) if top_rule_ci is not None else None),
        # --- reference only: the highest POINT-ESTIMATE rule at n>=30, regardless of whether
        # its own CI excludes 1.0 -- kept so a reader can see what the pre-CI-gate headline
        # would have picked and confirm it is NOT what n_rules_survive_naive_baseline_CI_GATED
        # is built from ---
        "top_rule_by_incremental_lift_over_naive_n_ge_30_POINT_ESTIMATE_ONLY": (
            top_rule_new.rule_text if top_rule_new is not None else "none reach n_sealed>=30"),
        "top_rule_by_incremental_lift_over_naive_n_ge_30_POINT_ESTIMATE_ONLY_verdict": (
            top_rule_new.naive_verdict if top_rule_new is not None else None),
        "early_rules_surviving_naive_baseline_n_ge_30_CI_GATED": [
            {"rule_id": r.rule_id, "incremental_lift_over_naive": round(float(r.incremental_lift_over_naive), 4),
             "incr_lift_ci": [round(float(r.incr_lift_ci_lo), 4), round(float(r.incr_lift_ci_hi), 4)],
             "sealed_n": int(r.n_sealed), "sealed_hit": round(float(r.sealed_hit_rate), 4),
             "naive_hit_sealed": round(float(r.naive_hit_sealed), 4)}
            for _, r in early_reliable_survivors.iterrows()],
        # --- OLD (pre-fix, pre-band-search, point-estimate-only) headline metric, PRESERVED
        # UNCHANGED for diffability ---
        "top_rule_by_sealed_lift_n_ge_30": (top_rule_old.rule_text if top_rule_old is not None else "none reach n_sealed>=30"),
        "top_rule_sealed_n": (int(top_rule_old.n_sealed) if top_rule_old is not None else None),
        "top_rule_sealed_lift": (float(top_rule_old.lift_sealed) if top_rule_old is not None else None),
        "top_rule_by_sealed_lift_COLLAPSES_TO_NAIVE_BASELINE": (
            (top_rule_old.beats_naive_sealed is False) if top_rule_old is not None else None),
        "top_rule_by_sealed_lift_incremental_lift_over_naive": (
            float(top_rule_old.incremental_lift_over_naive) if top_rule_old is not None else None),
        "top_rule_unfiltered_WARNING_tiny_n": (
            top_rule_unfiltered.rule_text if (top_rule_unfiltered is not None and
                                               top_rule_unfiltered.flag_small_n) else "n/a, not flagged"),
        "top_rule_unfiltered_sealed_n": (int(top_rule_unfiltered.n_sealed) if top_rule_unfiltered is not None else None),
    },
    data_paths=[
        "_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet",
        "_DataMetricPulls/pacing_backtest/pattern_discovery_2026-07-26.py (imported read-only, reused "
        "build_targets()/WALL_ELON/CHECKPOINTS_*/make_prior_final_fn/build_daily_brackets, main() never called)",
        "_DataMetricPulls/pacing_backtest/pattern_discovery_lib.py (imported, reused)",
        "_DataMetricPulls/pacing_backtest/pattern_discovery_methods.py (imported, reused fit_M2/fit_M3_centroids/"
        "fit_M4/fit_M5/build_features/_assign_cluster/_hourly_seq)",
        "_DataMetricPulls/pacing_backtest/pattern_discovery_out/summary.md + run_dstfix_2026-07-31.log "
        "(source of the FROZEN, post-DST-fix hyperparameters hardcoded above, re-diffed against this fresh "
        "log -- never re-searched; supersedes the pre-fix run_reaudit_fix.log)",
    ],
    window_basis="noon-ET parsed from market slug, reused unchanged from pattern_discovery_2026-07-26.py "
                  "(WALL_ELON=2026-04-01 00:00 ET, unchanged)",
    fills="N/A -- pure descriptive/interpretability extraction over an already-fit forecast-accuracy "
          "diagnostic. No P&L, no fills, no tradeability claim attached to any rule (prereg already answered "
          "that question: no method beats the market where the market priced the winner).",
    trial_count=0,
    scope="descriptive extraction / interpretability pass over an already-fitted study (pattern_discovery_"
          "2026-07-26.py) -- NOT a new study, zero new hyperparameter search performed anywhere in this script",
    notes=(
        f"SUPERSESSION NOTICE: a 5-site DST bug fix landed upstream in pattern_discovery_2026-07-26.py / "
        f"pattern_discovery_methods.py (DailySeries, r2_null_check, the M7 multi-day decomposition, the "
        f"Trump day-zero anchor, and pattern_discovery_methods.py:282 M3's d['s']+86400 -> d['e']) since "
        f"this script's prior audited run. The parent study was re-run cold twice back-to-back from cleared "
        f"checkpoints and is now frozen/verified: per_row.csv, summary.md, and its own RUN_META are "
        f"byte-identical across both runs. The daily window shifted for 126 training days, so this tree "
        f"legitimately rebuilds from scratch -- n_cart_leaves_elon_daily={n_leaves_daily}, "
        f"n_cart_leaves_elon_2day={n_leaves_e2d}, n_rules_total={len(rules_df)} may all differ from any "
        f"earlier run of this script, and DO differ from the pre-DST-fix run this file's prior audit saw "
        f"(then: 13 elon_daily leaves / 22 rules total). ANY leaf4/leaf7/leaf11/leaf15/leaf21 citation from "
        f"a prior version of this file or its audit logs is SUPERSEDED and refers to leaves that no longer "
        f"exist under this identifier -- read the leaves in decision_tree_elon_daily.txt/"
        f"decision_tree_elon_2day.txt fresh, on their own (new) numbering; do not attempt to reconcile "
        f"against the old numbering."
        f"\n\nFitted objects (CART, KMeans centroids, HMM, GBM hazard) were NOT persisted by the original "
        f"run (pattern_discovery_out/checkpoints/*.pkl only cache per-row prediction rows) -- every model "
        f"in this script is a REFIT using the exact TRAIN-only data (via the original build_targets(), "
        f"imported read-only, now reading the DST-fixed pipeline) and the exact disclosed hyperparameters, "
        f"re-sourced from the post-fix pattern_discovery_out/run_dstfix_2026-07-31.log (supersedes the "
        f"pre-fix run_reaudit_fix.log an earlier version of this file cited) -- "
        f"(daily: M2 K={DAILY_M2_HP['K']}/ccp_alpha={DAILY_M2_HP['ccp_alpha']}, M3 k={DAILY_M3_K}, "
        f"M4 n_states={DAILY_M4_STATES}, M5 n_estimators={DAILY_M5_HP['n_estimators']}/"
        f"max_depth={DAILY_M5_HP['max_depth']}; elon_2day: M2 K={E2D_M2_HP['K']}/"
        f"ccp_alpha={E2D_M2_HP['ccp_alpha']}, M4 n_states={E2D_M4_STATES}), hardcoded as constants (values "
        f"themselves diffed against the fresh disclosed log, not re-selected), never re-searched. "
        f"DAILY_BRACKETS reproduced exactly and asserted against the disclosed run ({DAILY_BRACKETS}). "
        f"n_train/n_sealed (auction-count basis): elon_daily train={len(daily_train)} "
        f"sealed={len(daily_sealed)}; elon_2day train={len(e2d_train)} sealed={len(e2d_sealed)}. CART "
        f"leaves fit ONCE on the full train span (disclosed: original refits per walk-forward block; noted "
        f"explicitly in each tree's output file). HMM/GBM fit ONCE using fit_M4/fit_M5's own disclosed "
        f"cap=40 default (last 40 train units), matching the walk-forward cap used throughout the original "
        f"study."
        f"\n\nAUCTION-COUNT FIX (audit 2026-07-31 [D][MEDIUM] round-2, this run): n_train/n_sealed on every "
        f"CART leaf and M3 cluster row are unique AUCTIONS (distinct slug), never checkpoint-rows -- a "
        f"single auction hitting multiple checkpoints that route to the same leaf can otherwise inflate n "
        f"past a leaf's true independent sample size. Row counts are preserved separately as "
        f"n_train_rows/n_sealed_rows (nothing hidden). flag_small_n (MIN_N_FLAG={MIN_N_FLAG}) is gated on "
        f"the auction count, not the row count. A leave-one-auction-out jackknife "
        f"(jackknife_n_auctions/jackknife_hit_min/jackknife_hit_max) is computed per leaf and per cluster as "
        f"the honest stability measure at these sample sizes. Of {len(rules_df)} total rules, "
        f"{int(rules_df.flag_small_n.sum()) if len(rules_df) else 0} are flagged small-n on the corrected "
        f"auction basis. The naive-baseline n's (naive_n_train/naive_n_sealed) are re-pointed at unique "
        f"auctions the same way, for a like-for-like comparison; row counts kept as naive_n_train_rows/"
        f"naive_n_sealed_rows."
        f"\n\nNAIVE-BASELINE SCORECARD, round-3 CI-GATED (audit 2026-07-31 [D][HIGH] findings #1+#2 fix): "
        f"the naive baseline itself now searches TWO-SIDED BANDS (lo<=count_so_far<=hi) in addition to "
        f"one-sided thresholds (superset of the old search -- can only make survival harder, never easier; "
        f"see fit_naive_threshold() docstring), and beats_naive_sealed's raw point comparison is no longer "
        f"the scorecard verdict -- SURVIVES now requires the {N_BOOT}-resample auction-level block-bootstrap "
        f"95% CI on incremental_lift_over_naive to EXCLUDE 1.0 (ci_lo>1.0). Of {len(rules_df)} total rules: "
        f"{n_survive_ci} SURVIVE (CI excludes 1.0), {n_unproven_ci} UNPROVEN (point estimate beats naive but "
        f"CI straddles 1.0, or CI undefined at <2 unique auctions on either side -- this is what disqualifies "
        f"the n_sealed=1 M2-elon_2day-leaf6 row from ever reading SURVIVES), {n_collapse_ci} COLLAPSE (point "
        f"estimate at or below naive), {n_untestable_ci} UNTESTABLE (no naive baseline or no sealed rows) "
        f"(full scorecard: ranked_rules.csv naive_verdict/naive_lo/naive_hi/incr_lift_ci_lo/incr_lift_ci_hi/"
        f"p_lift_le_1 columns, decision_tree_elon_daily.txt/decision_tree_elon_2day.txt 'Naive-baseline "
        f"summary'). For reference, the OLD point-estimate-only (pre-band-search, pre-CI-gate) scorecard "
        f"called {n_survive1_old_point} rules SURVIVE -- the strengthened baseline + CI gate together moved "
        f"{n_survive1_old_point - n_survive_ci} of those out of SURVIVES."
        f"\n\nOf the reliable-n (n_sealed auctions >= {MIN_N_FLAG}) subset, the CI-GATED top rule by "
        f"incremental_lift_over_naive is "
        + (f"{top_rule_ci.rule_id} ({float(top_rule_ci.incremental_lift_over_naive):.3f}x, CI="
           f"[{float(top_rule_ci.incr_lift_ci_lo):.3f}x,{float(top_rule_ci.incr_lift_ci_hi):.3f}x], sealed "
           f"n={int(top_rule_ci.n_sealed)} auctions, hit={float(top_rule_ci.sealed_hit_rate)*100:.1f}%)"
           if top_rule_ci is not None else "NONE -- no rule both reaches n_sealed(auctions)>=30 AND has a "
           "bootstrap CI on incremental_lift_over_naive that excludes 1.0")
        + (f". For contrast, the highest POINT-ESTIMATE rule at this n was {top_rule_new.rule_id} "
           f"({float(top_rule_new.incremental_lift_over_naive):.3f}x, CI-gated verdict={top_rule_new.naive_verdict})"
           if top_rule_new is not None and (top_rule_ci is None or top_rule_new.rule_id != top_rule_ci.rule_id)
           else "")
        + f". {len(early_reliable_survivors)} reliable-n EARLY rule(s) (checkpoints<=15h, i.e. "
        f"18:00/00:00/03:00 ET) CI-gated-SURVIVE the naive baseline: "
        f"{[r.rule_id for _, r in early_reliable_survivors.iterrows()] or 'none'}."
        f"\n\n2-FEATURE NAIVE BASELINE (carried forward from @backtest-auditor's 2026-07-31 re-audit probe, "
        f"made a permanent check in this run, now ALSO band-searched + CI-gated per the round-3 fix): "
        f"count_so_far AND max_posts_60min jointly, same TRAIN-fit/frozen/sealed-applied discipline as the "
        f"1-feature version, CART leaves only (M3 clusters excluded -- no equivalent burst-intensity feature "
        f"in the shape-based cluster representation). Of the {n_survive1} rules that CI-gated-SURVIVE the "
        f"1-feature naive baseline, {n_survive2} ALSO CI-gated-SURVIVE this strictly harder 2-feature "
        f"adversary on sealed data: {survive2_ids or 'none'} -- these carry information beyond running-count "
        f"AND beyond burst-intensity alone, individually, with statistical confidence at this n."
        f"\n\nelon_2day rules carry no lag-1 autocorrelation n_eff discount (unlike elon_daily's disclosed "
        f"rho=0.44/N_eff~39%) because that figure is explicitly scoped to the daily substrate only "
        f"(prereg/pattern_discovery_2026-07-26.md:74) -- elon_2day's own autocorrelation was never "
        f"estimated; this is stated explicitly in each elon_2day leaf's n_eff_note rather than left blank."
    ),
    out_dir="rules_out",
)

print("\n[DONE] Extraction complete. Hand off to @backtest-auditor for verdict.")
