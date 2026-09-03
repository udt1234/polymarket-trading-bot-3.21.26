# -*- coding: utf-8 -*-
"""PACING REPLAY for the Elon 2-day auction elon-musk-of-tweets-april-16-april-18 (noon ET Apr16 -> noon ET Apr18).
One row PER TWEET (counting + non-counting, flagged). Columns: Date | Time (ET) | Time to close | Count | Counts? |
then every pacing strategy's PROJECTED FINAL count at that tweet's moment, plus the live-dashboard Bayesian and the
settled Actual (reference). Walk-forward: every model's prior/params use ONLY 2-day auctions that closed BEFORE Apr 16.
Model math reused verbatim from calibration_test.py (Linear/Kalman/M4MMPP/CurBayes/M0), pacing_leaderboard.py
(Ens+CAP1.5), add_more_pace_models.py (sleep-adjusted effective hours), Brackets.js (_computePacing live Bayesian).
Set WRITE=True to push to the Google Sheet."""
import sys, os, glob, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
WRITE = ('--write' in sys.argv)
ROOT = "C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
PB = ROOT + "/_DataMetricPulls/pacing_backtest"; CANON = ROOT + "/_DataMetricPulls/canonical"; ET = ZoneInfo('America/New_York')
SLUG = "elon-musk-of-tweets-april-16-april-18"
SHEET = "1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg"; NEWTAB = "Pacing Replay Apr16-18"
MONTHS = {m.lower(): i for i, m in enumerate(['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'])}

# ---- tweet stream (ALL for rows) + counting subset ----
bf = pd.read_parquet(PB + "/elon_backfill_2025-09_to_now.parquet").sort_values('ms')
all_ms = (bf.ms.to_numpy() // 1000).astype('int64')
all_counts = bf.counts_main_feed.to_numpy().astype(bool)
cnt_ms = all_ms[all_counts]                       # only counting tweets
hd_all = pd.to_datetime(cnt_ms, unit='s', utc=True).tz_convert(ET).hour.to_numpy()
def obs(s, e): return int(np.searchsorted(cnt_ms, e) - np.searchsorted(cnt_ms, s))   # counting tweets in [s,e)

def noonET(slug, yr):
    tk = slug.replace('elon-musk-of-tweets-', '').split('-'); mo1 = MONTHS[tk[0].lower()]; d1 = int(tk[1])
    if len(tk) >= 4 and tk[2].lower() in MONTHS: mo2 = MONTHS[tk[2].lower()]; d2 = int(tk[3])
    else: mo2 = mo1; d2 = int(tk[2])
    y2 = yr + (1 if mo2 < mo1 else 0)
    return (int(pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET)).timestamp()), int(pd.Timestamp(datetime(y2, mo2, d2, 12, tzinfo=ET)).timestamp()))

S, E = noonET(SLUG, 2026); TOTAL_H = (E - S) / 3600.0
ACTUAL = obs(S, E)
print(f"window: {datetime.fromtimestamp(S, ET)} -> {datetime.fromtimestamp(E, ET)}  ({TOTAL_H:.0f}h)  ACTUAL settled count = {ACTUAL}")

# ---- diurnal (sleep) curve + effective hours, walk-forward (only tweets before S) ----
def diurnal_mult(before_s):
    h = hd_all[cnt_ms < before_s]
    if len(h) < 240: return np.ones(24)
    m = np.array([np.sum(h == hh) for hh in range(24)], float); return m / m.mean() if m.mean() > 0 else np.ones(24)
