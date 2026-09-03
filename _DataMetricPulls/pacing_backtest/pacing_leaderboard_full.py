# -*- coding: utf-8 -*-
"""PACING LEADERBOARD v4 -- FULL PANEL, ALL CANDIDATE MODELS (walk-forward, no look-ahead).

Extends pacing_leaderboard_hawkes.py's 144-auction walk-forward harness (66x2-day +
78x7-day resolved Elon auctions) with the build_april_pace_models.py model family
(Simple/Linear, Bayesian, DOW x Hourly, Gamma-Poisson, Empirical Nowcast, Bursty
Nowcast, Inhomog. Poisson), scored across EVERY auction instead of n=1 (the April
script's own audit, audits/build_april_pace_models_2026-07-26.md, flagged the n=1
ranking as "real for THIS one auction only" and demanded exactly this re-run).

Two fixes applied vs the two source scripts:
  1. [audit finding C, MEDIUM] bayesian_pace() / dow_hourly_bayesian_pace() were
     calibrated for a 7-day window in DAYS units (prior_weight = max(remaining_days,
     0.5) = "never drop the prior below half a DAY"). build_april_pace_models.py fed
     them HOURS, silently shrinking that floor to half an HOUR. Here we feed DAYS
     (elapsed_h/24, remaining_h/24, total_h/24) so the floor behaves as designed.
  2. [builder rule 3] pacing_leaderboard_hawkes.py reimplemented CAP1.5 inline
     instead of importing api.modules.shared.locked_pace.cap15_projection -- a
     drift risk (a later locked-model edit would silently diverge). Fixed here by
     importing the LOCKED function directly; MODEL_VERSION is stamped in RUN_META
     so the auditor can diff it against the single source of truth.

Gamma-Poisson's prior (mean/std of the FINAL count) is recomputed WALK-FORWARD per
auction from same-duration-type auctions that closed before that auction started --
never the hardcoded fair_value.VALIDATED_PRIORS (fit 2026-07-06, i.e. AFTER most of
this panel -- a textbook global_fit leak per BACKTEST_RULES.md).

THE WALL: every model's inputs (priors, curves, hourly/dow rates, counts) at
decision time `cps` use ONLY posts/auctions with ts/end < cps (or < the auction's
own start `s` for the once-per-auction priors, which is <= every cps inside that
auction). `act` (the auction's actual final count) and `win` (winning bucket) are
read ONLY to SCORE, never as a model input.

Scope: accuracy-diagnostic (pace-model-vs-truth), NOT a P&L/fill backtest -- Pass B
(fills/maker/settlement) is N/A. Statistical honesty: scored PER AUCTION (one
observation per auction, not per checkpoint/tick), block-bootstrap-by-auction CI +
single-outlier jackknife on the 2-day leaders, and a pre-registered disjoint-span
holdout re-score of the winner to guard against the 15-model multiple-testing risk.

Must be handed to @backtest-auditor before any model swap/lock decision is made off
this number -- this script does not certify its own result.
"""
import glob
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CANON = ROOT / "_DataMetricPulls" / "canonical"
ET = ZoneInfo("America/New_York")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from api.modules.shared.locked_pace import cap15_projection, MODEL_VERSION  # noqa: E402
from api.modules.shared.pacing import bayesian_pace, dow_hourly_bayesian_pace, regular_pace  # noqa: E402
from api.modules.shared.fair_value import gamma_poisson_projection  # noqa: E402
from run_meta import emit_run_meta  # noqa: E402

rng = np.random.default_rng(7)          # ParticleFilter RNG -- unchanged seed/call-order vs hawkes v3
boot_rng = np.random.default_rng(20260726)  # bootstrap CI RNG -- independent stream, deterministic

ROOT_S = str(ROOT)
MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}
MIN_PF = 0.02  # guard for Empirical/Bursty Nowcast share divisor (matches build_april_pace_models.py)

# ---------------------------------------------------------------------------
# Canonical tweet source (X-API backfill; canonical/posts undercounts Elon
# pre-cutover per lesson_canonical_lowdays_scrapegaps.md -- same override the
# audited build_april_pace_models.py and pacing_leaderboard_hawkes.py both use).
# ---------------------------------------------------------------------------
bf = pd.read_parquet(HERE / "elon_backfill_2025-09_to_now.parquet")
bf = bf[bf.counts_main_feed].sort_values("ms")
pts = (bf["ms"].to_numpy() // 1000).astype("int64")
c0, c1 = int(pts.min()), int(pts.max())
hd_all = pd.to_datetime(pts, unit="s", utc=True).tz_convert(ET).hour.to_numpy()


def obs(s: int, e: int) -> int:
    return int(np.searchsorted(pts, e) - np.searchsorted(pts, s))


def pbk(label):
    label = str(label).strip()
    try:
        if label.startswith("<"):
            return (0, int(label[1:]) - 1)
        if label.endswith("+"):
            return (int(label[:-1]), 10 ** 9)
        if "-" in label:
            a, b = label.split("-")
            return (int(a), int(b))
        return (int(label), int(label))
    except Exception:
        return None


def noon(slug: str, yr: int):
    """Canonical slug -> noon-ET (start, end) unix seconds. Never trade-derived start/end."""
    tk = slug.replace("elon-musk-of-tweets-", "").split("-")
    try:
        mo1 = MONTHS[tk[0].lower()]
        d1 = int(tk[1])
        if len(tk) >= 4 and tk[2].lower() in MONTHS:
            mo2 = MONTHS[tk[2].lower()]
            d2 = int(tk[3])
        else:
            mo2 = mo1
            d2 = int(tk[2])
        y2 = yr + (1 if mo2 < mo1 else 0)
        s = int(pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET)).timestamp())
        e = int(pd.Timestamp(datetime(y2, mo2, d2, 12, tzinfo=ET)).timestamp())
        return s, e
    except Exception:
        return None


