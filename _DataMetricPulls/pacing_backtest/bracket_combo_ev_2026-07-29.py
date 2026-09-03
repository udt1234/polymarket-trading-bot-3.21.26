# -*- coding: utf-8 -*-
"""STATIC bracket-combo coverage + EV study -- built 2026-07-29, resumed/run 2026-07-31
(@backtest-builder). User's framing, in their words: "buying the same brackets over and
over because they win 80% of the time... under 40 and between 40 and 64 usually wins."

Question (NOT a forecasting model): is there a FIXED set of Elon-2-day / Trump-7-day
brackets that, bought blind on EVERY auction with ZERO signal, wins often enough in
DOLLAR terms to beat its cost? Static-portfolio / market-efficiency test, not a
walk-forward strategy. There is no model fit here, so THE WALL applies only to (a) price
lookups -- price_at() never reads a close with hour_utc > decision T, and (b) the
held-out re-score -- the "best" combo is selected on the PRE-WALL span only, then
re-scored on the DISJOINT POST-WALL span (never selected using data the re-score then
reuses).

Scope (backtest-auditor pass-A gate): (b) forecast/coverage diagnostic + (e) exhaustive
config sweep, with a DISCLOSED-ASSUMPTION cost/EV estimate. This is explicitly NOT a
scope-(a) fills-verified claims-P&L number -- see FILL ASSUMPTION below. Do not size a
real order off this number without a follow-up fills-verified pass.

Data: canonical/auctions/{handle} + canonical/prices/{handle} ONLY. No L2, no derived
CSV, no one-off parquet. Auction windows are noon-ET parsed from the market SLUG
(bracket_hit_backtest.py::noon() / pattern_discovery_lib.py::noon_window() pattern,
REPRODUCED LOCALLY below -- not imported -- so this script has zero runtime dependency
on pattern_discovery_*.py, rules_out/, regime_out/, or any prereg file, all of which
other agents are concurrently editing in this repo). Never from trade-derived
start_utc/end_utc (memory: those are ~2x wrong).

FILL ASSUMPTION (read before trusting any $ number here): cost of 1 share of a bracket
at decision time T = the last hourly trade-derived CLOSE at or before T
(canonical `prices.close`), the SAME market-price convention already used as the
audited B4 baseline in pattern_discovery_2026-07-26.py. This is a last-print PROXY, NOT
a confirmed maker-rest fill: Polymarket's L2 order-book archive only exists 2026-04-13+
and does not cover most of this historical span, so a strict "price must trade THROUGH
our resting bid" simulation is UNVERIFIED here. A real patient maker rests BELOW the
last print and waits for the market to trade through them, so true achievable cost is
very likely <= this proxy -- read any positive EV here as a WEAK LOWER BOUND on a real
maker's edge, not a tradeable number, and treat fill-realism as UNVERIFIED for this
piece. Selling side ("who does the market overpay") has the mirror-image caveat: a real
resting ASK gets filled ABOVE the last print, so realized edge selling into an
overpriced bracket is very likely >= what's reported here.

Winner label: `winning_bucket` with confidence=='high' (project memory: reliable even
where price series are missing). Used ONLY to score hit/payout -- never to pick a combo
or a checkpoint. There is no selection *logic* for a label to leak into: combos are
exhaustively enumerated, not chosen by any signal, so THE WALL's "leaked_label" pattern
does not apply to combo membership; it is still enforced for prices (see price_at).

Hands off to @backtest-auditor. Does not certify its own result.
"""
from __future__ import annotations

import itertools
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_meta import emit_run_meta  # noqa: E402

ROOT = Path(r"C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot")
CANON = ROOT / "_DataMetricPulls" / "canonical"
OUT = Path(__file__).resolve().parent / "combo_out"
OUT.mkdir(exist_ok=True)
ET = ZoneInfo("America/New_York")

SEED = 20260729
RNG = np.random.default_rng(SEED)

CHECKPOINTS_H = [6, 12, 24, 36]
PRIMARY_CHECKPOINT_H = 24
MAX_COMBO_SIZE = 5
N_BOOT_HEADLINE = 2000       # bootstrap reps for the small set of headline/highlighted combos
N_BOOT_SWEEP_GAP = 1000      # bootstrap reps for the single aggregate efficiency-gap statistic