MULT = diurnal_mult(S)
def eff_hours(t0, t1):
    # fractional effective (sleep-weighted) hours: full hours + partial current hour,
    # so early rows never divide by ~0 (avoids the first-hour blow-up on the _S models).
    if t1 <= t0: return 0.0
    n = int((t1 - t0) // 3600); tot = 0.0
    if n > 0:
        hrs = pd.to_datetime(t0 + np.arange(n) * 3600, unit='s', utc=True).tz_convert(ET).hour.to_numpy(); tot += float(np.sum(MULT[hrs]))
    rem = (t1 - t0) - n * 3600
    if rem > 0:
        h = int(pd.Timestamp(t0 + n * 3600, unit='s', tz='UTC').tz_convert(ET).hour); tot += MULT[h] * (rem / 3600.0)
    return tot
EFF_TOTAL = eff_hours(S, E)

# ---- walk-forward priors from 2-day auctions that CLOSED before S ----
auc = pd.concat([pd.read_parquet(p) for p in glob.glob(CANON + "/auctions/elonmusk/*.parquet")], ignore_index=True)
allA = []
for _, a in auc.iterrows():
    if a.duration_type != '2-day': continue
    try: w = noonET(a.auction_slug, pd.to_datetime(a['start_utc'], utc=True).year)
    except Exception: continue
    if not 1.5 <= (w[1] - w[0]) / 86400 <= 2.6: continue
    if w[1] >= S: continue                                        # NO look-ahead: closed strictly before our start
    allA.append({'s': w[0], 'e': w[1], 'final': obs(w[0], w[1])})
allA = [a for a in allA if a['final'] > 0]
POOL = [a['final'] for a in allA]                                  # prior finals
PDUR = [(a['e'] - a['s']) / 3600 for a in allA]
PRATE = [a['final'] / ((a['e'] - a['s']) / 3600) for a in allA]    # prior clock rate
PEFF = [a['final'] / eff_hours(a['s'], a['e']) for a in allA if eff_hours(a['s'], a['e']) > 0]  # prior effective rate
print(f"priors: {len(allA)} prior 2-day auctions | mean final {np.mean(POOL):.1f} | mean rate {np.mean(PRATE):.2f}/h | mean eff-rate {np.mean(PEFF):.2f}/effh")

# ---- Polymarket market: per-bracket price time-series -> implied pace + odds ----
prc = pd.read_parquet(PB + "/clob_prices.parquet"); prc = prc[prc.auction_slug == SLUG]
PRICE_IDX = {}
for bk, g in prc.sort_values('t').groupby('bucket'):
    PRICE_IDX[bk] = (g['t'].to_numpy(), g['price'].to_numpy())
def _center(bk):
    if bk.startswith('<'): return (int(bk[1:]) - 1) / 2.0            # <40 -> 19.5
    if bk.endswith('+'): return int(bk[:-1]) + 20                    # 240+ -> ~260
    a, b = bk.split('-'); return (int(a) + int(b)) / 2.0
CENTERS = {bk: _center(bk) for bk in PRICE_IDX}
def price_at(bk, t):
    a = PRICE_IDX.get(bk)
    if a is None: return None
    ts, ps = a; i = np.searchsorted(ts, t, side='right') - 1
    if i < 0: return None
    v = float(ps[i]); return v if 0 <= v <= 1 else None
def market(t):
    px = {bk: price_at(bk, t) for bk in PRICE_IDX}; px = {bk: v for bk, v in px.items() if v is not None}
    tot = sum(px.values())
    if not px or tot <= 0: return None, None
    norm = {bk: v / tot for bk, v in px.items()}
    pace = sum(CENTERS[bk] * p for bk, p in norm.items())            # implied final count
    odds = 100.0 * norm.get('65-89', 0.0)                            # winner-bracket probability %
    return round(pace, 1), round(odds, 1)

# ---- MODELS (math verbatim from the canonical scripts) ----
def Linear(o, eh, rh): return 0.0 if eh <= 0 else o * (eh + rh) / eh
def M4MMPP(o, eh, rh, rates): return o * (eh + rh) / max(eh, 1) if not rates else o + (0.5 * (o / max(eh, 1)) + 0.5 * float(np.mean(rates))) * rh
def Kalman(o, eh, rh, rates):
    if not rates: return o * (eh + rh) / max(eh, 1)
    x = float(np.mean(rates)); P = float(np.var(rates)) + 0.01; R = max(0.1, P * 0.5); K = (P + 0.01) / (P + 0.01 + R)
    return o + (x + K * (o / max(eh, 1) - x)) * rh
def CurBayes(o, eh, rh, pool):
    th = eh + rh
    if not pool or o <= 0 or eh <= 0: return float(np.mean(pool)) if pool else 0.0
    ec = min(0.99, max(0.001, eh / th)); op = o / ec; pm = float(np.mean(pool))
    ps = max(1.0, float(np.std(pool, ddof=1)) if len(pool) > 1 else pm * 0.25); ov = max(1.0, o * (1 - ec) / (ec ** 2))
    return (pm / ps ** 2 + op / ov) / (1 / ps ** 2 + 1 / ov)
def M0(o, eh, rh, pt, pdur):
    if not pt: return o * (eh + rh) / max(eh, 1)
    return o + (sum(pt) + o) / (sum(pdur) + eh) * rh if (sum(pdur) + eh) > 0 else o
def M5NB(): return float(np.mean(POOL)) if POOL else 0.0            # historical average (widened, weakest)
# sleep-aware variants: base model over SLEEP-ADJUSTED (effective) hours
def kblend(obs_rate, priors):
    if not priors: return obs_rate
    x = float(np.mean(priors)); P = float(np.var(priors)) + 0.01; K = (P + 0.01) / (P + 0.01 + max(0.1, P * 0.5)); return x + K * (obs_rate - x)
def Linear_S(o, eeh, erh): return 0.0 if eeh <= 0 else o * (eeh + erh) / eeh
def M4MMPP_S(o, eeh, erh): return o + (0.5 * (o / max(eeh, 0.1)) + 0.5 * (np.mean(PEFF) if PEFF else 0)) * erh
def Kalman_S(o, eeh, erh): return o + kblend(o / max(eeh, 0.1), PEFF) * erh
# Ens+CAP1.5 (leaderboard project): time-weighted Kalman(early)+Accrual(late), burst rate capped at 1.5x baseline
def share_curve():
    noon0 = pd.Timestamp(datetime.fromtimestamp(int(cnt_ms.min()), ET).date(), tz=ET) + pd.Timedelta(hours=12); d = noon0; curves = []
    while d.timestamp() + 48 * 3600 <= S:
        ss = int(d.timestamp()); ee = ss + 48 * 3600; final = obs(ss, ee)
        if final >= 5: curves.append(np.array([obs(ss, ss + h * 3600) for h in range(1, 49)], float) / final)
        d = d + pd.Timedelta(days=1)
    return np.clip(np.median(np.vstack(curves), axis=0), 1e-3, 1.0) if curves else None
SHARE = share_curve()
RMEAN = float(np.mean(PRATE)) if PRATE else 40.0
Pk = np.var(PRATE) + .01; KK = (Pk + .01) / (Pk + .01 + max(.1, Pk * .5))
def EnsCap15(o, eh, rh, eeh, erh):
    kal = o + (RMEAN + KK * (o / max(eh, .1) - RMEAN)) * rh
    acc = o / SHARE[min(len(SHARE) - 1, max(0, int(eh) - 1))] if SHARE is not None else o * TOTAL_H / max(eh, .1)
    cp = eh / TOTAL_H; ens = (1 - cp) * kal + cp * acc
    r = (ens - o) / max(rh, .1); return o + min(r, 1.5 * RMEAN) * rh
# live-dashboard Bayesian (Brackets.js _computePacing, ported)
def LiveBayes(o, eh, rh):
    total = eh + rh; priorMean = float(np.mean(POOL)) if POOL else 0.0
    priorStd = max(1.0, float(np.std(POOL, ddof=1)) if len(POOL) > 1 else 1.0)
    ePct = min(1.0, eh / total) if total > 0 else 0.0
    if ePct < 0.05 or priorMean == 0: return priorMean
    op = o / ePct; obsVar = max(1.0, o * (1 - ePct) / max(0.05, ePct * ePct))
    pp = 1 / (priorStd * priorStd); po = 1 / obsVar; return (pp * priorMean + po * op) / (pp + po)

# ---- STRATEGY registry (name -> description) in display order ----
STRATS = [
    ("Linear",     "Straight line: current count / % of clock time elapsed. Extrapolates the raw pace to close."),
    ("Kalman",     "Prior avg rate blended with observed rate (Kalman gain), extrapolated over remaining clock hours."),
    ("M4MMPP",     "Half current pace + half historical pace, over remaining clock hours. A quiet-or-manic hedge."),
    ("Linear_S",   "Linear but over SLEEP-ADJUSTED hours (3-9am ET weighted ~0), so the dead-zone doesn't inflate it."),
    ("Kalman_S",   "Kalman blend over sleep-adjusted effective hours. Built to stop night-burst overshoot."),
    ("M4MMPP_S",   "M4MMPP over sleep-adjusted effective hours (half current eff-pace, half historical eff-pace)."),
    ("CurBayes",   "Bayesian blend: observed projection precision-weighted against the historical prior mean."),
    ("M0",         "Pooled prior: (sum of prior finals + current count) / (prior hours + elapsed) x remaining."),
    ("M5NB",       "Historical average final count (widened for wild weeks). Flat line, runs high, weakest."),
    ("Ens+CAP1.5", "LOCKED model: time-weighted Kalman(early)+Accrual(late), go-forward rate capped at 1.5x baseline."),
    ("LiveBayes",  "The live dashboard's pacing (Brackets.js): Linear projection Bayesian-blended with the prior, anchored on the prior for the first 5% of the window."),
]
# market + truth columns (computed per row, not count-projection strategies)
EXTRA = [
    ("Poly Pace",         "Polymarket implied final count = sum of each bracket's midpoint x its normalized price at that moment (what the crowd was pricing)."),
    ("Poly Odds (65-89)", "Polymarket implied probability (%) of the eventual-winning bracket 65-89, normalized across brackets - shows the crowd converging on the truth."),
    ("Actual",            "The count the auction actually settled at (truth, 77, same on every row) - for overshoot reference."),
]

def strat_values(o, eh, rh):
    eeh = eff_hours(S, S + int(eh * 3600)); erh = max(EFF_TOTAL - eeh, 0.0)
    return {
        "Linear": Linear(o, eh, rh), "Kalman": Kalman(o, eh, rh, PRATE), "M4MMPP": M4MMPP(o, eh, rh, PRATE),
        "Linear_S": Linear_S(o, eeh, erh), "Kalman_S": Kalman_S(o, eeh, erh), "M4MMPP_S": M4MMPP_S(o, eeh, erh),
        "CurBayes": CurBayes(o, eh, rh, POOL), "M0": M0(o, eh, rh, POOL, PDUR), "M5NB": M5NB(),
        "Ens+CAP1.5": EnsCap15(o, eh, rh, eeh, erh), "LiveBayes": LiveBayes(o, eh, rh), "Actual": float(ACTUAL),
    }

def fmt_dur(sec):
    sec = max(0, int(sec)); h = sec // 3600; m = (sec % 3600) // 60; return f"{h:02d}:{m:02d}"

# ---- build rows: every tweet in the window ----
mask = (all_ms >= S) & (all_ms < E)
win_ms = all_ms[mask]; win_cnt = all_counts[mask]
rows = []
running = 0
for tms, is_count in zip(win_ms, win_cnt):
    if is_count: running += 1                      # count includes this tweet if it counts
    o = running; eh = (tms - S) / 3600.0; rh = max(TOTAL_H - eh, 0.0)
    dt = datetime.fromtimestamp(int(tms), ET)
    sv = strat_values(o, eh, rh)
    ppace, podds = market(int(tms))
    row = [dt.strftime('%Y-%m-%d'), dt.strftime('%H:%M:%S'), fmt_dur(E - tms), o, ('yes' if is_count else 'no')]
    row += [round(sv[name], 1) for name, _ in STRATS]
    row += [ppace if ppace is not None else '', podds if podds is not None else '', float(ACTUAL)]
    rows.append(row)
print(f"rows: {len(rows)} tweets ({int(win_cnt.sum())} counting, {int((~win_cnt).sum())} non-counting)")
# preview
hdr_names = ['Date', 'Time (ET)', 'Time to Close', 'Count', 'Counts?'] + [n for n, _ in STRATS] + [n for n, _ in EXTRA]
print(' | '.join(hdr_names))
for r in rows[:3] + rows[-3:]:
    print(' | '.join(str(x) for x in r))

if not WRITE:
    print("\n(dry run — pass --write to push to the sheet)"); sys.exit(0)

# ---- MAE (each projection col vs the settled ACTUAL, over all tweets) ----
n = len(rows)
PROJ = list(range(5, 17))                              # Linear..Poly Pace (count projections)
def col_mae(ci):
    v = [abs(float(r[ci]) - ACTUAL) for r in rows if isinstance(r[ci], (int, float))]
    return round(sum(v) / len(v), 1) if v else ''
MAE = {ci: col_mae(ci) for ci in PROJ}
rank = sorted([ci for ci in PROJ if isinstance(MAE[ci], (int, float))], key=lambda ci: MAE[ci])
print("\nMAE vs actual (best tracker first):")
for ci in rank: print(f"  {hdr_names[ci]:>16}: {MAE[ci]}")

# ---- write to a NEW tab ----
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds = service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'), scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc = build('sheets', 'v4', credentials=creds).spreadsheets()
titles = [s['properties']['title'] for s in svc.get(spreadsheetId=SHEET).execute()['sheets']]
if NEWTAB in titles:
    dgid = [s['properties']['sheetId'] for s in svc.get(spreadsheetId=SHEET).execute()['sheets'] if s['properties']['title'] == NEWTAB][0]
    svc.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'deleteSheet': {'sheetId': dgid}}]}).execute()