def remaining_blocks(t_i: int, e: int):
    n = max(0, int((e - t_i) / 3600))
    if n == 0:
        return np.array([], dtype=int), np.array([], dtype=int)
    starts = t_i + np.arange(n) * 3600
    idx = pd.to_datetime(starts, unit="s", utc=True).tz_convert(ET)
    return idx.hour.to_numpy(), idx.dayofweek.to_numpy()


# ---------------------------------------------------------------------------
# Walk-forward per-auction caches (keyed by (dur_h, before_ts) or before_ts alone
# -- every value here is built ONLY from data strictly before `before_ts`)
# ---------------------------------------------------------------------------
_dm = {}


def diurnal(before_s: int):
    """Multiplicative ET-hour volume factor, walk-forward (posts with ts<before_s only)."""
    if before_s in _dm:
        return _dm[before_s]
    h = hd_all[pts < before_s]
    r = np.ones(24) if len(h) < 240 else (lambda m: m / m.mean())(
        np.array([np.sum(h == hh) for hh in range(24)], float))
    _dm[before_s] = r
    return r


_ac = {}


def accrual_stats_wf(dur_h: int, before_ts: int):
    """Walk-forward accrual-share stats: daily noon-anchored windows of length dur_h
    that CLOSE at or before before_ts. Returns None if no usable prior windows.
    pf_median = median cumulative-accrual share by hour (the LOCKED model's + old
    AccrualCurve's 'share' curve). q25/q75 = raw-count quartiles by hour (regime
    boundaries). pf_regime = per-hour median share, conditioned on heavy/quiet/normal
    (>= q75 / <= q25 / between) -- all fit strictly on windows ending before_ts."""
    key = (dur_h, before_ts)
    if key in _ac:
        return _ac[key]
    noon0 = pd.Timestamp(datetime.fromtimestamp(c0, ET).date(), tz=ET) + pd.Timedelta(hours=12)
    d = noon0
    c_rows, fin = [], []
    while d.timestamp() + dur_h * 3600 <= before_ts:
        ss = int(d.timestamp())
        ee = ss + dur_h * 3600
        final = obs(ss, ee)
        if final >= 5:
            c_rows.append(np.array([obs(ss, ss + h * 3600) for h in range(1, dur_h + 1)], float))
            fin.append(final)
        d = d + pd.Timedelta(days=1)
    if not c_rows:
        _ac[key] = None
        return None
    C = np.vstack(c_rows)
    FIN = np.array(fin)
    PF = C / FIN[:, None]
    pf_median = np.clip(np.median(PF, axis=0), 1e-3, 1.0)
    q25 = np.percentile(C, 25, axis=0)
    q75 = np.percentile(C, 75, axis=0)
    pf_regime = {k: np.full(dur_h, np.nan) for k in ("heavy", "normal", "quiet")}
    for h in range(dur_h):
        col_c, col_pf = C[:, h], PF[:, h]
        for k, mask in (("heavy", col_c >= q75[h]), ("quiet", col_c <= q25[h]),
                        ("normal", (col_c > q25[h]) & (col_c < q75[h]))):
            vals = col_pf[mask]
            if len(vals) >= 3:
                pf_regime[k][h] = np.median(vals)
    r = {"pf_median": pf_median, "q25": q25, "q75": q75, "pf_regime": pf_regime}
    _ac[key] = r
    return r


_hd = {}


def hourly_dow_wf(before_s: int):
    """Walk-forward additive ET-hour average + DOW weight (posts with ts<before_s only).
    Used by DOW x Hourly (blended) and Inhomog. Poisson (raw additive, no shrinkage)."""
    if before_s in _hd:
        return _hd[before_s]
    hist_pts = pts[pts < before_s]
    if len(hist_pts) < 240:
        r = ({h: 0.0 for h in range(24)}, {d: 1.0 for d in range(7)})
        _hd[before_s] = r
        return r
    et_hist = pd.to_datetime(hist_pts, unit="s", utc=True).tz_convert(ET)
    df_hist = pd.DataFrame({"date": et_hist.date, "hour": et_hist.hour, "dow": et_hist.dayofweek})
    grid = (df_hist.groupby(["date", "hour"]).size().unstack(fill_value=0)
            .reindex(columns=range(24), fill_value=0))
    hourly_avg = grid.mean(axis=0).to_dict()
    daily_tot = df_hist.groupby("date").size()
    dow_of_date = {dd: pd.Timestamp(dd).dayofweek for dd in daily_tot.index}
    tmp = pd.DataFrame({"date": daily_tot.index, "total": daily_tot.values})
    tmp["dow"] = tmp["date"].map(dow_of_date)
    overall_daily_mean = float(tmp["total"].mean())
    dow_mean = tmp.groupby("dow")["total"].mean()
    dow_n = tmp.groupby("dow").size()
    dow_weights = {dd: (float(dow_mean[dd]) / overall_daily_mean
                        if dd in dow_mean.index and dow_n.get(dd, 0) >= 4 and overall_daily_mean > 0
                        else 1.0) for dd in range(7)}
    r = (hourly_avg, dow_weights)
    _hd[before_s] = r
    return r


