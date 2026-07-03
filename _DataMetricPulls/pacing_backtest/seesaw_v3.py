"""SEESAW v3 — fix the EXIT to match the operator's actual fills (buy dip ~5c below the
anchor, SELL ON THE POP ~5c above the anchor, capturing the full swing, not half).
Stop-out if it keeps falling (cut falling knives). Pacing-bracket-selective. Cost sweep."""
import sys, numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
prc=pd.read_parquet(OUT/'clob_prices.parquet').sort_values(['auction_slug','bucket','t'])
EMA_SPAN=60; GAP=0.05; STOP=0.06; INPLAY=(0.25,0.75); COSTS=[0.0,0.01,0.02,0.03]

grids={c:[] for c in COSTS}; per_auc={c:{} for c in COSTS}
for slug,g in prc.groupby('auction_slug'):
    wide=g.pivot_table(index='t', columns='bucket', values='price', aggfunc='last').sort_index().ffill()
    if len(wide)<EMA_SPAN+5: continue
    dist=(wide-0.5).abs(); inplay=dist.idxmin(axis=1)
    emas={bk:wide[bk].ewm(span=EMA_SPAN,adjust=False).mean() for bk in wide.columns}
    idx=wide.index.to_numpy()
    for c in COSTS:
        pos=None; posbk=None; pnls=[]
        for k in range(EMA_SPAN,len(idx)):
            bk=inplay.iloc[k]; px=wide[bk].iloc[k]; an=emas[bk].iloc[k]
            if pos is not None:
                cpx=wide[posbk].iloc[k]; can=emas[posbk].iloc[k]
                # SELL ON THE POP (anchor+GAP), or stop-out, or bracket left the zone
                if cpx>=can+GAP or cpx<=pos-STOP or not(INPLAY[0]<cpx<INPLAY[1]):
                    pnls.append(cpx-pos-c); pos=None; posbk=None
            if pos is None and (INPLAY[0]<px<INPLAY[1]) and px<an-GAP:
                pos=px; posbk=bk
        if pos is not None: pnls.append(wide[posbk].iloc[-1]-pos-c)
        if pnls: grids[c].extend(pnls); per_auc[c].setdefault(slug,[]).extend(pnls)

print("=== SEESAW v3 (sell ON THE POP, stop falling knives, pacing-bracket only) ===")
print(f"{'cost':>6}{'trades':>8}{'avg/trade':>11}{'win%':>7}{'total/sh':>10}{'auctions_profitable':>20}")
for c in COSTS:
    a=np.array(grids[c])
    if not len(a): continue
    ap={s:sum(v) for s,v in per_auc[c].items()}; prof=sum(1 for v in ap.values() if v>0)
    print(f"{c*100:>5.0f}c{len(a):>8}{a.mean()*100:>10.2f}c{100*(a>0).mean():>6.0f}%{a.sum()*100:>9.1f}c{f'{prof}/{len(ap)} ({100*prof/len(ap):.0f}%)':>20}")
# avg win vs avg loss
a=np.array(grids[0.0])
print(f"\nat 0c: avg WIN={a[a>0].mean()*100:.1f}c (n={int((a>0).sum())}), avg LOSS={a[a<0].mean()*100:.1f}c (n={int((a<0).sum())})")