# Disclosed wall choice: the task names WALL_ELON=2026-04-01. We apply the SAME date to
# Trump 7-day rather than reusing pattern_discovery's WALL_TRUMP=2026-01-01, because the
# Trump 7-day modal (11-bucket) ladder format is not used AT ALL before 2026-02-06 (see
# run notes / RUN_META) -- WALL_TRUMP=2026-01-01 would put 0 auctions in TRAIN for that
# ladder. 2026-04-01 gives both handles a workable, comparably-sized train/sealed split.
# This choice is about SPLIT-SIZE FEASIBILITY (checked BEFORE any hit-rate/EV number was
# computed), never about which cutoff makes an edge look better.
WALL = int(pd.Timestamp("2026-04-01 00:00:00", tz=ET).timestamp())

# Precedent: pattern_discovery_2026-07-26.py:65. Below this, a block-bootstrap CI
# "excluding zero" is a base-rate artifact of too few auctions (P=25% at n=3 under a
# true null), not evidence. Applied to every success/edge claim below n admissible
# auctions, never silently.
SUCCESS_N_FLOOR = 10

TRIALS = {"n": 0, "detail": {}}


def _trial(name, k=1):
    TRIALS["n"] += k
    TRIALS["detail"][name] = TRIALS["detail"].get(name, 0) + k


# ---------------------------------------------------------------------------
# 1. noon-ET slug parser -- reproduces bracket_hit_backtest.py::noon() /
#    pattern_discovery_lib.py::noon_window() locally (not imported).
# ---------------------------------------------------------------------------
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
EXCLUDE_SLUG = re.compile(
    r"^arch-|higher-bracket|lower-bracket|higher-option|lower-option|"
    r"brackets-of-|-continued$"
)
ELON_PREFIX = "elon-musk-of-tweets-"
TRUMP_PREFIXES = [
    "donald-trump-of-truth-social-posts-",
    "donald-trump-of-tweets-",
    "president-trump-of-tweets-",
]


def _strip_prefix(slug, handle):
    if handle == "elonmusk":
        return slug[len(ELON_PREFIX):] if slug.startswith(ELON_PREFIX) else None
    for p in TRUMP_PREFIXES:
        if slug.startswith(p):
            return slug[len(p):]
    return None


def _parse_tokens(tk, yr):
    mo1 = MONTHS[tk[0].lower()]
    d1 = int(tk[1])
    rest = tk[2:]
    if len(rest) == 1:
        mo2, d2 = mo1, int(rest[0])
    elif len(rest) == 2 and rest[0].lower() in MONTHS:
        mo2, d2 = MONTHS[rest[0].lower()], int(rest[1])
    else:
        raise ValueError("unrecognized slug token shape")
    y2 = yr + (1 if mo2 < mo1 else 0)
    s = pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET))
    e = pd.Timestamp(datetime(y2, mo2, d2, 12, tzinfo=ET))
    return int(s.timestamp()), int(e.timestamp())


def noon_window(slug, handle, yr):
    """Noon-ET [start,end) unix seconds parsed from the market SLUG. yr anchors only the
    calendar year (from start_utc.year, per the established convention); month/day come
    from the slug tokens themselves -- never from trade-derived start_utc/end_utc."""
    body = _strip_prefix(slug, handle)
    if body is None:
        return None
    tk = body.split("-")
    try:
        return _parse_tokens(tk, yr)
    except Exception:
        pass
    if tk and tk[-1].isdigit() and len(tk[-1]) >= 2:  # trailing disambiguator id
        try:
            return _parse_tokens(tk[:-1], yr)
        except Exception:
            return None
    return None


def parse_bucket_range(label):
    l = str(label).replace("\u2013", "-").replace("\u2014", "-").strip()
    try:
        if l.startswith("<"):
            return (0, int(l[1:]) - 1)
        if l.endswith("+"):
            return (int(l[:-1]), None)
        if "-" in l:
            a, b = l.split("-")
            return (int(a), int(b))
        return (int(l), int(l))
    except Exception:
        return None


def normalize_bucket(s):
    return str(s).replace("\u2013", "-").replace("\u2014", "-").strip()