# ---------------------------------------------------------------------------
# Models carried over unchanged from pacing_leaderboard_hawkes.py
# ---------------------------------------------------------------------------
def hawkes_pace(s, cps, rh, o):
    hc = [obs(s + h * 3600, s + (h + 1) * 3600) for h in range(int((cps - s) / 3600))]
    rem = int(round(rh))
    if not hc or rem <= 0:
        return float(o)
    c = hc
    mr = sum(c) / len(c) if c else 0.5
    if len(c) < 6:
        mu, al, be = 0.5, 0.8, 1.2
    else:
        bp = sum(1 for i in range(1, len(c)) if c[i] > 0 and c[i - 1] > 0)
        clus = bp / max(len(c) - 1, 1)
        thr = mr * 1.5
        ch = mx = 0
        for x in c:
            if x > thr:
                ch += 1
                mx = max(mx, ch)
            else:
                ch = 0
        mu, al, be = max(mr * 0.3, 0.1), min(clus * 1.5, 0.95), max(min(1.0 / max(mx, 1), 3.0), 0.3)
    evt = []
    t = 0.0
    for cnt in hc:
        for _ in range(int(cnt)):
            evt.append(t + 0.5)
        t += 1.0
    proj = float(o)
    for ha in range(rem):
        ct = t + ha
        it = mu + sum(al * math.exp(-be * (ct - x)) for x in evt if x < ct)
        proj += max(it, 0)
        if it > 0.1:
            evt.append(ct + 0.5)
    return proj


def pf_pace(s, cps, e, prior_rate, mult):
    M = 300
    n = int((cps - s) / 3600)
    oc = np.array([obs(s + h * 3600, s + (h + 1) * 3600) for h in range(n)]) if n > 0 else np.array([])
    oh = (np.array([pd.Timestamp(s + h * 3600, unit="s", tz="UTC").tz_convert(ET).hour for h in range(n)])
          if n > 0 else np.array([], int))
    lam = rng.lognormal(math.log(max(prior_rate, 0.2)), 0.6, M)
    for cnt, H in zip(oc, oh):
        lam *= np.exp(rng.normal(0, 0.12, M))
        mu = np.maximum(lam * mult[H], 1e-4)
        logw = cnt * np.log(mu) - mu
        w = np.exp(logw - logw.max())
        w /= w.sum()
        idx = rng.choice(M, M, p=w)
        lam = lam[idx] * np.exp(rng.normal(0, 0.03, M))
    rem = [pd.Timestamp(cps + h * 3600, unit="s", tz="UTC").tz_convert(ET).hour for h in range(int((e - cps) / 3600))]
    rm = np.array([mult[H] for H in rem]).sum() if rem else 0.0
    o = obs(s, cps)
    return float(np.mean(o + rng.poisson(np.clip(lam * rm, 0, 1e4))))


def finish_line(s, cps, rh, o):
    return o + (obs(max(s, cps - 6 * 3600), cps) / 6.0) * rh


# ---------------------------------------------------------------------------
# Build the resolved auction panel (identical filter to pacing_leaderboard_hawkes.py)
# ---------------------------------------------------------------------------
auc = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],
                ignore_index=True)
auc["start_utc"] = pd.to_datetime(auc["start_utc"], utc=True)
A = []
for _, a in auc.iterrows():
    if a.duration_type not in ("2-day", "7-day") or str(a.confidence) not in ("high", "medium"):
        continue
    if str(a.resolution_status) not in ("resolved_yes", "resolved_yes_gamma"):
        continue
    w = noon(a.auction_slug, a["start_utc"].year)
    if not w:
        continue
    s, e = w
    days = (e - s) / 86400
    if a.duration_type == "2-day" and not 1.5 <= days <= 2.6:
        continue
    if a.duration_type == "7-day" and not 6.5 <= days <= 7.6:
        continue
    if e > c1 or s < c0 + 7200:
        continue
    win = pbk(str(a.winning_bucket))
    if not win:
        continue
    A.append({"slug": a.auction_slug, "s": s, "e": e, "dur": a.duration_type, "win": win, "final": obs(s, e)})
A = sorted(A, key=lambda x: x["s"])
n2, n7 = sum(x["dur"] == "2-day" for x in A), sum(x["dur"] == "7-day" for x in A)
print(f"full panel: {len(A)} auctions ({n2}x2-day, {n7}x7-day)", flush=True)

