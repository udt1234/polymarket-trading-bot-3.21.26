# -*- coding: utf-8 -*-
"""April 16-18 2026 2-day auction, SEESAW engine (unchanged mechanic), DE-BIASED BURSTY NOWCAST
driving the center instead of the LOCKED Ens+CAP1.5 model.

WHY: Ens+CAP1.5 overshoots on this auction (drove the -$2,200 loss in the existing
New_Backtest_Clean_7.13.2026 tab, buying high brackets on a 152-ish projection when the
actual final was 77). Bursty Nowcast (build_april_pace_models.py column X /
pacing_leaderboard_full.py "Bursty Nowcast") has a known systematic bias -- but that
bias figure (+3.17%) was measured on a 61-auction FULL PANEL that includes April 16-18
itself and future auctions. Using it here would be a global_fit leak (BACKTEST_RULES.md
leak #3). This script instead fits the correction WALK-FORWARD: only 2-day auctions that
CLOSED strictly before 2026-04-16 12:00 ET feed the bias estimate `b`. The live sim then
applies `debiased = raw_bursty / (1+b)` at every decision point inside the auction.

THE WALL:
  - `b` is fit on auctions with end < S0 (this auction's own start) only.
  - The target auction's own accrual-share table (ac_target) is built walk-forward via
    accrual_stats_wf(48, S0) -- daily noon-anchored 48h windows closing at/before S0.
  - Per-event inputs (count o, elapsed eh) use only tweets with ts <= that event's own ts.
  - ACTUAL_FINAL (77) and WIN bucket are used ONLY to score/settle, never as model inputs.
  - calib_sigma + bracket_fair are IMPORTED from api.modules.shared.locked_pace (LOCKED
    model, builder rule 3) -- never reimplemented.

EVERYTHING ELSE is copied unchanged from single_auction_seesaw.py: EDGE=0.02, UNIT=$20/trade,
per-tweet-per-bracket 1-trade cap, GATE_H=3h, the data-coverage guard, hold-to-resolution
settlement. The ONLY variable swapped is the center/pace model (Ens+CAP1.5 -> de-biased
Bursty Nowcast), to isolate that one change.

KNOWN, INHERITED, NOT-NEW LIMITATION (flag loudly, do not hide): single_auction_seesaw.py's
fill mechanic is TAKER-CROSSING -- it buys at the live best ASK and sells at the live best
BID the instant the edge condition is true, full $20 notional, no depth cap, no queue/rest
time, zero fee. That is not a maker-resting sim and does not satisfy BACKTEST_RULES fill
realism on its own. This script keeps that mechanic UNCHANGED (per the explicit task: swap
ONLY the center) so the P&L delta vs the existing -$2,200 LOCKED-driven run isolates the
center-model effect. The ABSOLUTE dollar P&L from either run should be treated as
UNVERIFIED fill-realism; the RELATIVE comparison (does de-biasing reduce overshoot / stop
buying too-high brackets / move the P&L) is the meaningful read here.

n=1 auction. This is an anecdote about the de-bias mechanism working as designed, not proof
of a live edge. UNAUDITED -- hand off to @backtest-auditor before trusting any number here."""
import glob
import json
import math
import os
import re
import subprocess
import sys
import datetime as dt
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CANON = ROOT / "_DataMetricPulls" / "canonical"
PMX = ROOT / "_DataMetricPulls" / "pmxt_pulled"
OUTD = HERE / "audit_out_debiased_bursty"
OUTD.mkdir(parents=True, exist_ok=True)
ET = ZoneInfo("America/New_York")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from api.modules.shared.locked_pace import calib_sigma, bracket_fair, MODEL_VERSION  # noqa: E402
from run_meta import emit_run_meta  # noqa: E402

SLUG = "elon-musk-of-tweets-april-16-april-18"
EDGE = 0.02
UNIT = 20.0
GATE_H = 3.0
SIGMA_MAX = 100.0
MIN_PF = 0.02
CPS_BIAS = [0.20, 0.35, 0.50, 0.70, 0.90]  # same checkpoint scheme as pacing_leaderboard_full.py

MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


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


def bmid(l):
    lo, hi = pbk(l)
    return lo + 12.0 if hi >= 10 ** 9 else ((hi + 1) / 2.0 if lo == 0 else (lo + hi) / 2.0)


def noon(slug, yr):
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