# ---------------------------------------------------------------------------
# 2. canonical data loaders (auctions + prices ONLY)
# ---------------------------------------------------------------------------
def load_auctions(handle, dur):
    files = sorted((CANON / "auctions" / handle).glob("*.parquet"))
    auc = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    raw_n = int(((auc.confidence == "high") & (auc.duration_type == dur)).sum())
    auc = auc[(auc.confidence == "high") & (auc.duration_type == dur)
              & (auc.resolution_status.isin(["resolved_yes", "resolved_yes_gamma"]))]
    excl_mask = auc.auction_slug.str.contains(EXCLUDE_SLUG)
    excluded_slugs = auc[excl_mask].auction_slug.tolist()
    auc = auc[~excl_mask]
    rows = []
    for _, r in auc.iterrows():
        w = noon_window(r.auction_slug, handle, int(r.start_utc.year))
        if w is None:
            continue
        s, e = w
        brackets = []
        for b in str(r.all_buckets).split(","):
            rng = parse_bucket_range(b)
            if rng:
                brackets.append((normalize_bucket(b), rng[0], rng[1]))
        if not brackets:
            continue
        winner = normalize_bucket(r.winning_bucket)
        if winner not in [b[0] for b in brackets]:
            continue
        rows.append(dict(slug=r.auction_slug, handle=handle, s=s, e=e, dur=dur,
                          winner=winner, brackets=brackets,
                          ladder=frozenset(b[0] for b in brackets)))
    rows.sort(key=lambda x: x["s"])
    return rows, raw_n, excluded_slugs


