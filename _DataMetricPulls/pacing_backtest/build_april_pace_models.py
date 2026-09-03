# -*- coding: utf-8 -*-
"""7 walk-forward pacing models, computed PER ROW, for the Elon April 16-18 2026 2-day
auction ('elon-musk-of-tweets-april-16-april-18'). Writes projected-FINAL-count columns
S..Y onto New_Backtest_Clean_7.13.2026, surgically (S3:Y135 + S1:Y2 headers ONLY -- every
other column/row is untouched). This is an accuracy-diagnostic layer (pace model vs
truth), NOT a P&L backtest.

THE WALL (no look-ahead):
  - Every model's prior/curve is fit ONLY on 2-day auctions that CLOSED strictly before
    2026-04-16 12:00 ET (this auction's own start). April 16-18's own outcome (final=77)
    is read only to SCORE the report at the bottom, never as a model input.
  - Per-row inputs (count_so_far, elapsed_h, remaining_h) use ONLY tweets with
    ts <= that row's own timestamp (obs(S0, t_i), never obs(t_i, E0) or obs(S0, E0)).
  - gamma_poisson_projection's prior_mean/prior_std are NOT the hardcoded
    VALIDATED_PRIORS 2-day=(60,25) from fair_value.py -- that constant was calibrated
    2026-07-06 (git log), i.e. AFTER this auction, on a span that includes it. Using it
    here would be a global_fit leak. Instead we recompute the SAME prior walk-forward
    from the 45 2-day auctions that closed before this one (mean~100.3, std~37.6). We
    still import + call the real gamma_poisson_projection() math unchanged.

Models -> columns:
  S Simple/Linear        regular_pace()
  T Bayesian             bayesian_pace()            (blends S with walk-forward hist_mean)
  U DOW x Hourly         dow_hourly_bayesian_pace()  (walk-forward hour-of-day x weekday rates)
  V Gamma-Poisson        gamma_poisson_projection()  (walk-forward prior_mean/std, not the
                                                       post-hoc-fit hardcoded constant)
  W Empirical Nowcast    count_so_far / pf_median[h]        (walk-forward median accrual share)
  X Bursty Nowcast       count_so_far / pf_regime[h]        (heavy/normal/quiet conditioned,
                                                       classified vs walk-forward quartiles)
  Y Inhomog. Poisson     count_so_far + sum(remaining-hour lambda[hour,dow])  (additive, no
                                                       shrinkage -- distinct from U)
"""
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CANON = ROOT / "_DataMetricPulls" / "canonical"
ET = ZoneInfo("America/New_York")

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from api.modules.shared.pacing import bayesian_pace, dow_hourly_bayesian_pace, regular_pace  # noqa: E402
from api.modules.shared.fair_value import gamma_poisson_projection  # noqa: E402
from run_meta import emit_run_meta  # noqa: E402

SEE = "1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg"
TAB = "New_Backtest_Clean_7.13.2026"
ROW_FIRST, ROW_LAST = 3, 135  # inclusive, matches the live tab's single April 16-18 block
N_ROWS = ROW_LAST - ROW_FIRST + 1

MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
MONTH3 = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

TARGET_SLUG = "elon-musk-of-tweets-april-16-april-18"


def noon(slug: str):
    """Canonical slug -> noon-ET (start, end) unix seconds. NEVER trade-derived start/end."""
    tk = slug.replace("elon-musk-of-tweets-", "").split("-")
    mo1 = MONTHS[tk[0].lower()]
    d1 = int(tk[1])
    if len(tk) >= 4 and tk[2].lower() in MONTHS:
        mo2 = MONTHS[tk[2].lower()]
        d2 = int(tk[3])
    else:
        mo2 = mo1
        d2 = int(tk[2])
    s = int(pd.Timestamp(datetime(2026, mo1, d1, 12, tzinfo=ET)).timestamp())
    e = int(pd.Timestamp(datetime(2026, mo2, d2, 12, tzinfo=ET)).timestamp())
    return s, e