resp = svc.batchUpdate(spreadsheetId=SHEET, body={'requests': [{'addSheet': {'properties': {'title': NEWTAB, 'gridProperties': {'frozenRowCount': 2, 'frozenColumnCount': 5}}}}]}).execute()
gid = resp['replies'][0]['addSheet']['properties']['sheetId']
row1 = hdr_names
row2 = ['', '', '', '', ''] + [d for _, d in STRATS] + [d for _, d in EXTRA]   # descriptions under each column
svc.values().update(spreadsheetId=SHEET, range=f"'{NEWTAB}'!A1", valueInputOption='RAW', body={'values': [row1, row2] + rows}).execute()
# summary MAE row (leave one blank row after data)
summ = ['MAE vs Actual (77)'] + [''] * 4 + [MAE[ci] for ci in PROJ] + ['', 0.0]
best_note = [f"Best tracker: {hdr_names[rank[0]]} (MAE {MAE[rank[0]]}) | worst: {hdr_names[rank[-1]]} (MAE {MAE[rank[-1]]})"]
svc.values().update(spreadsheetId=SHEET, range=f"'{NEWTAB}'!A{n + 4}", valueInputOption='RAW', body={'values': [summ, best_note]}).execute()

# ---- formatting: pace-band shading + Poly-Odds scale + summary emphasis ----
def gr(c0, c1, r0, r1): return {'sheetId': gid, 'startRowIndex': r0, 'endRowIndex': r1, 'startColumnIndex': c0, 'endColumnIndex': c1}
proj_cols = list(range(5, 17)) + [18]                  # count projections + Actual
data_ranges = [gr(c, c + 1, 2, 2 + n) for c in proj_cols]
BANDS = [  # continuous bracket bands, cool(low)->green(winner 65-89)->warm(overshoot)
    ('NUMBER_LESS', ['40'], {'red': 0.82, 'green': 0.89, 'blue': 0.96}),
    ('NUMBER_BETWEEN', ['40', '64.5'], {'red': 0.80, 'green': 0.93, 'blue': 0.90}),
    ('NUMBER_BETWEEN', ['64.5', '89.5'], {'red': 0.71, 'green': 0.90, 'blue': 0.74}),   # winner band 65-89
    ('NUMBER_BETWEEN', ['89.5', '114.5'], {'red': 0.99, 'green': 0.96, 'blue': 0.78}),
    ('NUMBER_BETWEEN', ['114.5', '139.5'], {'red': 0.99, 'green': 0.88, 'blue': 0.72}),
    ('NUMBER_GREATER', ['139.5'], {'red': 0.96, 'green': 0.78, 'blue': 0.78}),
]
reqs = []
for cond, vals, color in BANDS:
    reqs.append({'addConditionalFormatRule': {'index': 0, 'rule': {'ranges': data_ranges, 'booleanRule': {'condition': {'type': cond, 'values': [{'userEnteredValue': v} for v in vals]}, 'format': {'backgroundColor': color}}}}})