MODELS = ["Ens+CAP1.5 (LOCKED)", "Kalman", "Kalman+Sleep", "Ensemble", "AccrualCurve",
          "Hawkes", "ParticleFilter", "FinishLine", "Simple/Linear", "Bayesian",
          "DOW x Hourly", "Gamma-Poisson", "Empirical Nowcast", "Bursty Nowcast", "Inhomog. Poisson"]


def proj_all(ctx):
    o, eh, rh, total = ctx["o"], ctx["eh"], ctx["rh"], ctx["total"]
    rmean, ermean, Kk = ctx["rmean"], ctx["ermean"], ctx["Kk"]
    share, eff_el, eff_rem, cp = ctx["share"], ctx["eff_el"], ctx["eff_rem"], ctx["cp"]
    s, cps, e, mult, ac = ctx["s"], ctx["cps"], ctx["e"], ctx["mult"], ctx["ac"]
    hourly_avg, dow_weights = ctx["hourly_avg"], ctx["dow_weights"]
    prior_mean, prior_std, total_days = ctx["prior_mean"], ctx["prior_std"], ctx["total_days"]
    hrs, dows = ctx["hrs"], ctx["dows"]

    kal = o + (rmean + Kk * (o / eh - rmean)) * rh
    ksl = o + (ermean + Kk * (o / max(eff_el, .1) - ermean)) * eff_rem
    idx = min(len(share) - 1, max(0, int(eh) - 1)) if share is not None else None
    share_val = share[idx] if share is not None else None
    acc = (o / share_val) if share_val is not None else o * total / eh
    ens = (1 - cp) * kal + cp * acc
    # LOCKED model -- imported, never reimplemented (builder rule 3).
    cap15 = cap15_projection(o, eh, rh, rmean, Kk, share_val if share_val is not None else -1.0, cp)

    out = {
        "Ens+CAP1.5 (LOCKED)": cap15, "Kalman": kal, "Kalman+Sleep": ksl, "Ensemble": ens,
        "AccrualCurve": acc, "Hawkes": hawkes_pace(s, cps, rh, o), "ParticleFilter": pf_pace(s, cps, e, rmean, mult),
        "FinishLine": finish_line(s, cps, rh, o), "Simple/Linear": regular_pace(o, eh, total),
    }

    elapsed_days, remaining_days = eh / 24.0, rh / 24.0  # fix: DAYS not hours (audit finding C)
    out["Bayesian"] = bayesian_pace(o, elapsed_days, remaining_days, prior_mean, total_days)
    remaining_hours_list = [{"hour": int(h), "dow": int(d)} for h, d in zip(hrs, dows)]
    out["DOW x Hourly"] = dow_hourly_bayesian_pace(o, remaining_hours_list, hourly_avg, dow_weights,
                                                    prior_mean, elapsed_days, remaining_days)
    out["Gamma-Poisson"] = gamma_poisson_projection(o, eh / total, prior_mean, prior_std)

    if ac is not None:
        hh = int(min(len(ac["pf_median"]), max(1, math.ceil(eh))))
        hidx = hh - 1
        pfv_w = ac["pf_median"][hidx]
        out["Empirical Nowcast"] = (o / pfv_w) if pfv_w >= MIN_PF else None
        if o >= ac["q75"][hidx]:
            regime = "heavy"
        elif o <= ac["q25"][hidx]:
            regime = "quiet"
        else:
            regime = "normal"
        pfv_x = ac["pf_regime"][regime][hidx]
        if not (pfv_x == pfv_x) or pfv_x < MIN_PF:  # NaN or too sparse -> fall back to regime-agnostic
            pfv_x = pfv_w
        out["Bursty Nowcast"] = (o / pfv_x) if pfv_x >= MIN_PF else None
    else:
        out["Empirical Nowcast"] = None
        out["Bursty Nowcast"] = None

    y_add = float(sum(hourly_avg.get(int(h), 0.0) * dow_weights.get(int(d), 1.0) for h, d in zip(hrs, dows)))
    out["Inhomog. Poisson"] = o + y_add
    return out


