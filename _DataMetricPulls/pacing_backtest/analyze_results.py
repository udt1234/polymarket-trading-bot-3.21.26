import sys, pandas as pd, numpy as np
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
OUT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot\_DataMetricPulls\pacing_backtest')
df = pd.read_csv(OUT/'backtest_full_results.csv')
models = ['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M4MMPP','M5NB','Kalman']

for cp in ['T1d','T2d']:
    errcols = {m: f'{m}_{cp}_err%' for m in models}
    sub = df[[c for c in errcols.values() if c in df.columns]].apply(pd.to_numeric, errors='coerce')
    sub = sub.dropna(how='any')
    print(f'\n===== {cp}  (n={len(sub)} auctions with all models scored) =====')
    # win = lowest abs err this auction
    wins = sub.idxmin(axis=1).value_counts()
    rows = []
    for m in models:
        c = errcols[m]
        if c not in sub.columns: continue
        v = sub[c]
        nwin = int((sub.idxmin(axis=1) == c).sum())
        rows.append((m, v.mean(), v.median(), nwin, 100*nwin/len(sub)))
    rows.sort(key=lambda r: r[2])  # sort by median
    print(f"{'Model':<10}{'mean%':>9}{'median%':>10}{'wins':>6}{'win%':>7}")
    for m, mean, med, nwin, winpct in rows:
        print(f"{m:<10}{mean:>9.1f}{med:>10.1f}{nwin:>6}{winpct:>6.0f}%")

# Head-to-head: best simple model vs deployed CurBayes at T-1d
print('\n===== M4MMPP / Kalman vs deployed CurBayes (T-1d) =====')
s = df[['actual','M4MMPP_T1d_err%','Kalman_T1d_err%','CurBayes_T1d_err%','Linear_T1d_err%']].apply(pd.to_numeric, errors='coerce').dropna()
for m in ['M4MMPP_T1d_err%','Kalman_T1d_err%','Linear_T1d_err%']:
    better = int((s[m] < s['CurBayes_T1d_err%']).sum())
    print(f'{m:<22} beats CurBayes in {better}/{len(s)} auctions ({100*better/len(s):.0f}%)')