reqs.append({'addConditionalFormatRule': {'index': 0, 'rule': {'ranges': [gr(17, 18, 2, 2 + n)], 'gradientRule': {'minpoint': {'color': {'red': 1, 'green': 1, 'blue': 1}, 'type': 'NUMBER', 'value': '0'}, 'maxpoint': {'color': {'red': 0.55, 'green': 0.82, 'blue': 0.58}, 'type': 'NUMBER', 'value': '100'}}}}})
reqs.append({'repeatCell': {'range': gr(5, 19, 2, 2 + n), 'cell': {'userEnteredFormat': {'numberFormat': {'type': 'NUMBER', 'pattern': '0.0'}}}, 'fields': 'userEnteredFormat.numberFormat'}})
# summary row bold + highlight best MAE cell
sr = n + 3
reqs.append({'repeatCell': {'range': gr(0, 19, sr, sr + 1), 'cell': {'userEnteredFormat': {'textFormat': {'bold': True}}}, 'fields': 'userEnteredFormat.textFormat'}})
reqs.append({'repeatCell': {'range': gr(rank[0], rank[0] + 1, sr, sr + 1), 'cell': {'userEnteredFormat': {'backgroundColor': {'red': 0.71, 'green': 0.90, 'blue': 0.74}}}, 'fields': 'userEnteredFormat.backgroundColor'}})
# header row bold + wrap descriptions
reqs.append({'repeatCell': {'range': gr(0, 19, 0, 1), 'cell': {'userEnteredFormat': {'textFormat': {'bold': True}, 'horizontalAlignment': 'CENTER'}}, 'fields': 'userEnteredFormat(textFormat,horizontalAlignment)'}})
reqs.append({'repeatCell': {'range': gr(5, 19, 1, 2), 'cell': {'userEnteredFormat': {'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP', 'textFormat': {'fontSize': 8, 'italic': True}}}, 'fields': 'userEnteredFormat(wrapStrategy,verticalAlignment,textFormat)'}})
svc.batchUpdate(spreadsheetId=SHEET, body={'requests': reqs}).execute()
print(f"\nDONE. Wrote {n} rows + MAE summary + band shading to '{NEWTAB}'. https://docs.google.com/spreadsheets/d/{SHEET}/edit")
