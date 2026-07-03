"""Re-score the 10 pacing models as the NEW bot's worth-calculator.

The convergence bot trades on bracket WORTH = P(final count lands in bracket).
So we judge each model by the quality of its bracket distribution and by the
profit a value-trade on its worth would have made against REAL historical prices.

Per model x checkpoint (T-2d, T-1d) we report:
  - bracket_hit%   : point prediction lands in the winning bracket
  - argmax_hit%    : model's most-likely bracket IS the winner
  - logloss        : -log P(winning bracket)         (lower better, proper score)
  - brier          : sum_b (P_b - 1{win})^2          (lower better, proper score)
  - P_winner       : mean probability placed on the winning bracket
  - conv_PnL/auc   : buy every bracket where worth-price > 5c, hold to resolution,
                     avg $ PnL per auction (real bracket close prices)
  - conv_winrate   : of those value-buys, % that resolved YES
  - n_trades       : value-buys flagged across all auctions
A 'Market' baseline scores the crowd's own prices as the distribution.

Distribution wrap: final ~ Normal(pred, sigma), sigma = walk-forward std of the
model's own past errors (Poisson sqrt(pred) fallback for early auctions). Brackets
are renormalised to sum to 1. Walk-forward => no look-ahead.
"""
import sys, math
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls')
CANON = ROOT/'canonical'
OUT = ROOT/'pacing_backtest'
GAP = 0.05  # convergence value gap: buy when worth exceeds price by 5c

MODELS = ['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M4MMPP','M5NB','Kalman']