# ---------------------------------------------------------------------------
# Tweet data (the ONLY trustworthy Elon tweet-count source -- X-API backfill)
# ---------------------------------------------------------------------------
bf = pd.read_parquet(HERE / "elon_backfill_2025-09_to_now.parquet")
bf = bf[bf.counts_main_feed].sort_values("ms")
pts = (bf["ms"].to_numpy() // 1000).astype("int64")
bfms = bf["ms"].to_numpy().astype("int64")
c0, c1 = int(pts.min()), int(pts.max())


def obs(a, b):
    return int(np.searchsorted(pts, b) - np.searchsorted(pts, a))


# ---------------------------------------------------------------------------
# accrual_stats_wf -- WALK-FORWARD accrual-share + regime table, copied verbatim
# from pacing_leaderboard_full.py (already-audited methodology, not reinvented).
# ---------------------------------------------------------------------------
_ac_cache = {}


def accrual_stats_wf(dur_h, before_ts):
    key = (dur_h, before_ts)
    if key in _ac_cache:
        return _ac_cache[key]
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
        _ac_cache[key] = None
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
    _ac_cache[key] = r
    return r


def bursty_raw(o, eh, ac):
    """Bursty Nowcast RAW (not de-biased) projection. Identical math to
    build_april_pace_models.py column X / pacing_leaderboard_full.py 'Bursty Nowcast'."""
    if ac is None:
        return None
    dur_h = len(ac["pf_median"])
    hh = int(min(dur_h, max(1, math.ceil(eh))))
    hidx = hh - 1
    pfv_w = ac["pf_median"][hidx]
    if o >= ac["q75"][hidx]:
        regime = "heavy"
    elif o <= ac["q25"][hidx]:
        regime = "quiet"
    else:
        regime = "normal"
    pfv_x = ac["pf_regime"][regime][hidx]
    if not (pfv_x == pfv_x) or pfv_x < MIN_PF:  # NaN or too sparse -> fall back to regime-agnostic
        pfv_x = pfv_w
    if pfv_x < MIN_PF:
        return None
    return o / pfv_x


# ---------------------------------------------------------------------------
# Candidate 2-day auction panel (same filter as pacing_leaderboard_full.py)
# ---------------------------------------------------------------------------
auc = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],
                ignore_index=True)
auc["start_utc"] = pd.to_datetime(auc["start_utc"], utc=True)
A = []
for _, a in auc.iterrows():
    if a.duration_type != "2-day" or str(a.confidence) not in ("high", "medium"):
        continue
    if str(a.resolution_status) not in ("resolved_yes", "resolved_yes_gamma"):
        continue
    w = noon(a.auction_slug, a["start_utc"].year)
    if not w:
        continue
    s_, e_ = w
    days = (e_ - s_) / 86400
    if not 1.5 <= days <= 2.6:
        continue
    if e_ > c1 or s_ < c0 + 7200:
        continue
    win = pbk(str(a.winning_bucket))
    if not win:
        continue
    A.append({"slug": a.auction_slug, "s": s_, "e": e_, "win": win, "final": obs(s_, e_)})
A = sorted(A, key=lambda x: x["s"])
print(f"candidate 2-day panel (full history, resolved, confidence high/medium): n={len(A)}")

# ---------------------------------------------------------------------------
# Target auction
# ---------------------------------------------------------------------------
row = auc[auc.auction_slug == SLUG].iloc[0]
WIN = str(row.winning_bucket)
wlo, whi = pbk(WIN)
tok = row.bracket_yes_token_ids
tok = json.loads(tok) if isinstance(tok, str) else dict(tok)
S0, E0 = noon(SLUG, 2026)
total = (E0 - S0) / 3600.0
ACTUAL_FINAL = obs(S0, E0)
assert abs(total - 48.0) < 0.01, f"target window not 48h: {total}"
assert ACTUAL_FINAL == 77, f"actual final mismatch vs task spec: {ACTUAL_FINAL} != 77"
print(f"TARGET {SLUG} | {datetime.fromtimestamp(S0, ET):%m-%d %H:%M}->{datetime.fromtimestamp(E0, ET):%m-%d %H:%M} ET "
      f"| WINNER {WIN} | actual final {ACTUAL_FINAL}")

# ---------------------------------------------------------------------------
# WALK-FORWARD de-bias: b fit ONLY on 2-day auctions closing strictly before S0
# ---------------------------------------------------------------------------
prior_panel = [a for a in A if a["e"] < S0]
assert len(prior_panel) >= 8, f"too few walk-forward prior 2-day auctions before target start: {len(prior_panel)}"