# ---------------------------------------------------------------------------
# Clean tweet source (the ONLY trustworthy tweet source)
# ---------------------------------------------------------------------------
bf = pd.read_parquet(HERE / "elon_backfill_2025-09_to_now.parquet")
bf = bf[bf.counts_main_feed].sort_values("ms")
pts = (bf["ms"].to_numpy() // 1000).astype("int64")  # unix seconds UTC, sorted


def obs(s: int, e: int) -> int:
    return int(np.searchsorted(pts, e) - np.searchsorted(pts, s))


S0, E0 = noon(TARGET_SLUG)
TOTAL_H = (E0 - S0) / 3600.0
ACTUAL_FINAL = obs(S0, E0)  # SCORING ONLY -- never fed into any model below
assert abs(TOTAL_H - 48.0) < 0.01, f"target window not 48h: {TOTAL_H}"
assert ACTUAL_FINAL == 77, f"actual final mismatch vs task spec: {ACTUAL_FINAL} != 77"

# ---------------------------------------------------------------------------
# Walk-forward prior auctions: 2-day auctions that CLOSED strictly before S0
# ---------------------------------------------------------------------------
auc = pd.concat(
    [pd.read_parquet(p) for p in sorted((CANON / "auctions" / "elonmusk").glob("*.parquet"))],
    ignore_index=True,
)
prior_windows = []
for _, a in auc[auc.duration_type == "2-day"].iterrows():
    try:
        s, e = noon(a.auction_slug)
    except (KeyError, ValueError):
        continue  # unparseable slug (e.g. 'arch-' prefixed) -- skip, never guess
    if e < S0:
        prior_windows.append((s, e))
prior_windows.sort()
N_PRIOR = len(prior_windows)
assert N_PRIOR >= 20, f"too few walk-forward prior 2-day auctions: {N_PRIOR}"

C = np.zeros((N_PRIOR, 48))       # cumulative raw count by hour h (1..48), per prior auction
FIN = np.zeros(N_PRIOR)           # final count of each prior auction
for i, (s, e) in enumerate(prior_windows):
    fin = obs(s, e)
    FIN[i] = fin
    for h in range(1, 49):
        C[i, h - 1] = obs(s, min(s + h * 3600, e))
PF = C / FIN[:, None]             # accrual share by hour h, per prior auction

pf_median = np.median(PF, axis=0)                       # W: regime-agnostic curve
q25 = np.percentile(C, 25, axis=0)                       # X: regime split boundaries
q75 = np.percentile(C, 75, axis=0)
pf_regime = {k: np.full(48, np.nan) for k in ("heavy", "normal", "quiet")}
for h in range(48):
    col_c, col_pf = C[:, h], PF[:, h]
    for k, mask in (("heavy", col_c >= q75[h]), ("quiet", col_c <= q25[h]),
                     ("normal", (col_c > q25[h]) & (col_c < q75[h]))):
        vals = col_pf[mask]
        if len(vals) >= 3:
            pf_regime[k][h] = np.median(vals)

HIST_MEAN_FINAL = float(FIN.mean())          # T, U prior (mean FINAL count, walk-forward)
WF_PRIOR_STD = float(FIN.std(ddof=1))         # V prior std (walk-forward, NOT the hardcoded 25.0)
print(f"walk-forward priors: n_prior_2day_auctions={N_PRIOR}  hist_mean_final={HIST_MEAN_FINAL:.1f}  "
      f"prior_std={WF_PRIOR_STD:.1f}  (recomputed walk-forward; NOT fair_value.VALIDATED_PRIORS "
      f"2-day=(60,25), which was fit 2026-07-06 on a span that includes this auction)")

# ---------------------------------------------------------------------------
# Walk-forward hour-of-day x day-of-week tweet rates (tweets before S0 only)
# ---------------------------------------------------------------------------
hist_pts = pts[pts < S0]
et_hist = pd.to_datetime(hist_pts, unit="s", utc=True).tz_convert(ET)
df_hist = pd.DataFrame({"date": et_hist.date, "hour": et_hist.hour, "dow": et_hist.dayofweek})
grid = (df_hist.groupby(["date", "hour"]).size().unstack(fill_value=0)
        .reindex(columns=range(24), fill_value=0))
HOURLY_AVG = grid.mean(axis=0).to_dict()  # hour(0-23) -> avg tweets in that ET hour per day

daily_tot = df_hist.groupby("date").size()
dow_of_date = {d: pd.Timestamp(d).dayofweek for d in daily_tot.index}
tmp = pd.DataFrame({"date": daily_tot.index, "total": daily_tot.values})
tmp["dow"] = tmp["date"].map(dow_of_date)
overall_daily_mean = float(tmp["total"].mean())
dow_mean = tmp.groupby("dow")["total"].mean()
dow_n = tmp.groupby("dow").size()
DOW_WEIGHTS = {
    d: (float(dow_mean[d]) / overall_daily_mean if d in dow_mean.index and dow_n.get(d, 0) >= 4
        and overall_daily_mean > 0 else 1.0)
    for d in range(7)
}
print(f"hourly/dow rates built from {len(daily_tot)} walk-forward days before {TARGET_SLUG} start")

# ---------------------------------------------------------------------------
# Read the live tab's row timestamps (col A Date, col B Time) + its recorded
# count-so-far (col F) as an ALIGNMENT GUARD -- abort before writing if mismatched.
# ---------------------------------------------------------------------------
creds = service_account.Credentials.from_service_account_file(
    os.path.expanduser("~/.claude/google-service-account.json"),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
    subject="darwin@xagency.com",
)
sh = build("sheets", "v4", credentials=creds).spreadsheets()

ab = sh.values().get(spreadsheetId=SEE, range=f"'{TAB}'!A{ROW_FIRST}:B{ROW_LAST}",
                     valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
f_col = sh.values().get(spreadsheetId=SEE, range=f"'{TAB}'!F{ROW_FIRST}:F{ROW_LAST}",
                        valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
assert len(ab) == N_ROWS, f"expected {N_ROWS} rows in A:B, got {len(ab)}"
f_col = [(r[0] if r else None) for r in f_col] + [None] * (N_ROWS - len(f_col))

import re  # noqa: E402
TIME_RE = re.compile(r"^(\d{1,2})(AM|PM)\s+(\d+)\s*mins?,\s*(\d+)\s*seconds?$")


def parse_row_ts(date_str: str, time_str: str) -> int:
    mo_abbr, day = date_str.split()
    mo = MONTH3[mo_abbr.lower()[:3]]
    m = TIME_RE.match(time_str.strip())
    if not m:
        raise ValueError(f"unparseable time: {time_str!r}")
    hh, ampm, mm, ss = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
    if ampm == "AM":
        hh24 = 0 if hh == 12 else hh
    else:
        hh24 = 12 if hh == 12 else hh + 12
    t = datetime(2026, mo, int(day), hh24, mm, ss, tzinfo=ET)
    return int(pd.Timestamp(t).timestamp())


rows = []
mismatches = 0
for i, (date_str, time_str) in enumerate(ab):
    t_i = parse_row_ts(date_str, time_str)
    if t_i < S0:  # market lists a few hours before noon-ET start (recorder starts early);
        t_i = S0  # clamp so elapsed_h is never negative -- never lets count_so_far peek forward
    if t_i > E0:
        t_i = E0
    count_so_far = obs(S0, t_i)  # THE WALL: bounded by this row's own timestamp only
    rec_f = f_col[i]
    if isinstance(rec_f, (int, float)) and int(rec_f) != count_so_far:
        mismatches += 1
    rows.append({"t": t_i, "count": count_so_far})

print(f"ALIGNMENT vs col F (tweet count so far): mismatches={mismatches}/{N_ROWS} (must be 0 to write)")
if mismatches:
    print("ABORT: row timestamp reconstruction does not match the live tab -- not writing.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Per-row model computation
# ---------------------------------------------------------------------------
def remaining_blocks(t_i: int):
    n = max(0, int((E0 - t_i) / 3600))
    if n == 0:
        return np.array([], dtype=int), np.array([], dtype=int)
    starts = t_i + np.arange(n) * 3600
    idx = pd.to_datetime(starts, unit="s", utc=True).tz_convert(ET)
    return idx.hour.to_numpy(), idx.dayofweek.to_numpy()


MIN_ELAPSED_H = 0.5
MIN_PF = 0.02
grid_out = []
for r in rows:
    t_i, count = r["t"], r["count"]
    elapsed_h = (t_i - S0) / 3600.0
    remaining_h = TOTAL_H - elapsed_h
    if elapsed_h < MIN_ELAPSED_H:
        grid_out.append([""] * 7)
        continue
    elapsed_fraction = elapsed_h / TOTAL_H
    hrs, dows = remaining_blocks(t_i)
    remaining_hours = [{"hour": int(h), "dow": int(d)} for h, d in zip(hrs, dows)]

    s_val = regular_pace(count, elapsed_h, TOTAL_H)
    t_val = bayesian_pace(count, elapsed_h, remaining_h, HIST_MEAN_FINAL, TOTAL_H)
    u_val = dow_hourly_bayesian_pace(count, remaining_hours, HOURLY_AVG, DOW_WEIGHTS,
                                     HIST_MEAN_FINAL, elapsed_h, remaining_h)
    v_val = gamma_poisson_projection(count, elapsed_fraction, HIST_MEAN_FINAL, WF_PRIOR_STD)

    hh = int(min(48, max(1, np.ceil(elapsed_h))))
    pfv_w = pf_median[hh - 1]
    w_val = (count / pfv_w) if pfv_w >= MIN_PF else ""

    if count >= q75[hh - 1]:
        regime = "heavy"
    elif count <= q25[hh - 1]:
        regime = "quiet"
    else:
        regime = "normal"
    pfv_x = pf_regime[regime][hh - 1]
    if not (pfv_x == pfv_x) or pfv_x < MIN_PF:  # NaN or too small -> fall back to regime-agnostic
        pfv_x = pfv_w
    x_val = (count / pfv_x) if pfv_x >= MIN_PF else ""

    y_add = float(sum(HOURLY_AVG[h] * DOW_WEIGHTS[d] for h, d in zip(hrs, dows)))
    y_val = count + y_add

    row_vals = [s_val, t_val, u_val, v_val, w_val, x_val, y_val]
    grid_out.append([round(v, 1) if isinstance(v, (int, float)) else v for v in row_vals])

n_populated = sum(1 for row in grid_out for v in row if v != "")
print(f"computed {len(grid_out)} rows x 7 models = {n_populated} populated cells "
      f"(blank only if elapsed_h<{MIN_ELAPSED_H}h or a pf-share guard tripped)")

# ---------------------------------------------------------------------------
# SURGICAL write: S1:Y2 headers + S3:Y135 values ONLY
# ---------------------------------------------------------------------------
HDR1 = [["Pace Model"] * 7]
HDR2 = [["Simple/Linear", "Bayesian", "DOW x Hourly", "Gamma-Poisson",
         "Empirical Nowcast", "Bursty Nowcast", "Inhomog. Poisson"]]

sh.values().batchUpdate(spreadsheetId=SEE, body={
    "valueInputOption": "RAW",
    "data": [
        {"range": f"'{TAB}'!S1", "values": HDR1},
        {"range": f"'{TAB}'!S2", "values": HDR2},
        {"range": f"'{TAB}'!S{ROW_FIRST}", "values": grid_out},
    ],
}).execute()

# ---------------------------------------------------------------------------
# Verify by re-reading
# ---------------------------------------------------------------------------
chk = sh.values().get(spreadsheetId=SEE, range=f"'{TAB}'!S2:Y{ROW_LAST}",
                      valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
n_written = sum(1 for row in chk[1:] if any(v != "" for v in (row + [""] * 7)[:7]))
print(f"\nVERIFY: re-read S2:Y{ROW_LAST} -> {len(chk) - 1} data rows, {n_written} with >=1 populated cell")
print("headers row2:", chk[0])
print("sample row3 :", chk[1] if len(chk) > 1 else None)
print("sample row69:", chk[67] if len(chk) > 67 else None)
print("sample last :", chk[-1] if chk else None)
assert len(chk) - 1 == N_ROWS, f"row count drift after write: {len(chk) - 1} != {N_ROWS}"

# ---------------------------------------------------------------------------
# Accuracy report: mean signed error + MAE per model vs ACTUAL_FINAL (77), n=133 rows
# ---------------------------------------------------------------------------
names = ["Simple/Linear", "Bayesian", "DOW x Hourly", "Gamma-Poisson",
         "Empirical Nowcast", "Bursty Nowcast", "Inhomog. Poisson"]
cols = list(zip(*grid_out))  # 7 tuples of 133 values each
print(f"\n{'model':>20} | {'n':>4} | {'mean signed err':>15} | {'MAE':>8}")
report = {}
for name, col in zip(names, cols):
    vals = [v for v in col if isinstance(v, (int, float))]
    if not vals:
        print(f"{name:>20} | {0:>4} | {'n/a':>15} | {'n/a':>8}")
        continue
    signed = [v - ACTUAL_FINAL for v in vals]
    mae = float(np.mean(np.abs(signed)))
    mse_signed = float(np.mean(signed))
    report[name] = {"n": len(vals), "mean_signed_err": round(mse_signed, 2), "mae": round(mae, 2)}
    print(f"{name:>20} | {len(vals):>4} | {mse_signed:>+15.2f} | {mae:>8.2f}")

best = min(report, key=lambda k: abs(report[k]["mean_signed_err"]))
print(f"\nleast overshoot (smallest |mean signed error|): {best} ({report[best]['mean_signed_err']:+.2f})")
best_mae = min(report, key=lambda k: report[k]["mae"])
print(f"lowest MAE (most accurate on average): {best_mae} (MAE={report[best_mae]['mae']:.2f})")

emit_run_meta(
    script=__file__,
    headline={"n_auctions": 1, "n_rows": N_ROWS, "actual_final": ACTUAL_FINAL,
              "per_model_mae": {k: v["mae"] for k, v in report.items()},
              "per_model_mean_signed_err": {k: v["mean_signed_err"] for k, v in report.items()}},
    data_paths=[str(HERE / "elon_backfill_2025-09_to_now.parquet"),
                str(CANON / "auctions" / "elonmusk")],
    window_basis="noon-ET from slug (elon-musk-of-tweets-april-16-april-18)",
    fills="N/A -- accuracy-diagnostic (forecast-vs-truth), not a P&L/fill sim",
    trial_count=1,
    scope="accuracy-diagnostic",
    notes=(f"7 pace models scored per-row (n={N_ROWS} rows, 1 auction) vs ACTUAL_FINAL=77. "
           f"Walk-forward priors from {N_PRIOR} 2-day auctions closing before target start. "
           f"gamma_poisson_projection prior_mean/std recomputed walk-forward "
           f"({HIST_MEAN_FINAL:.1f}/{WF_PRIOR_STD:.1f}), NOT fair_value.VALIDATED_PRIORS "
           f"2-day=(60,25) (that constant postdates this auction -- see script docstring)."),
)