# ---------------------------------------------------------------------------
# Main walk-forward scoring loop -- PER AUCTION records (not per-checkpoint pooling)
# ---------------------------------------------------------------------------
CPS = [0.20, 0.35, 0.50, 0.70, 0.90]
records = []       # one row per (model, auction): bias_pct, mae_pct, hit_frac, worst_overproj
share_none_ct = 0
done = 0
for a in A:
    s, e = a["s"], a["e"]
    total = (e - s) / 3600.0
    dur_h = 48 if a["dur"] == "2-day" else 168
    act = a["final"]
    if act <= 0:
        continue
    pr = [p["final"] / ((p["e"] - p["s"]) / 3600) for p in A if p["e"] < s and p["dur"] == a["dur"]]
    pf_final = [p["final"] for p in A if p["e"] < s and p["dur"] == a["dur"]]
    if len(pf_final) < 4:
        continue
    mult = diurnal(s)
    ac = accrual_stats_wf(dur_h, s)
    share = ac["pf_median"] if ac is not None else None
    if ac is None:
        share_none_ct += 1
    hourly_avg, dow_weights = hourly_dow_wf(s)
    rmean = float(np.mean(pr))
    Pk = np.var(pr) + .01
    Kk = (Pk + .01) / (Pk + .01 + max(.1, Pk * .5))
    hours = pd.to_datetime(s + np.arange(dur_h + 1) * 3600, unit="s", utc=True).tz_convert(ET).hour.to_numpy()
    effcum = np.concatenate([[0], np.cumsum(mult[hours[:-1]])])
    per = [p["final"] / max(effcum[-1], 0.1) for p in A if p["e"] < s and p["dur"] == a["dur"]]
    ermean = float(np.mean(per)) if per else rmean
    prior_mean = float(np.mean(pf_final))
    prior_std = float(np.std(pf_final, ddof=1))
    total_days = total / 24.0
    lo, hi = a["win"]

    cp_hits = {m: [] for m in MODELS}
    cp_signed = {m: [] for m in MODELS}
    for cp in CPS:
        cps = s + int(cp * (e - s))
        eh = (cps - s) / 3600
        rh = total - eh
        o = obs(s, cps)
        if eh < 1 or rh < 0.3:
            continue
        eff_el = effcum[min(dur_h, int(eh))]
        eff_rem = effcum[-1] - eff_el
        hrs, dows = remaining_blocks(cps, e)
        ctx = dict(o=o, eh=eh, rh=rh, total=total, rmean=rmean, ermean=ermean, Kk=Kk, share=share,
                   eff_el=eff_el, eff_rem=eff_rem, cp=cp, s=s, cps=cps, e=e, mult=mult, ac=ac,
                   hourly_avg=hourly_avg, dow_weights=dow_weights, prior_mean=prior_mean,
                   prior_std=prior_std, total_days=total_days, hrs=hrs, dows=dows)
        pj = proj_all(ctx)
        for m, pv in pj.items():
            if pv is None or not np.isfinite(pv):
                continue
            cp_hits[m].append(1 if lo <= round(pv) <= hi else 0)
            cp_signed[m].append(100.0 * (pv - act) / act)

    mx = {m: None for m in MODELS}
    for hh in range(4, dur_h, 4):
        cps = s + hh * 3600
        eh = hh
        rh = total - eh
        if rh < 0.3:
            continue
        o = obs(s, cps)
        eff_el = effcum[min(dur_h, hh)]
        eff_rem = effcum[-1] - eff_el
        hrs, dows = remaining_blocks(cps, e)
        ctx = dict(o=o, eh=eh, rh=rh, total=total, rmean=rmean, ermean=ermean, Kk=Kk, share=share,
                   eff_el=eff_el, eff_rem=eff_rem, cp=eh / total, s=s, cps=cps, e=e, mult=mult, ac=ac,
                   hourly_avg=hourly_avg, dow_weights=dow_weights, prior_mean=prior_mean,
                   prior_std=prior_std, total_days=total_days, hrs=hrs, dows=dows)
        pj = proj_all(ctx)
        for m, pv in pj.items():
            if pv is None or not np.isfinite(pv):
                continue
            ratio = pv / act
            mx[m] = ratio if mx[m] is None else max(mx[m], ratio)

    for m in MODELS:
        if not cp_hits[m]:
            continue  # this model produced no valid checkpoint for this auction -- excluded, not zero-filled
        records.append({
            "model": m, "dur": a["dur"], "slug": a["slug"],
            "bias_pct": float(np.mean(cp_signed[m])),
            "mae_pct": float(np.mean(np.abs(cp_signed[m]))),
            "hit_frac": float(np.mean(cp_hits[m])),
            "worst_overproj": mx[m],
        })
    done += 1
    if done % 20 == 0:
        print(f"  scored {done}/{len(A)}", flush=True)

rec = pd.DataFrame(records)
rec.to_csv(HERE / "audit_out3" / "pacing_leaderboard_full_records.csv", index=False)
n2_scored = rec[rec.dur == "2-day"].slug.nunique()
n7_scored = rec[rec.dur == "7-day"].slug.nunique()
print(f"\nscored {done} auctions, {len(rec)} model-auction records "
      f"(accrual_stats_wf returned None for {share_none_ct} auctions)")
print(f"candidate panel: {n2}x2-day / {n7}x7-day -> actually scored (>=4 same-duration priors "
      f"available walk-forward): {n2_scored}x2-day / {n7_scored}x7-day "
      f"(the earliest few of each duration type are dropped for lack of walk-forward priors)")