bias_recs = []
ac_none_ct = 0
for p in prior_panel:
    ps, pe, act = p["s"], p["e"], p["final"]
    if act <= 0:
        continue
    ac_p = accrual_stats_wf(48, ps)
    if ac_p is None:
        ac_none_ct += 1
        continue
    for cp in CPS_BIAS:
        cps = ps + int(cp * (pe - ps))
        eh = (cps - ps) / 3600.0
        if eh < 1:
            continue
        o_ = obs(ps, cps)
        raw = bursty_raw(o_, eh, ac_p)
        if raw is None or not np.isfinite(raw):
            continue
        bias_recs.append({"slug": p["slug"], "cp": cp, "bias_pct": 100.0 * (raw - act) / act})
assert len(bias_recs) >= 5, "too few walk-forward bias checkpoints -- cannot compute b honestly"
bdf = pd.DataFrame(bias_recs)
b_const = float(bdf["bias_pct"].mean()) / 100.0
n_prior_auctions_used = bdf["slug"].nunique()
n_checkpoints_used = len(bdf)
max_prior_e = max(p["e"] for p in prior_panel)
print(f"\nWALK-FORWARD BIAS: prior_panel n={len(prior_panel)} 2-day auctions closing before target start "
      f"(latest closes {datetime.fromtimestamp(max_prior_e, ET):%Y-%m-%d %H:%M} ET, "
      f"< target start {datetime.fromtimestamp(S0, ET):%Y-%m-%d %H:%M} ET -- confirmed) | "
      f"{ac_none_ct} auctions dropped for lack of walk-forward accrual priors")
print(f"scored: {n_prior_auctions_used} auctions x up to {len(CPS_BIAS)} checkpoints = {n_checkpoints_used} records")
print(f"b (constant, mean signed bias %) = {b_const * 100:+.2f}%")

# block-bootstrap-by-auction CI on b (honest uncertainty on the single number the whole
# de-bias correction hinges on)
_bt_rng = np.random.default_rng(20260416)
means_by_slug = bdf.groupby("slug")["bias_pct"].mean().values
_n = len(means_by_slug)
_boots = np.array([_bt_rng.choice(means_by_slug, size=_n, replace=True).mean() for _ in range(2000)]) if _n >= 2 else np.array([b_const * 100])
b_ci_lo, b_ci_hi = (float(np.percentile(_boots, 2.5)), float(np.percentile(_boots, 97.5))) if _n >= 2 else (float("nan"), float("nan"))
print(f"b 95% block-bootstrap-by-auction CI: [{b_ci_lo:+.2f}%, {b_ci_hi:+.2f}%]  (n={_n} prior auctions)")
if n_prior_auctions_used < 15:
    print(f"CAVEAT: b fit on only {n_prior_auctions_used} prior auctions -- small-n, the CI above is wide/fragile, "
          f"treat b as a rough correction, not a precise calibration.")

# per-checkpoint (horizon-dependent) breakdown -- decide whether it's worth using instead
# of the single constant, per task's optional clause. Rule: only switch if the spread across
# checkpoints is large (>8pp) AND every checkpoint bucket has enough auctions (>=8) to trust --
# otherwise a 5-point correction on ~15-30 auctions would overfit noise.
per_cp = bdf.groupby("cp").agg(bias_mean=("bias_pct", "mean"), n=("bias_pct", "size")).reindex(CPS_BIAS)
print("\nper-checkpoint (horizon) bias breakdown:")
print(per_cp.round(2).to_string())
cp_means = per_cp["bias_mean"].dropna()
cp_spread = float(cp_means.max() - cp_means.min()) if len(cp_means) >= 2 else 0.0
cp_min_n = int(per_cp["n"].min()) if len(per_cp) else 0
USE_HORIZON = (cp_spread > 8.0) and (cp_min_n >= 8)
if USE_HORIZON:
    cp_xs = [cp * 48.0 for cp in cp_means.index]
    cp_ys = [v / 100.0 for v in cp_means.values]

    def b_of_eh(eh):
        if eh <= cp_xs[0]:
            return cp_ys[0]
        if eh >= cp_xs[-1]:
            return cp_ys[-1]
        for i in range(1, len(cp_xs)):
            if eh <= cp_xs[i]:
                x0, x1, y0, y1 = cp_xs[i - 1], cp_xs[i], cp_ys[i - 1], cp_ys[i]
                return y0 + (y1 - y0) * (eh - x0) / (x1 - x0)
        return cp_ys[-1]

    bias_desc = f"HORIZON-DEPENDENT (5-point walk-forward interp; spread={cp_spread:.1f}pp > 8pp AND min bucket n={cp_min_n} >= 8)"