# ---------- load ----------
posts = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'posts/elonmusk').glob('*.parquet'))], ignore_index=True)
posts['ts_utc'] = pd.to_datetime(posts['ts_utc'], utc=True)
counted = posts[posts['counts_for_auction'] == True].sort_values('ts_utc')
post_ts = (counted['ts_utc'].astype('int64')//10**9).to_numpy()

auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
pri = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'prices/elonmusk').glob('*.parquet'))], ignore_index=True)
pri['hour_secs'] = (pd.to_datetime(pri['hour_utc'], utc=True).astype('int64')//10**9)

res = pd.read_csv(OUT/'backtest_full_results.csv')
res['start_dt'] = pd.to_datetime(res['start_utc'], utc=True)
res = res.sort_values('start_dt').reset_index(drop=True)  # chronological for walk-forward sigma

# bracket set + winner per auction (use prices as authoritative enumeration)
buckets_by_slug = pri.groupby('auction_slug')['bucket'].apply(lambda s: sorted(set(s.dropna()))).to_dict()
winner_by_slug = auc.set_index('auction_slug')['winning_bucket'].to_dict()
# price lookup: (slug,bucket) -> (hour_secs sorted, close sorted)
price_idx = {}
for (slug, bucket), g in pri.sort_values('hour_secs').groupby(['auction_slug','bucket']):
    price_idx[(slug, bucket)] = (g['hour_secs'].to_numpy(), g['close'].to_numpy())

def observed_at(start_secs, cp_secs):
    return int(np.searchsorted(post_ts, cp_secs) - np.searchsorted(post_ts, start_secs))

def parse_bucket(lbl):
    lbl = str(lbl).strip()
    try:
        if lbl.startswith('<'):  return (0, int(lbl[1:]) - 1)
        if lbl.endswith('+'):    return (int(lbl[:-1]), None)
        if '-' in lbl:
            a, b = lbl.split('-'); return (int(a), int(b))
        return (int(lbl), int(lbl))
    except Exception:
        return None

def ncdf(z): return 0.5 * (1 + math.erf(z / math.sqrt(2)))

def bracket_prob(pred, sigma, lo, hi):
    sigma = max(sigma, 1.0)
    z_lo = (lo - 0.5 - pred) / sigma
    if hi is None: return max(0.0, 1.0 - ncdf(z_lo))
    return max(0.0, ncdf((hi + 0.5 - pred) / sigma) - ncdf(z_lo))

def price_at(slug, bucket, cp_secs):
    arr = price_idx.get((slug, bucket))
    if arr is None: return None
    hs, cl = arr
    i = np.searchsorted(hs, cp_secs, side='right') - 1
    if i < 0: return None
    v = float(cl[i])
    if not (0.0 < v < 1.0): return None
    return v

# ---------- per-checkpoint scoring ----------
records = []
for cp, hr in [('T2d', 48), ('T1d', 24)]:
    # walk-forward sigma state: per model running list of signed errors (actual-pred)
    err_hist = {m: [] for m in MODELS}
    for _, r in res.iterrows():
        pred_col = f'{{}}_{cp}'.format
        if pd.isna(r.get(f'Linear_{cp}', np.nan)) or r.get(f'Linear_{cp}', '') == '':
            continue  # checkpoint not scored for this auction (e.g. 2-day has no T2d)
        slug = r['auction_slug']; actual = float(r['actual'])
        winner = winner_by_slug.get(slug); blabels = buckets_by_slug.get(slug)
        if not blabels or winner is None: continue
        if winner not in blabels: blabels = sorted(set(blabels) | {winner})
        branges = [(b, parse_bucket(b)) for b in blabels]
        branges = [(b, rg) for b, rg in branges if rg]
        start_secs = int(r['start_dt'].timestamp())
        total_h = float(r['total_hours']); elapsed_h = total_h - hr
        cp_secs = start_secs + int(elapsed_h * 3600)
        observed = observed_at(start_secs, cp_secs)

        # market baseline distribution (normalised prices)
        mkt_raw = {b: price_at(slug, b, cp_secs) for b, _ in branges}
        mkt_avail = {b: v for b, v in mkt_raw.items() if v is not None}

        for m in MODELS + ['Market']:
            if m == 'Market':
                if len(mkt_avail) < 2: continue
                worth = dict(mkt_avail); pred = None
            else:
                pred = float(r[f'{m}_{cp}'])
                eh = err_hist[m]
                sigma = float(np.std(eh)) if len(eh) >= 5 else math.sqrt(max(pred, 1.0))
                worth = {b: bracket_prob(pred, sigma, lo, hi) for b, (lo, hi) in branges}
            tot = sum(worth.values())
            if tot <= 0: continue
            worth = {b: v / tot for b, v in worth.items()}  # renormalise to sum 1
            p_win = worth.get(winner, 0.0)

            # forecasting metrics
            argmax_b = max(worth, key=worth.get)
            logloss = -math.log(max(p_win, 1e-6))
            brier = sum((worth[b] - (1.0 if b == winner else 0.0))**2 for b in worth)
            # point bracket-hit (model only)
            if m == 'Market':
                phit = (argmax_b == winner)
            else:
                rgw = parse_bucket(winner)
                phit = bool(rgw and rgw[0] <= pred <= (rgw[1] if rgw[1] is not None else 1e9))

            # convergence value-trade vs real prices (skip Market)
            conv_pnl = 0.0; conv_n = 0; conv_wins = 0
            if m != 'Market':
                for b, _ in branges:
                    pr = mkt_raw.get(b)
                    if pr is None: continue
                    if worth.get(b, 0.0) - pr > GAP:
                        conv_n += 1
                        won = 1.0 if b == winner else 0.0
                        conv_pnl += (won - pr)   # buy-and-hold-to-resolution PnL
                        conv_wins += int(won)

            records.append(dict(checkpoint=cp, model=m, p_win=p_win, logloss=logloss,
                                brier=brier, phit=int(phit), argmax_hit=int(argmax_b == winner),
                                conv_pnl=conv_pnl, conv_n=conv_n, conv_wins=conv_wins))
            if m != 'Market':
                err_hist[m].append(actual - pred)

rec = pd.DataFrame(records)

# ---------- aggregate grid ----------
grid_rows = []
for cp in ['T2d', 'T1d']:
    for m in MODELS + ['Market']:
        s = rec[(rec.checkpoint == cp) & (rec.model == m)]
        if not len(s): continue
        n = len(s)
        ntr = int(s.conv_n.sum())
        grid_rows.append({
            'checkpoint': 'T-2d' if cp == 'T2d' else 'T-1d',
            'model': m,
            'n_auctions': n,
            'bracket_hit%': round(100 * s.phit.mean(), 1),
            'argmax_hit%': round(100 * s.argmax_hit.mean(), 1),
            'logloss': round(s.logloss.mean(), 3),
            'brier': round(s.brier.mean(), 3),
            'P_winner': round(s.p_win.mean(), 3),
            'conv_PnL/auction': round(s.conv_pnl.mean(), 3) if m != 'Market' else '',
            'conv_winrate%': round(100 * s.conv_wins.sum() / ntr, 1) if (m != 'Market' and ntr) else '',
            'conv_trades': ntr if m != 'Market' else '',
        })
grid = pd.DataFrame(grid_rows)
grid.to_csv(OUT/'bracket_score_grid.csv', index=False)

# ---------- print ----------
for cp in ['T-1d', 'T-2d']:
    g = grid[grid.checkpoint == cp].copy()
    g = g.sort_values('logloss')
    print(f'\n================= {cp}  (worth-calculator scoring) =================')
    print(g.drop(columns=['checkpoint']).to_string(index=False))
print(f'\nWrote grid to {OUT/"bracket_score_grid.csv"}')