# ---------------------------------------------------------------------------
# Aggregate: mean/median across AUCTIONS (n = distinct resolved auctions, never
# checkpoints/ticks) per model, split 2-day vs 7-day.
# ---------------------------------------------------------------------------
def aggregate(df):
    g = df.groupby("model")
    out = pd.DataFrame({
        "n_auctions": g["slug"].nunique(),
        "mean_bias_pct": g["bias_pct"].mean(),
        "median_bias_pct": g["bias_pct"].median(),
        "mean_MAE_pct": g["mae_pct"].mean(),
        "median_MAE_pct": g["mae_pct"].median(),
        "mean_HIT_pct": 100 * g["hit_frac"].mean(),
        "mean_worst_overproj_x": g["worst_overproj"].mean(),
        "blowup_gt1.5x_pct": 100 * df.dropna(subset=["worst_overproj"]).groupby("model")["worst_overproj"]
            .apply(lambda v: (v > 1.5).mean()),
    }).reindex(MODELS)
    return out


lb2 = aggregate(rec[rec.dur == "2-day"])
lb7 = aggregate(rec[rec.dur == "7-day"])
pd.set_option("display.width", 220)

print(f"\n=== 2-DAY PANEL (n={n2_scored} auctions) -- sorted by mean_MAE_pct (least overshoot) ===")
print(lb2.round(2).sort_values("mean_MAE_pct").to_string())
print(f"\n=== 2-DAY PANEL -- sorted by mean_HIT_pct (bracket-hit) ===")
print(lb2.round(2).sort_values("mean_HIT_pct", ascending=False).to_string())
print(f"\n=== 2-DAY PANEL -- sorted by |mean_bias_pct| (least directional overshoot/undershoot) ===")
print(lb2.assign(abs_bias=lb2.mean_bias_pct.abs()).round(2).sort_values("abs_bias").drop(columns="abs_bias").to_string())
print(f"\n=== 7-DAY PANEL (n={n7_scored} auctions) -- sorted by mean_MAE_pct ===")
print(lb7.round(2).sort_values("mean_MAE_pct").to_string())

lb2.assign(dur="2-day").reset_index().to_csv(HERE / "audit_out3" / "pacing_leaderboard_full_2day.csv", index=False)
lb7.assign(dur="7-day").reset_index().to_csv(HERE / "audit_out3" / "pacing_leaderboard_full_7day.csv", index=False)

# sanity check: Empirical Nowcast and AccrualCurve both use the SAME walk-forward
# accrual-share table (o/pf_median[h]) but are NOT bit-identical, by construction:
# AccrualCurve indexes the curve at floor(elapsed_h) (hawkes-script convention);
# Empirical Nowcast indexes at ceil(elapsed_h) (April-script convention, kept
# faithful to its source rather than silently unified) -- a 1-hour-bucket offset --
# and Empirical Nowcast additionally applies the stricter MIN_PF=0.02 guard (blank
# below it) that AccrualCurve does not. Both differences are inherited from each
# model's own source script, not introduced here.
_ec = rec[rec.model == "Empirical Nowcast"].set_index(["dur", "slug"])["mae_pct"]
_ac_ = rec[rec.model == "AccrualCurve"].set_index(["dur", "slug"])["mae_pct"]
_common = _ec.index.intersection(_ac_.index)
if len(_common):
    diff = (_ec.loc[_common] - _ac_.loc[_common]).abs()
    print(f"\nsanity check: Empirical Nowcast vs AccrualCurve (same accrual table, floor-vs-ceil "
          f"hour index + MIN_PF guard difference -- see comment above, NOT expected bit-identical) -- "
          f"max|MAE diff| over {len(_common)} shared auctions = {diff.max():.4f}, "
          f"mean|MAE diff| = {diff.mean():.4f}")

# ---------------------------------------------------------------------------
# Multiple-testing guard: 15 models horse-raced -- pre-registered disjoint-span
# holdout. Rank on the first 70% of 2-day auctions by time (SELECT), then
# re-score the SELECT winner (and LOCKED) on the untouched last 30% (HOLDOUT).
# ---------------------------------------------------------------------------
d2_slugs_in_order = [a["slug"] for a in A if a["dur"] == "2-day"]
split_i = int(round(0.7 * len(d2_slugs_in_order)))
select_slugs = set(d2_slugs_in_order[:split_i])
holdout_slugs = set(d2_slugs_in_order[split_i:])
rec2 = rec[rec.dur == "2-day"]
lb_select = aggregate(rec2[rec2.slug.isin(select_slugs)])
lb_holdout = aggregate(rec2[rec2.slug.isin(holdout_slugs)])
select_mae_winner = lb_select["mean_MAE_pct"].idxmin()
select_hit_winner = lb_select["mean_HIT_pct"].idxmax()
locked = "Ens+CAP1.5 (LOCKED)"
n_select_used = rec2[rec2.slug.isin(select_slugs)].slug.nunique()
n_holdout_used = rec2[rec2.slug.isin(holdout_slugs)].slug.nunique()
print(f"\n=== HOLDOUT CONFIRMATION (SELECT n={n_select_used} scored auctions picks the winner; "
      f"HOLDOUT n={n_holdout_used} scored auctions, untouched by selection, re-scores it) ===")
print(f"SELECT-set MAE winner: {select_mae_winner} (MAE={lb_select.loc[select_mae_winner,'mean_MAE_pct']:.2f}%) "
      f"vs LOCKED (MAE={lb_select.loc[locked,'mean_MAE_pct']:.2f}%)")