else:
    def b_of_eh(eh):
        return b_const

    bias_desc = (f"SINGLE CONSTANT b={b_const * 100:+.2f}% (per-checkpoint spread={cp_spread:.1f}pp <= 8pp "
                 f"or min bucket n={cp_min_n} < 8 -- insufficient evidence of horizon-dependence; "
                 f"parsimony favors the constant over a 5-point fit on this few auctions)")
print(f"\nDECISION: {bias_desc}")

# de-biased final projection at S0 using the constant b (headline number the task asks for)
ac_target = accrual_stats_wf(48, S0)
assert ac_target is not None, "no walk-forward accrual stats available for target auction"
raw_at_full = bursty_raw(ACTUAL_FINAL, 48.0, ac_target)
debiased_at_full = raw_at_full / (1.0 + b_const) if raw_at_full is not None else None
print(f"\n[sanity check, NOT used live] Bursty projection AT the true final count/hour "
      f"(o={ACTUAL_FINAL}, eh=48): raw={raw_at_full:.1f} -> de-biased={debiased_at_full:.1f} "
      f"(should sit close to {ACTUAL_FINAL} by construction -- confirms pf_median[47] normalizes near 1.0)")

# informational-only full-panel bias (all auctions incl. target + future) for comparison
# against Sir's stated +3.17% figure -- NEVER used for the correction, sanity check only.
full_recs = []
for p in A:
    ac_p = accrual_stats_wf(48, p["s"])
    if ac_p is None:
        continue
    for cp in CPS_BIAS:
        cps = p["s"] + int(cp * (p["e"] - p["s"]))
        eh = (cps - p["s"]) / 3600.0
        if eh < 1:
            continue
        o_ = obs(p["s"], cps)
        raw = bursty_raw(o_, eh, ac_p)
        if raw is None or not np.isfinite(raw):
            continue
        full_recs.append(100.0 * (raw - p["final"]) / p["final"])
full_bias_pct = float(np.mean(full_recs)) if full_recs else float("nan")
print(f"[INFO ONLY -- not used] full-panel (n={len(A)} 2-day auctions incl. target+future) Bursty mean bias "
      f"= {full_bias_pct:+.2f}% (compare to Sir's stated +3.17% -- sanity check on model fidelity only, "
      f"NOT fed into the live de-bias correction, which uses ONLY the {len(prior_panel)}-auction pre-April slice).")

# ---------------------------------------------------------------------------
# Fresh, unmodified re-run of the LOCKED baseline for direct comparison (per
# lesson_distrust_past_findings: recompute, don't trust the stated -$2,200 figure blind).
# ---------------------------------------------------------------------------
print("\n=== re-running single_auction_seesaw.py UNMODIFIED for a fresh LOCKED-baseline number ===")
base_env = dict(os.environ)
base_env["AUCTION"] = SLUG
for k in ("REACT6H", "PACE_EDGE", "LAST_H"):
    base_env.pop(k, None)
base_proc = subprocess.run([sys.executable, "-u", str(HERE / "single_auction_seesaw.py")],
                            capture_output=True, text=True, env=base_env, timeout=600)
print(base_proc.stdout[-1200:])
if base_proc.returncode != 0:
    print("WARNING: baseline subprocess non-zero exit:", base_proc.returncode, base_proc.stderr[-2000:])
m_pnl = re.search(r"TOTAL P&L \$([+-]?[\d,.]+)", base_proc.stdout)
baseline_pnl = float(m_pnl.group(1).replace(",", "")) if m_pnl else None
base_csv = HERE / "audit_out3" / "one_auction_trades.csv"
base_trades_df = pd.read_csv(base_csv) if base_csv.exists() else pd.DataFrame()
base_buy_brackets = (base_trades_df[base_trades_df.action == "BUY"]["bracket"].value_counts()
                     if len(base_trades_df) else pd.Series(dtype=int))

# ---------------------------------------------------------------------------
# Load L2 price ticks for the target auction (identical query to single_auction_seesaw.py)
# ---------------------------------------------------------------------------
def pmxt_files(s, e):
    out = []
    t = datetime.fromtimestamp(s, ET) - dt.timedelta(hours=1)
    end = datetime.fromtimestamp(e, ET) + dt.timedelta(hours=1)
    while t <= end:
        out += glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet")
        t = t + dt.timedelta(hours=1)
    return sorted(set(out))


