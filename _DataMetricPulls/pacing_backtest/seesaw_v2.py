"""SEESAW v2 — SELECTIVE: only fade the PACING bracket (the in-play one nearest 50c),
only while it is genuinely range-bound (price in [0.30,0.70] and it IS the nearest-0.5
bracket). This is the operator's actual selectivity, not the every-bracket strawman.
Same price mean-reversion rule + honest cost sensitivity."""
import sys, numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
prc=pd.read_parquet(OUT/'clob_prices.parquet').sort_values(['auction_slug','bucket','t'])
EMA_SPAN=60; GAP=0.04; INPLAY=(0.30,0.70); COSTS=[0.0,0.01,0.02,0.03]

def parse_mid(lbl):
    l=str(lbl)
    try:
        if l.startswith('<'): return int(l[1:])/2
        if l.endswith('+'): return int(l[:-1])*1.2
        if '-' in l: a,b=l.split('-'); return (int(a)+int(b))/2
        return float(l)
    except: return np.nan

grids={c:[] for c in COSTS}; per_auc={c:{} for c in COSTS}
for slug,g in prc.groupby('auction_slug'):
    # common 1-min grid of all brackets' prices
    wide=g.pivot_table(index='t', columns='bucket', values='price', aggfunc='last').sort_index().ffill()
    if len(wide)<EMA_SPAN+5: continue
    # at each minute, in-play bracket = nearest 0.5 among present, in [0.30,0.70]
    dist=(wide-0.5).abs()
    inplay=dist.idxmin(axis=1)
    emas={bk:wide[bk].ewm(span=EMA_SPAN,adjust=False).mean() for bk in wide.columns}
    for c in COSTS:
        pos=None; posbk=None; pnls=[]
        idx=wide.index.to_numpy()
        for k in range(EMA_SPAN,len(idx)):
            t=idx[k]; bk=inplay.iloc[k]; px=wide[bk].iloc[k]; an=emas[bk].iloc[k]
            tradeable=(INPLAY[0]<px<INPLAY[1])
            if pos is not None:
                # exit if reverted to anchor, OR the held bracket is no longer in-play/tradeable
                cpx=wide[posbk].iloc[k]
                if cpx>=emas[posbk].iloc[k] or posbk!=bk or not (INPLAY[0]<cpx<INPLAY[1]):
                    pnls.append(cpx-pos-c); pos=None; posbk=None
            if pos is None and tradeable and px<an-GAP:
                pos=px; posbk=bk
        if pos is not None: pnls.append(wide[posbk].iloc[-1]-pos-c)
        if pnls:
            grids[c].extend(pnls); per_auc[c].setdefault(slug,[]).extend(pnls)

print("=== SEESAW v2 (SELECTIVE: pacing bracket only), by round-trip cost ===")
print(f"{'cost':>6}{'trades':>8}{'avg/trade':>11}{'win%':>7}{'total/sh':>10}{'auctions_profitable':>20}")
for c in COSTS:
    a=np.array(grids[c])
    if not len(a): continue
    ap={s:sum(v) for s,v in per_auc[c].items()}; prof=sum(1 for v in ap.values() if v>0)
    print(f"{c*100:>5.0f}c{len(a):>8}{a.mean()*100:>10.2f}c{100*(a>0).mean():>6.0f}%{a.sum()*100:>9.1f}c{f'{prof}/{len(ap)} ({100*prof/len(ap):.0f}%)':>20}")
print("\n(vs v1 every-bracket, which lost even at 0c. Selectivity = trade only the in-play ~50c bracket.)")