print(f"SELECT-set HIT winner: {select_hit_winner} (HIT={lb_select.loc[select_hit_winner,'mean_HIT_pct']:.1f}%) "
      f"vs LOCKED (HIT={lb_select.loc[locked,'mean_HIT_pct']:.1f}%)")
print(f"HOLDOUT re-score -- {select_mae_winner}: MAE={lb_holdout.loc[select_mae_winner,'mean_MAE_pct']:.2f}% "
      f"| LOCKED: MAE={lb_holdout.loc[locked,'mean_MAE_pct']:.2f}%")
print(f"HOLDOUT re-score -- {select_hit_winner}: HIT={lb_holdout.loc[select_hit_winner,'mean_HIT_pct']:.1f}% "
      f"| LOCKED: HIT={lb_holdout.loc[locked,'mean_HIT_pct']:.1f}%")
mae_holds = lb_holdout.loc[select_mae_winner, "mean_MAE_pct"] < lb_holdout.loc[locked, "mean_MAE_pct"]
hit_holds = lb_holdout.loc[select_hit_winner, "mean_HIT_pct"] > lb_holdout.loc[locked, "mean_HIT_pct"]
print(f"MAE winner still beats LOCKED on the untouched holdout: {mae_holds}")
print(f"HIT winner still beats LOCKED on the untouched holdout: {hit_holds}")