def load_prices(handle):
    files = sorted((CANON / "prices" / handle).glob("*.parquet"))
    prc = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    prc["bucket"] = prc["bucket"].apply(normalize_bucket)
    idx = {}
    for (slug, bucket), g in prc.sort_values("hour_utc").groupby(["auction_slug", "bucket"]):
        t = (g["hour_utc"].astype("int64") // 10**9).to_numpy().astype("int64")
        c = g["close"].to_numpy(dtype=float)
        idx[(slug, bucket)] = (t, c)
    return idx


def price_at(price_idx, slug, bucket, T):
    """Last hourly CLOSE at or before T -- THE WALL. Never reads a row with
    hour_utc > T (searchsorted side='right' then -1 picks the last index <= T)."""
    a = price_idx.get((slug, bucket))
    if a is None:
        return None
    ts, closes = a
    i = np.searchsorted(ts, T, side="right") - 1
    if i < 0:
        return None
    v = float(closes[i])
    return v if 0.0 <= v <= 1.0 else None


# ---------------------------------------------------------------------------
# 3. stats helpers
# ---------------------------------------------------------------------------
def wilson_ci(k, n, z=1.959963984540054):
    if n == 0:
        return (float("nan"), float("nan"))
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def block_bootstrap_ci(values, n_boot=N_BOOT_HEADLINE, seed=SEED):
    rng = np.random.default_rng(seed)
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    n = len(vals)
    if n == 0:
        return dict(mean=float("nan"), lo=float("nan"), hi=float("nan"), n=0)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        means[b] = vals[idx].mean()
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


def n_flag(n):
    return "OK" if n >= SUCCESS_N_FLOOR else f"BELOW_N_FLOOR(<{SUCCESS_N_FLOOR})"


# ---------------------------------------------------------------------------
# 4. per-group pipeline
# ---------------------------------------------------------------------------
def combo_label(std_ladder, idx_tuple):
    return " + ".join(std_ladder[i] for i in idx_tuple)


def own_admissible_stats(units, price_idx, slug_field, combo_labels, checkpoint_h):
    """TRUE per-combo admissibility: an auction counts ONLY if every leg of THIS combo
    (not the whole ladder) has a price at T. This is the literal per-combo admissible-n
    the task asks for, used for headline combos (small set, own bootstrap CI)."""
    costs, hits = [], []
    for u in units:
        T = u["s"] + checkpoint_h * 3600
        if T >= u["e"]:
            continue
        prices = [price_at(price_idx, u[slug_field], lbl, T) for lbl in combo_labels]
        if any(p is None for p in prices):
            continue
        costs.append(sum(prices))
        hits.append(1.0 if u["winner"] in combo_labels else 0.0)
    return np.array(costs), np.array(hits)


def pick_best_combo(pool_units, price_idx, std_ladder, all_combo_idx, checkpoint_h):
    """argmax-hitrate and argmax-ROI combo (by index tuple -> label tuple), computed on
    the full-ladder-priced admissible subset of `pool_units` ONLY. Used to select on
    TRAIN and then re-score on the disjoint SEALED span (rule 9's held-out re-score)."""
    m = len(std_ladder)
    adm = []
    for u in pool_units:
        T = u["s"] + checkpoint_h * 3600
        if T >= u["e"]:
            continue
        prices = [price_at(price_idx, u["slug"], lbl, T) for lbl in std_ladder]
        if any(p is None for p in prices):
            continue
        adm.append((u, prices))
    if len(adm) < 5:
        return None
    P = np.array([p for _, p in adm])
    W = np.zeros((len(adm), m))
    for i, (u, _) in enumerate(adm):
        W[i, std_ladder.index(u["winner"])] = 1.0
    IND = np.zeros((len(all_combo_idx), m))
    for r, idx_tuple in enumerate(all_combo_idx):
        IND[r, list(idx_tuple)] = 1.0
    cost_matrix = IND @ P.T
    hit_matrix = IND @ W.T
    mean_cost = cost_matrix.mean(axis=1)
    hit_rate = hit_matrix.mean(axis=1)
    mean_roi = np.divide(hit_rate - mean_cost, mean_cost,
                          out=np.full_like(mean_cost, -np.inf), where=mean_cost > 0)
    best_hit_idx = all_combo_idx[int(np.argmax(hit_rate))]
    best_roi_idx = all_combo_idx[int(np.argmax(mean_roi))]
    return (tuple(std_ladder[i] for i in best_hit_idx), tuple(std_ladder[i] for i in best_roi_idx))


def run_group(handle, dur, prefix_label):
    units_all, raw_n, excluded_slugs = load_auctions(handle, dur)
    price_idx = load_prices(handle)

    ladder_counts = Counter(u["ladder"] for u in units_all)
    std_ladder_set, n_std = ladder_counts.most_common(1)[0]
    std_ladder = sorted(std_ladder_set, key=lambda b: (parse_bucket_range(b) or (0, 0))[0])
    m = len(std_ladder)

    units = [u for u in units_all if u["ladder"] == std_ladder_set]
    excluded_ladder_rows = [dict(slug=u["slug"], ladder=sorted(u["ladder"]))
                             for u in units_all if u["ladder"] != std_ladder_set]

    train_units = [u for u in units if u["s"] < WALL]
    sealed_units = [u for u in units if u["s"] >= WALL]

    print(f"\n=== {handle} {dur} ===")
    print(f"  raw n (confidence=='high' & duration_type=='{dur}', no other filter) = {raw_n}")
    print(f"  n after resolved+arch-exclude = {len(units_all)} "
          f"(dropped {raw_n - len(units_all)}: unresolved/arch-slug)")
    print(f"  ladder distribution: {[(len(k), v) for k, v in ladder_counts.most_common(6)]}")
    print(f"  modal ladder ({m} rungs): {std_ladder}")
    print(f"  n consistent-ladder = {n_std}  |  n excluded (other ladder shape) = {len(excluded_ladder_rows)}")
    print(f"  TRAIN (s<wall) = {len(train_units)}   SEALED (s>=wall) = {len(sealed_units)}")

    # winner distribution (verifies the user's/orchestrator's numbers directly)
    wc_raw = Counter(u["winner"] for u in units_all)
    wc_std = Counter(u["winner"] for u in units)
    print(f"  winner dist (n={len(units_all)}, resolved+arch-excluded pop): {dict(wc_raw)}")
    print(f"  winner dist (n={len(units)}, consistent-ladder pop): {dict(wc_std)}")

    # ---- exhaustive combo hit-rate sweep (item 2) ----
    combo_rows = []
    all_combo_idx = []
    for k in range(1, MAX_COMBO_SIZE + 1):
        for idx_tuple in itertools.combinations(range(m), k):
            all_combo_idx.append(idx_tuple)
    for idx_tuple in all_combo_idx:
        labels = frozenset(std_ladder[i] for i in idx_tuple)
        for span_name, pool in (("full", units), ("sealed", sealed_units)):
            n = len(pool)
            k_hit = sum(1 for u in pool if u["winner"] in labels)
            lo, hi = wilson_ci(k_hit, n)
            combo_rows.append(dict(
                handle=handle, dur=dur, combo_size=len(idx_tuple),
                combo=combo_label(std_ladder, idx_tuple), span=span_name,
                n=n, k_hit=k_hit, hit_rate=(k_hit / n if n else float("nan")),
                wilson_lo=lo, wilson_hi=hi, n_flag=n_flag(n),
            ))
            _trial(f"{handle}_{dur}_hitrate_{span_name}")
    hit_df = pd.DataFrame(combo_rows)

    # ---- matched-population cost/EV sweep (items 3+4), one per checkpoint ----
    econ_rows = []
    gap_summaries = []
    scatter_data = {}
    for checkpoint_h in CHECKPOINTS_H:
        adm_units = []
        for u in units:
            T = u["s"] + checkpoint_h * 3600
            if T >= u["e"]:
                continue
            prices = [price_at(price_idx, u["slug"], lbl, T) for lbl in std_ladder]
            if any(p is None for p in prices):
                continue
            adm_units.append((u, prices))
        n_adm = len(adm_units)
        P = np.array([p for _, p in adm_units]) if n_adm else np.zeros((0, m))
        W = np.zeros((n_adm, m))
        for i, (u, _) in enumerate(adm_units):
            W[i, std_ladder.index(u["winner"])] = 1.0
        print(f"  checkpoint {checkpoint_h}h: full-ladder-priced admissible n = {n_adm}/{len(units)} "
              f"({100*n_adm/len(units) if units else 0:.1f}%)")

        if n_adm == 0:
            continue

        IND = np.zeros((len(all_combo_idx), m))
        for r, idx_tuple in enumerate(all_combo_idx):
            IND[r, list(idx_tuple)] = 1.0
        cost_matrix = IND @ P.T   # (n_combos, n_adm)
        hit_matrix = IND @ W.T    # (n_combos, n_adm), values in {0,1}
        mean_cost = cost_matrix.mean(axis=1)
        hit_rate = hit_matrix.mean(axis=1)
        pnl_matrix = hit_matrix - cost_matrix
        mean_pnl = pnl_matrix.mean(axis=1)
        mean_roi = np.divide(mean_pnl, mean_cost, out=np.full_like(mean_pnl, np.nan), where=mean_cost > 0)
        hit_k = hit_matrix.sum(axis=1)
        for r, idx_tuple in enumerate(all_combo_idx):
            lo, hi = wilson_ci(int(hit_k[r]), n_adm)
            econ_rows.append(dict(
                handle=handle, dur=dur, checkpoint_h=checkpoint_h, span="matched_full_ladder_priced",
                combo_size=len(idx_tuple), combo=combo_label(std_ladder, idx_tuple),
                n_admissible=n_adm, mean_cost=float(mean_cost[r]), hit_rate=float(hit_rate[r]),
                wilson_lo=lo, wilson_hi=hi, mean_pnl_per_auction=float(mean_pnl[r]),
                mean_roi_per_dollar=float(mean_roi[r]), n_flag=n_flag(n_adm),
            ))
            _trial(f"{handle}_{dur}_econ_ck{checkpoint_h}")

        # efficiency null: gap = hit_rate - cost, aggregated across ALL combos, with an
        # auction-level block bootstrap (resamples auctions, NOT combos -- combos are
        # non-independent linear combinations of the same underlying legs/auctions, so a
        # combo-level bootstrap would be pseudo-replication).
        gap_matrix = hit_matrix - cost_matrix
        gap_per_combo = gap_matrix.mean(axis=1)
        overall_gap = float(gap_per_combo.mean())
        boot = np.empty(N_BOOT_SWEEP_GAP)
        for b in range(N_BOOT_SWEEP_GAP):
            idx = RNG.integers(0, n_adm, n_adm)
            boot[b] = gap_matrix[:, idx].mean(axis=1).mean()
        slope, intercept = np.polyfit(mean_cost, hit_rate, 1)
        ss_res = float(np.sum((hit_rate - (slope * mean_cost + intercept)) ** 2))
        ss_tot = float(np.sum((hit_rate - hit_rate.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        gap_summaries.append(dict(
            handle=handle, dur=dur, checkpoint_h=checkpoint_h, n_admissible=n_adm,
            n_combos=len(all_combo_idx), mean_gap_hitrate_minus_cost=overall_gap,
            gap_ci_lo=float(np.percentile(boot, 2.5)), gap_ci_hi=float(np.percentile(boot, 97.5)),
            ols_slope=float(slope), ols_intercept=float(intercept), ols_r2=r2,
        ))
        scatter_data[checkpoint_h] = (mean_cost.copy(), hit_rate.copy(),
                                       np.array([len(t) for t in all_combo_idx]))
    econ_df = pd.DataFrame(econ_rows)
    gap_df = pd.DataFrame(gap_summaries)

    # ---- headline combos: user's combo, best-by-hitrate, best-by-ROI (own admissible pop) ----
    headline = []
    user_combo = frozenset({"<40", "40-64"}) if handle == "elonmusk" else None
    best4_combo = frozenset({"40-64", "65-89", "90-114", "115-139"}) if handle == "elonmusk" else None
    candidates = {}
    if user_combo and user_combo <= std_ladder_set:
        candidates["user_combo(<40+40-64)"] = tuple(sorted(user_combo,
                                                            key=lambda b: std_ladder.index(b)))
    if best4_combo and best4_combo <= std_ladder_set:
        candidates["user_named_4combo(40-64..115-139)"] = tuple(sorted(best4_combo,
                                                                        key=lambda b: std_ladder.index(b)))
    ck = PRIMARY_CHECKPOINT_H
    sub = econ_df[econ_df.checkpoint_h == ck] if not econ_df.empty else pd.DataFrame()
    if not sub.empty:
        best_hit_row = sub.loc[sub.hit_rate.idxmax()]
        best_roi_row = sub.loc[sub.mean_roi_per_dollar.idxmax()]
        # NOTE: selected using `units` = FULL population, which OVERLAPS the sealed span.
        # The "sealed" row reported below for these two is therefore NOT a clean disjoint
        # holdout -- it is descriptive only (selection leakage). See the TRAINselected
        # candidates below for the genuine held-out re-score (rule: "sweep -> hold out a
        # disjoint span to re-score the winner").
        candidates[f"best_hitrate@{ck}h_FULLselected(sealed-row-NOT-clean-holdout)"] = tuple(best_hit_row.combo.split(" + "))
        candidates[f"best_roi@{ck}h_FULLselected(sealed-row-NOT-clean-holdout)"] = tuple(best_roi_row.combo.split(" + "))

    # genuine disjoint held-out re-score: select the argmax combo using ONLY train_units
    # (s < WALL), then its "sealed" row below is a true out-of-sample confirmation.
    best_train = pick_best_combo(train_units, price_idx, std_ladder, all_combo_idx, ck)
    if best_train is not None:
        best_hit_labels_train, best_roi_labels_train = best_train
        candidates[f"best_hitrate@{ck}h_TRAINselected(sealed-row-IS-clean-holdout)"] = best_hit_labels_train
        candidates[f"best_roi@{ck}h_TRAINselected(sealed-row-IS-clean-holdout)"] = best_roi_labels_train

    for name, labels in candidates.items():
        labels_fs = frozenset(labels)
        for span_name, pool in (("full", units), ("train", train_units), ("sealed", sealed_units)):
            for checkpoint_h in CHECKPOINTS_H:
                costs, hits = own_admissible_stats(pool, price_idx, "slug", labels_fs, checkpoint_h)
                pnl = hits - costs
                n_adm = len(costs)
                if n_adm == 0:
                    continue
                boot = block_bootstrap_ci(pnl)
                jk = jackknife_drop_best(pnl)
                lo, hi = wilson_ci(int(hits.sum()), n_adm)
                headline.append(dict(
                    handle=handle, dur=dur, name=name, combo=" + ".join(labels),
                    span=span_name, checkpoint_h=checkpoint_h,
                    n_admissible=n_adm, n_flag=n_flag(n_adm),
                    hit_rate=float(hits.mean()), wilson_lo=lo, wilson_hi=hi,
                    mean_cost=float(costs.mean()), mean_pnl=boot["mean"],
                    pnl_ci_lo=boot["lo"], pnl_ci_hi=boot["hi"],
                    jk_full=jk["full_mean"], jk_dropbest=jk["dropbest_mean"], jk_sign_holds=jk["sign_holds"],
                ))
                _trial(f"{handle}_{dur}_headline_{name}_{span_name}")
    headline_df = pd.DataFrame(headline)

    # ---- scatter plot: cost vs hit-rate across all combos, primary checkpoint ----
    plot_path = None
    if PRIMARY_CHECKPOINT_H in scatter_data:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            cost, hr, sizes = scatter_data[PRIMARY_CHECKPOINT_H]
            fig, ax = plt.subplots(figsize=(6, 6))
            sc = ax.scatter(cost, hr, c=sizes, cmap="viridis", s=18, alpha=0.7)
            lim = [0, max(cost.max(), hr.max()) * 1.05]
            ax.plot(lim, lim, "r--", lw=1, label="efficient market (cost = hit rate)")
            ax.set_xlabel("combo cost ($, sum of leg closes)")
            ax.set_ylabel("combo hit rate (historical)")
            ax.set_title(f"{handle} {dur} @ {PRIMARY_CHECKPOINT_H}h -- combo cost vs hit rate\n"
                          f"(n_combos={len(scatter_data[PRIMARY_CHECKPOINT_H][0])}, matched-pop)")
            plt.colorbar(sc, label="combo size (legs)")
            ax.legend()
            plot_path = OUT / f"combo_scatter_{handle}_{dur}.png"
            fig.tight_layout()
            fig.savefig(plot_path, dpi=110)
            plt.close(fig)
        except Exception as ex:
            print(f"  [WARN] plot failed: {ex}")
            plot_path = None

    return dict(
        handle=handle, dur=dur, std_ladder=std_ladder, raw_n=raw_n,
        n_resolved_noarch=len(units_all), n_consistent=n_std,
        n_excluded_ladder=len(excluded_ladder_rows), excluded_ladder_rows=excluded_ladder_rows,
        excluded_arch_slugs=excluded_slugs, n_train=len(train_units), n_sealed=len(sealed_units),
        winner_dist_raw=dict(wc_raw), winner_dist_std=dict(wc_std),
        hit_df=hit_df, econ_df=econ_df, gap_df=gap_df, headline_df=headline_df,
        plot_path=str(plot_path) if plot_path else None,
    )


def main():
    elon = run_group("elonmusk", "2-day", ELON_PREFIX)
    trump = run_group("realDonaldTrump", "7-day", "donald-trump-of-truth-social-posts-")

    # user's specific numeric claims, reconciled explicitly against BOTH populations
    def combo_hit(units, labels):
        n = len(units)
        k = sum(1 for u in units if u["winner"] in labels)
        return k, n

    print("\n" + "=" * 70)
    print("USER CLAIM CHECK (Elon 2-day)")
    print("=" * 70)
    # recompute directly (not reusing elon['hit_df'] filtering) as an independent check
    raw_units, _, _ = load_auctions("elonmusk", "2-day")
    # raw_units already resolved+arch-excluded (this IS the n=67/68-ish population)
    k2, n2 = combo_hit(raw_units, frozenset({"<40", "40-64"}))
    k4, n4 = combo_hit(raw_units, frozenset({"40-64", "65-89", "90-114", "115-139"}))
    print(f"  <40 + 40-64            : {k2}/{n2} = {100*k2/n2:.1f}%  (user's original claim was ~80%)")
    print(f"  40-64+65-89+90-114+115-139 : {k4}/{n4} = {100*k4/n4:.1f}%  (the actual ~80% combo, needs 4 legs)")

    # write CSVs
    for res in (elon, trump):
        h = res["handle"]
        res["hit_df"].to_csv(OUT / f"combo_hitrates_{h}_{res['dur']}.csv", index=False)
        res["econ_df"].to_csv(OUT / f"combo_economics_{h}_{res['dur']}.csv", index=False)
        res["gap_df"].to_csv(OUT / f"efficiency_gap_{h}_{res['dur']}.csv", index=False)
        res["headline_df"].to_csv(OUT / f"headline_combos_{h}_{res['dur']}.csv", index=False)
        pd.DataFrame(res["excluded_ladder_rows"]).to_csv(
            OUT / f"excluded_ladder_auctions_{h}_{res['dur']}.csv", index=False)

    # single-bracket ("sell side") mispricing table, both handles, primary checkpoint
    mispricing = []
    for res in (elon, trump):
        sub = res["econ_df"]
        if sub.empty:
            continue
        sub1 = sub[(sub.combo_size == 1) & (sub.checkpoint_h == PRIMARY_CHECKPOINT_H)].copy()
        sub1["gap_hitrate_minus_cost"] = sub1.hit_rate - sub1.mean_cost
        sub1 = sub1.sort_values("gap_hitrate_minus_cost")
        mispricing.append(sub1[["handle", "dur", "combo", "n_admissible", "mean_cost",
                                 "hit_rate", "gap_hitrate_minus_cost", "n_flag"]])
    if mispricing:
        mispricing_df = pd.concat(mispricing, ignore_index=True)
        mispricing_df.to_csv(OUT / "single_bracket_mispricing.csv", index=False)
    else:
        mispricing_df = pd.DataFrame()

    print("\n" + "=" * 70)
    print(f"SINGLE-BRACKET MISPRICING @ {PRIMARY_CHECKPOINT_H}h (most negative gap = market OVERPAYS -> good to OFFER)")
    print("=" * 70)
    if not mispricing_df.empty:
        print(mispricing_df.to_string(index=False))

    print("\n" + "=" * 70)
    print("EFFICIENCY-NULL GAP (hit_rate - cost), all combos pooled, block-bootstrap by auction")
    print("=" * 70)
    for res in (elon, trump):
        if not res["gap_df"].empty:
            print(res["gap_df"].to_string(index=False))

    print("\n" + "=" * 70)
    print("HEADLINE COMBOS (own-admissible population, full/train/sealed)")
    print("=" * 70)
    for res in (elon, trump):
        if not res["headline_df"].empty:
            cols = ["handle", "name", "span", "checkpoint_h", "n_admissible", "n_flag",
                    "hit_rate", "mean_cost", "mean_pnl", "pnl_ci_lo", "pnl_ci_hi", "jk_sign_holds"]
            print(res["headline_df"][cols].to_string(index=False))

    # best combos by hit-rate AND by ROI, primary checkpoint, matched population
    print("\n" + "=" * 70)
    print(f"TOP 5 COMBOS BY HIT RATE and BY ROI/$ @ {PRIMARY_CHECKPOINT_H}h (matched-pop, FULL sample)")
    print("=" * 70)
    for res in (elon, trump):
        sub = res["econ_df"]
        if sub.empty:
            continue
        sub = sub[sub.checkpoint_h == PRIMARY_CHECKPOINT_H]
        print(f"-- {res['handle']} {res['dur']} -- by hit_rate --")
        print(sub.sort_values("hit_rate", ascending=False).head(5)[
            ["combo", "combo_size", "n_admissible", "mean_cost", "hit_rate", "mean_roi_per_dollar"]
        ].to_string(index=False))
        print(f"-- {res['handle']} {res['dur']} -- by ROI/$ --")
        print(sub.sort_values("mean_roi_per_dollar", ascending=False).head(5)[
            ["combo", "combo_size", "n_admissible", "mean_cost", "hit_rate", "mean_roi_per_dollar"]
        ].to_string(index=False))

    # ---- RUN_META ----
    headline_numbers = {
        "elon_2day_n_consistent_ladder": elon["n_consistent"],
        "elon_2day_n_train": elon["n_train"], "elon_2day_n_sealed": elon["n_sealed"],
        "user_combo_lt40_plus_40to64_hitrate_pct": round(100 * k2 / n2, 1),
        "user_named_4combo_hitrate_pct": round(100 * k4 / n4, 1),
        "elon_gap_ci_by_checkpoint": (elon["gap_df"].to_dict("records") if not elon["gap_df"].empty else None),
        "trump_gap_ci_by_checkpoint": (trump["gap_df"].to_dict("records") if not trump["gap_df"].empty else None),
        "n_auctions": elon["n_consistent"] + trump["n_consistent"],
    }
    emit_run_meta(
        script=__file__,
        headline=headline_numbers,
        data_paths=[str(CANON / "auctions" / "elonmusk"), str(CANON / "auctions" / "realDonaldTrump"),
                    str(CANON / "prices" / "elonmusk"), str(CANON / "prices" / "realDonaldTrump")],
        window_basis="noon-ET parsed from market slug (bracket_hit_backtest.py::noon() pattern, "
                      "reproduced locally, NOT trade-derived start_utc/end_utc)",
        fills=(
            "MAKER-ONLY framing (no crossing-the-spread simulated), but fill price = last hourly "
            "trade-derived CLOSE at-or-before decision T (canonical prices.close), NOT a confirmed "
            "L2 resting-bid fill -- no order-book history exists for most of this span "
            "(pmxt L2 archive starts 2026-04-13). UNVERIFIED fill-realism, disclosed as a "
            "last-print cost proxy that likely OVERSTATES true achievable maker cost (a patient "
            "resting bid fills below the last print), i.e. conservative-in-our-favor. Zero taker "
            "fee assumed for BUY legs is moot here since no fee-relevant crossing occurs in this "
            "cost-proxy computation; nothing here should be read as a fills-verified P&L claim."
        ),
        trial_count=TRIALS["n"],
        scope="accuracy/coverage-diagnostic + exhaustive-sweep (disclosed-assumption cost/EV, not fills-verified claims-P&L)",
        notes=json.dumps(dict(
            wall_utc=WALL, wall_note="single 2026-04-01 wall applied to BOTH handles (see docstring)",
            trials_detail=TRIALS["detail"],
            elon_excluded_ladder_n=elon["n_excluded_ladder"], trump_excluded_ladder_n=trump["n_excluded_ladder"],
            plots=[elon["plot_path"], trump["plot_path"]],
        ), default=str),
        out_dir="combo_out",
    )


if __name__ == "__main__":
    main()