con = duckdb.connect()
tok2lab = {str(v): k for k, v in tok.items()}
order = sorted(tok.keys(), key=lambda l: pbk(l)[0])
brng = {l: pbk(l) for l in order}
idxof = {l: i for i, l in enumerate(order)}
fs = pmxt_files(S0, E0)
arr = "[" + ",".join("'" + f.replace(os.sep, "/") + "'" for f in fs) + "]"
toklist = "(" + ",".join("'" + str(v) + "'" for v in tok.values()) + ")"
px = con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1 AND best_bid>0
    AND ts>={S0 * 1000} AND ts<{E0 * 1000} ORDER BY ts""").df()
px["lab"] = px.aid.map(tok2lab)
_have = set(px.lab.dropna().unique())
_missing = [l for l in order if l not in _have]
if _missing:
    print(f"WARNING: {len(_missing)}/{len(order)} bracket(s) have NO pmxt price data: {_missing}"
          + ("  <-- INCLUDES THE WINNER; results are INVALID" if WIN in _missing else ""))

tp = px.ts.to_numpy().astype("int64")
lab = px.lab.to_numpy()
ask = px.best_ask.to_numpy(float)
bid = px.best_bid.to_numpy(float)
tw = bfms[(bfms >= S0 * 1000) & (bfms < E0 * 1000)]
ts_all = np.concatenate([tw, tp])
typ = np.concatenate([np.ones(len(tw), np.int8), np.zeros(len(tp), np.int8)])
ip = np.concatenate([-np.ones(len(tw), int), np.arange(len(tp))])
o_srt = np.argsort(ts_all, kind="stable")
ts_all = ts_all[o_srt]
typ = typ[o_srt]
ip = ip[o_srt]

# ---------------------------------------------------------------------------
# SEESAW event loop -- identical mechanic to single_auction_seesaw.py, center swapped
# ---------------------------------------------------------------------------
s, e = S0, E0


def poly_pace(mid):
    if not mid:
        return ""
    num = sum(m * bmid(l) for l, m in mid.items())
    den = sum(mid.values())
    return round(num / den, 1) if den > 0 else ""


o = 0
bka = {l: 1.0 for l in order}
bkb = {l: 0.0 for l in order}
mid = {}
shares = {l: 0.0 for l in order}
cost = {l: 0.0 for l in order}
last_o = {l: -1 for l in order}
center = None
sd = None
fair = {}
realized = 0.0
trades = []
tweetlog = []
twn = 0
last_recomp = -10 ** 9

for k in range(len(ts_all)):
    t = int(ts_all[k])
    eh = (t / 1000.0 - s) / 3600.0
    rh = max(total - eh, 0.0)
    if typ[k] == 1:  # tweet
        o += 1
        twn += 1
        cprev = center
        if eh >= 0.5:
            raw = bursty_raw(o, eh, ac_target)
            center = (raw / (1.0 + b_of_eh(eh))) if raw is not None else None
            if center is not None:
                sd = calib_sigma(rh)
                fair = {l: bracket_fair(brng[l][0], brng[l][1], center, sd) for l in order}
            last_recomp = t
            cb = min(order, key=lambda x: abs((brng[x][0] + brng[x][1]) / 2 - center)) if center is not None else order[0]
            tweetlog.append({
                "tweet_no": twn, "et": datetime.fromtimestamp(t / 1000, ET).strftime("%m-%d %H:%M:%S"),
                "hrs_to_close": round(rh, 2), "count_so_far": o,
                "bursty_raw": round(raw, 1) if raw is not None else "",
                "center_debiased": round(center, 1) if center is not None else "",
                "per_post_move": round(center - cprev, 2) if (center is not None and cprev is not None) else "",
                "sigma": round(sd, 1) if sd is not None else "",
                **({f"fair_{l}": round(fair[l], 3) for l in order if abs(idxof[l] - idxof[cb]) <= 1} if center is not None else {}),
            })
        continue
    i = ip[k]
    l = lab[i]
    bka[l] = ask[i]
    bkb[l] = bid[i]
    mid[l] = (ask[i] + bid[i]) / 2.0
    if eh >= 0.5 and t - last_recomp >= 60000:
        raw = bursty_raw(o, eh, ac_target)
        center = (raw / (1.0 + b_of_eh(eh))) if raw is not None else None
        if center is not None:
            sd = calib_sigma(rh)
            fair = {l2: bracket_fair(brng[l2][0], brng[l2][1], center, sd) for l2 in order}
        last_recomp = t
    if center is None or eh < GATE_H or rh <= 0.05:
        continue
    if sd is None or sd > SIGMA_MAX:
        continue
    ci = None
    for j, ll in enumerate(order):
        lo, hi = brng[ll]
        if lo <= round(center) <= hi:
            ci = j
            break
    if ci is None:
        continue
    targets = [order[ci]] + ([order[ci + 1]] if ci + 1 < len(order) else []) + ([order[ci - 1]] if ci > 0 else [])
    if l not in targets or o <= last_o[l]:
        continue
    fp = fair.get(l)
    if fp is None:
        continue
    if bka[l] < fp - EDGE:
        sh = UNIT / bka[l]
        shares[l] += sh
        cost[l] += UNIT
        last_o[l] = o
        trades.append({"et": datetime.fromtimestamp(t / 1000, ET).strftime("%m-%d %H:%M:%S"), "hrs_to_close": round(rh, 2),
                       "action": "BUY", "bracket": l, "price": round(bka[l], 3), "our_fair": round(fp, 3),
                       "edge": round(fp - bka[l], 3), "center": round(center, 1), "cnt": o, "shares": round(sh, 1),
                       "ask": round(bka[l], 3), "bid": round(bkb[l], 3), "rpnl": 0.0, "poly_pace": poly_pace(mid)})
    elif bkb[l] > fp + EDGE and shares[l] > 1e-6:
        sh = min(UNIT / bkb[l], shares[l])
        proceeds = sh * bkb[l]
        frac = sh / shares[l]
        c = cost[l] * frac
        realized += proceeds - c
        shares[l] -= sh
        cost[l] -= c
        last_o[l] = o
        trades.append({"et": datetime.fromtimestamp(t / 1000, ET).strftime("%m-%d %H:%M:%S"), "hrs_to_close": round(rh, 2),
                       "action": "SELL", "bracket": l, "price": round(bkb[l], 3), "our_fair": round(fp, 3),
                       "edge": round(bkb[l] - fp, 3), "center": round(center, 1), "cnt": o, "shares": round(sh, 1),
                       "ask": round(bka[l], 3), "bid": round(bkb[l], 3), "rpnl": round(proceeds - c, 2), "poly_pace": poly_pace(mid)})

for l in order:  # RESOLUTION: book held/unsold positions at $1/$0
    if shares[l] > 1e-6:
        pay = 1.0 if pbk(l) == (wlo, whi) else 0.0
        trades.append({"et": datetime.fromtimestamp(e, ET).strftime("%m-%d %H:%M:%S"), "hrs_to_close": 0.0,
                       "action": "RESOLUTION", "bracket": l, "price": round(pay, 3), "our_fair": round(pay, 3),
                       "edge": 0.0, "center": round(center, 1) if center is not None else "", "cnt": o,
                       "shares": round(shares[l], 1), "ask": round(bka[l], 3), "bid": round(bkb[l], 3),
                       "rpnl": round(shares[l] * pay - cost[l], 2), "poly_pace": poly_pace(mid)})

settle = sum(shares[l] * (1.0 if pbk(l) == (wlo, whi) else 0.0) for l in order)
leftcost = sum(cost.values())
pnl = realized + settle - leftcost
T = pd.DataFrame(trades)
T.to_csv(OUTD / "april_debiased_bursty_trades.csv", index=False)
pd.DataFrame(tweetlog).to_csv(OUTD / "april_debiased_bursty_tweets.csv", index=False)
bdf.to_csv(OUTD / "debias_b_records.csv", index=False)

nb = int((T.action == "BUY").sum()) if len(T) else 0
nsl = int((T.action == "SELL").sum()) if len(T) else 0
my_buy_brackets = T[T.action == "BUY"]["bracket"].value_counts() if len(T) else pd.Series(dtype=int)

print("\n" + "=" * 78)
print("=== DE-BIASED BURSTY NOWCAST SEESAW -- ONE AUCTION (april-16 -> april-18) ===")
print("=" * 78)
print(f"tweets in window: {twn} | TOTAL TRADES: {len(T)}  ({nb} buys, {nsl} sells)")
print(f"realized ${realized:+.2f} | settle leftover ${settle - leftcost:+.2f} | TOTAL P&L ${pnl:+.2f}")
print(f"final live center estimate (last recompute before close): {round(center, 1) if center is not None else 'n/a'} "
      f"vs actual final {ACTUAL_FINAL}")
print(f"\nDE-BIASED BUY bracket breakdown:\n{my_buy_brackets.to_string()}")
print(f"\nBASELINE (LOCKED, fresh re-run) BUY bracket breakdown:\n{base_buy_brackets.to_string()}")
print(f"\nBASELINE (LOCKED, fresh re-run) TOTAL P&L: ${baseline_pnl:+.2f}" if baseline_pnl is not None else
      "\nBASELINE P&L: could not parse from subprocess stdout")
print(f"DE-BIASED BURSTY TOTAL P&L:                ${pnl:+.2f}")
if baseline_pnl is not None:
    print(f"DELTA (de-biased - baseline):              ${pnl - baseline_pnl:+.2f}")
print(f"\nWROTE {OUTD / 'april_debiased_bursty_trades.csv'} ({len(T)} rows), "
      f"{OUTD / 'april_debiased_bursty_tweets.csv'} ({len(tweetlog)} rows), "
      f"{OUTD / 'debias_b_records.csv'} ({len(bdf)} rows)")

# ---------------------------------------------------------------------------
# Write to a NEW tab (idempotent: clear+rewrite if it exists, create if not).
# New_Backtest_Clean_7.13.2026 is NEVER touched by this script.
# ---------------------------------------------------------------------------
SEE = "1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg"
NEWTAB = "April16-18 DeBiased Bursty"
HEADERS = ["Date", "Time", "Time-to-close", "Tweet count", "De-biased Bursty pace (center)",
          "Actual final (77)", "Poly Pace (market)", "Action", "Bracket", "PM Odds", "Our Odds",
          "Edge", "Kelly", "Shares", "Best ask", "Best bid", "Realized P&L", "Running P&L"]


def kelly_frac(action, price, fair_):
    if action == "BUY" and price < 1:
        return round(max(0.0, fair_ - price) / (1.0 - price), 3)
    if action == "SELL" and price > 0:
        return round(max(0.0, price - fair_) / price, 3)
    return ""


def split_date_time(et_str, year=2026):
    mmdd, hms = et_str.split(" ")
    mo, da = mmdd.split("-")
    return f"{year}-{mo}-{da}", hms


grid = []
running = 0.0
for tt in trades:
    date_s, time_s = split_date_time(tt["et"])
    running += tt["rpnl"]
    grid.append([
        date_s, time_s, tt["hrs_to_close"], tt["cnt"], tt["center"], ACTUAL_FINAL, tt["poly_pace"],
        tt["action"], tt["bracket"], tt["price"], tt["our_fair"], tt["edge"],
        kelly_frac(tt["action"], tt["price"], tt["our_fair"]), tt["shares"], tt["ask"], tt["bid"],
        tt["rpnl"], round(running, 2),
    ])

creds = service_account.Credentials.from_service_account_file(
    os.path.expanduser("~/.claude/google-service-account.json"),
    scopes=["https://www.googleapis.com/auth/spreadsheets"], subject="darwin@xagency.com")
sh = build("sheets", "v4", credentials=creds).spreadsheets()
meta = sh.get(spreadsheetId=SEE).execute()
titles = {x["properties"]["title"]: x["properties"]["sheetId"] for x in meta["sheets"]}
assert "New_Backtest_Clean_7.13.2026" in titles, "sanity check: existing tab list unexpectedly changed"
if NEWTAB not in titles:
    resp = sh.batchUpdate(spreadsheetId=SEE, body={"requests": [{"addSheet": {"properties": {"title": NEWTAB}}}]}).execute()
    gid_new = resp["replies"][0]["addSheet"]["properties"]["sheetId"]
    print(f"\ncreated new tab '{NEWTAB}' (sheetId={gid_new})")
else:
    gid_new = titles[NEWTAB]
    sh.values().clear(spreadsheetId=SEE, range=f"'{NEWTAB}'!A1:R20000").execute()
    print(f"\ntab '{NEWTAB}' already existed (sheetId={gid_new}) -- cleared A1:R20000 before rewrite (idempotent)")
sh.values().update(spreadsheetId=SEE, range=f"'{NEWTAB}'!A1", valueInputOption="RAW",
                   body={"values": [HEADERS] + grid}).execute()
sh.batchUpdate(spreadsheetId=SEE, body={"requests": [
    {"updateSheetProperties": {"properties": {"sheetId": gid_new, "gridProperties": {"frozenRowCount": 1}},
                               "fields": "gridProperties.frozenRowCount"}},
]}).execute()

# verify by re-reading
chk = sh.values().get(spreadsheetId=SEE, range=f"'{NEWTAB}'!A1:R{len(grid) + 1}",
                      valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
print(f"VERIFY: re-read '{NEWTAB}' -> {len(chk) - 1} data rows written (expected {len(grid)}), "
      f"headers match: {chk[0] == HEADERS if chk else False}")
assert len(chk) - 1 == len(grid), f"row count drift after write: {len(chk) - 1} != {len(grid)}"

# ---------------------------------------------------------------------------
# RUN_META
# ---------------------------------------------------------------------------
emit_run_meta(
    script=__file__,
    headline={
        "n_auctions": 1, "auction": SLUG, "actual_final": ACTUAL_FINAL,
        "debias_b_pct": round(b_const * 100, 2), "debias_b_ci_pct": [round(b_ci_lo, 2), round(b_ci_hi, 2)],
        "debias_method": "horizon-dependent" if USE_HORIZON else "single_constant",
        "n_prior_auctions_for_bias": int(n_prior_auctions_used), "n_checkpoints_for_bias": int(n_checkpoints_used),
        "final_live_center_estimate": round(center, 1) if center is not None else None,
        "debiased_pnl": round(pnl, 2), "n_trades": len(T), "n_buys": nb, "n_sells": nsl,
        "baseline_locked_pnl_freshrun": baseline_pnl,
        "pnl_delta_vs_baseline": round(pnl - baseline_pnl, 2) if baseline_pnl is not None else None,
    },
    data_paths=[str(HERE / "elon_backfill_2025-09_to_now.parquet"), str(CANON / "auctions" / "elonmusk"),
               str(PMX) + " (pmxt L2 archive)"],
    window_basis="noon-ET from slug (canonical, never trade-derived start/end); accrual windows daily noon-anchored",
    fills=("TAKER-CROSSING immediate fill at posted ask(buy)/bid(sell), full $20 notional per trade, "
           "NO depth cap, NO queue/rest-time, taker_fee=0 -- inherited UNCHANGED from "
           "single_auction_seesaw.py per task instruction to isolate the center-model swap only. "
           "NOT a maker-resting sim; absolute P&L is UNVERIFIED fill-realism (shared limitation with "
           "the prior -$2,200 LOCKED-baseline figure this run is compared against, freshly reproduced "
           "above as baseline_locked_pnl_freshrun)."),
    trial_count=1,
    scope="claims-pnl (single-auction, n=1)",
    notes=(f"De-biased Bursty Nowcast center replaces Ens+CAP1.5 in the seesaw engine for {SLUG} only, "
           f"everything else (EDGE=0.02, UNIT=$20, GATE_H=3h, per-tweet-per-bracket cap, coverage guard, "
           f"resolution settlement, calib_sigma+bracket_fair imported from locked_pace.py) held identical "
           f"to isolate the one variable. b={b_const * 100:+.2f}% (95% CI [{b_ci_lo:+.2f}%,{b_ci_hi:+.2f}%]) "
           f"fit WALK-FORWARD on {n_prior_auctions_used} 2-day auctions closing strictly before "
           f"2026-04-16 12:00 ET ({n_checkpoints_used} checkpoint records, CPS={CPS_BIAS}); live sim used "
           f"{'the horizon-dependent interp' if USE_HORIZON else 'the single constant'} -- see printed "
           f"DECISION line for why. Informational-only full-panel bias (all {len(A)} auctions, NOT used) "
           f"printed for comparison to the stated +3.17% figure. n=1 auction: anecdote about the de-bias "
           f"mechanism, not proof of a live edge -- the real test is full-panel walk-forward P&L. "
           f"UNAUDITED -- hand off to @backtest-auditor before trusting any number here."),
    out_dir="audit_out_debiased_bursty",
)

print(f"\nMODEL_VERSION (LOCKED sigma/fair, from locked_pace.py): {MODEL_VERSION}")
print(f"NEW TAB: '{NEWTAB}' in spreadsheet {SEE}")
print("\nNEXT STEP: this result must go to @backtest-auditor before any conclusion is trusted.")