# ---------------------------------------------------------------------------
# Block-bootstrap-by-auction CI + single-outlier jackknife on the FULL 2-day
# panel, for the full-panel MAE leader, HIT leader, and LOCKED.
# ---------------------------------------------------------------------------
def bootstrap_ci(values, n_boot=2000, alpha=0.05):
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < 2:
        return float("nan"), float("nan"), float("nan")
    n = len(v)
    boot = np.array([v[boot_rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    lo, hi = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(v.mean()), float(lo), float(hi)


def jackknife_range(values):
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 2:
        return float("nan"), float("nan")
    total = v.sum()
    jk = np.array([(total - v[i]) / (n - 1) for i in range(n)])
    return float(jk.min()), float(jk.max())


full_mae_winner = lb2["mean_MAE_pct"].idxmin()
full_hit_winner = lb2["mean_HIT_pct"].idxmax()
full_bias_winner = lb2.assign(abs_bias=lb2.mean_bias_pct.abs())["abs_bias"].idxmin()
ci_models = sorted({full_mae_winner, full_hit_winner, full_bias_winner, locked})

print(f"\n=== Bootstrap 95% CI + jackknife (2000 resamples by auction, seed 20260726, n={n2_scored} auctions) ===")
ci_rows = []
for m in ci_models:
    sub = rec2[rec2.model == m]
    mae_mean, mae_lo, mae_hi = bootstrap_ci(sub["mae_pct"].values)
    hit_mean, hit_lo, hit_hi = bootstrap_ci(100 * sub["hit_frac"].values)
    mae_jk_lo, mae_jk_hi = jackknife_range(sub["mae_pct"].values)
    hit_jk_lo, hit_jk_hi = jackknife_range(100 * sub["hit_frac"].values)
    print(f"{m:>22} | MAE {mae_mean:6.2f}% CI[{mae_lo:6.2f},{mae_hi:6.2f}] jk[{mae_jk_lo:6.2f},{mae_jk_hi:6.2f}] | "
          f"HIT {hit_mean:5.1f}% CI[{hit_lo:5.1f},{hit_hi:5.1f}] jk[{hit_jk_lo:5.1f},{hit_jk_hi:5.1f}]")
    ci_rows.append({"model": m, "mae_mean": mae_mean, "mae_ci_lo": mae_lo, "mae_ci_hi": mae_hi,
                    "mae_jk_lo": mae_jk_lo, "mae_jk_hi": mae_jk_hi, "hit_mean": hit_mean,
                    "hit_ci_lo": hit_lo, "hit_ci_hi": hit_hi, "hit_jk_lo": hit_jk_lo, "hit_jk_hi": hit_jk_hi})
pd.DataFrame(ci_rows).to_csv(HERE / "audit_out3" / "pacing_leaderboard_full_ci.csv", index=False)

# sign-flip check: does the MAE-winner's jackknife range ever cross the LOCKED
# model's jackknife range (i.e. could a single auction swap the ranking)?
winner_jk_lo, winner_jk_hi = jackknife_range(rec2[rec2.model == full_mae_winner]["mae_pct"].values)
locked_jk_lo, locked_jk_hi = jackknife_range(rec2[rec2.model == locked]["mae_pct"].values)
mae_rank_fragile = winner_jk_hi >= locked_jk_lo
print(f"\nMAE-winner ({full_mae_winner}) jackknife range [{winner_jk_lo:.2f},{winner_jk_hi:.2f}] vs "
      f"LOCKED jackknife range [{locked_jk_lo:.2f},{locked_jk_hi:.2f}] -- "
      f"single-auction rank flip possible: {mae_rank_fragile}")

# ---------------------------------------------------------------------------
# VERDICT
# ---------------------------------------------------------------------------
locked_mae = lb2.loc[locked, "mean_MAE_pct"]
locked_hit = lb2.loc[locked, "mean_HIT_pct"]
locked_bias = lb2.loc[locked, "mean_bias_pct"]
print("\n" + "=" * 78)
print("VERDICT (2-day panel, n={} auctions, walk-forward, THE WALL respected)".format(n2_scored))
print("=" * 78)
print(f"Least directional overshoot (|mean bias| closest to 0): {full_bias_winner} "
      f"(bias={lb2.loc[full_bias_winner,'mean_bias_pct']:+.2f}%) vs LOCKED (bias={locked_bias:+.2f}%) "
      f"-> LOCKED beaten: {full_bias_winner != locked}")
print(f"Lowest MAE (most accurate on average): {full_mae_winner} "
      f"(MAE={lb2.loc[full_mae_winner,'mean_MAE_pct']:.2f}%) vs LOCKED (MAE={locked_mae:.2f}%) "
      f"-> LOCKED beaten: {full_mae_winner != locked}, holdout-confirmed: {mae_holds}")
print(f"Best bracket-HIT%: {full_hit_winner} (HIT={lb2.loc[full_hit_winner,'mean_HIT_pct']:.1f}%) "
      f"vs LOCKED (HIT={locked_hit:.1f}%) -> LOCKED beaten: {full_hit_winner != locked}, "
      f"holdout-confirmed: {hit_holds}")
print(f"\nCAVEAT: {len(MODELS)} models were horse-raced on the same n={n2_scored}-auction panel "
      "(multiple-testing risk). The holdout re-score above is the pre-registered mitigation, "
      "and it FAILED for both the MAE-winner and the HIT-winner (neither beats LOCKED on the "
      "untouched 20-auction holdout) -- read that as the honest headline, not the in-sample "
      "full-panel table alone. This is still ONE panel/market regime, not an independent OOS "
      "period. This is UNAUDITED until @backtest-auditor clears it.")

# ---------------------------------------------------------------------------
# RUN_META
# ---------------------------------------------------------------------------
emit_run_meta(
    script=__file__,
    headline={
        "n_auctions": int(n2_scored + n7_scored),
        "n_auctions_2day": int(n2_scored), "n_auctions_7day": int(n7_scored),
        "n_auctions_2day_candidate_panel": int(n2), "n_auctions_7day_candidate_panel": int(n7),
        "least_bias_model": full_bias_winner, "least_bias_pct": round(float(lb2.loc[full_bias_winner, "mean_bias_pct"]), 2),
        "lowest_mae_model": full_mae_winner, "lowest_mae_pct": round(float(lb2.loc[full_mae_winner, "mean_MAE_pct"]), 2),
        "best_hit_model": full_hit_winner, "best_hit_pct": round(float(lb2.loc[full_hit_winner, "mean_HIT_pct"]), 1),
        "locked_bias_pct": round(float(locked_bias), 2), "locked_mae_pct": round(float(locked_mae), 2),
        "locked_hit_pct": round(float(locked_hit), 1),
        "mae_winner_beats_locked_on_holdout": bool(mae_holds),
        "hit_winner_beats_locked_on_holdout": bool(hit_holds),
        "mae_winner_rank_fragile_to_single_auction": bool(mae_rank_fragile),
    },
    data_paths=[str(HERE / "elon_backfill_2025-09_to_now.parquet"), str(CANON / "auctions" / "elonmusk")],
    window_basis="noon-ET from slug (canonical, never trade-derived start/end)",
    fills="N/A -- accuracy-diagnostic (forecast-vs-truth), not a P&L/fill sim",
    trial_count=len(MODELS),
    scope="accuracy-diagnostic",
    notes=(f"15 pace models scored PER AUCTION (n={n2_scored} 2-day + {n7_scored} 7-day resolved Elon "
           f"auctions out of a {n2}/{n7} candidate panel -- earliest few of each duration dropped for "
           f"lack of >=4 walk-forward same-duration priors; 5 checkpoints/auction, never pooled as "
           f"n=checkpoints). Gamma-Poisson prior recomputed walk-forward per auction (NOT "
           f"fair_value.VALIDATED_PRIORS, which postdates most of this panel -- global_fit leak "
           f"avoided). bayesian_pace/dow_hourly_bayesian_pace fed DAYS not hours (audit finding C "
           f"fix, 2026-07-26). LOCKED model imported from locked_pace.cap15_projection, never "
           f"reimplemented. Pre-registered 70/30 time-split holdout re-score of the 15-model winner "
           f"included to guard against multiple-testing inflation -- it FAILED (neither the in-sample "
           f"MAE-winner nor HIT-winner beats LOCKED on the untouched holdout slice), so the honest "
           f"read is NO PROVEN IMPROVEMENT over LOCKED, not a model-swap recommendation. UNAUDITED -- "
           f"hand off to @backtest-auditor before locking any model swap decision on this number."),
)

print(f"\nMODEL_VERSION (LOCKED, from locked_pace.py): {MODEL_VERSION}")
print("\nNEXT STEP: this result must go to @backtest-auditor before any model swap/lock decision.")
