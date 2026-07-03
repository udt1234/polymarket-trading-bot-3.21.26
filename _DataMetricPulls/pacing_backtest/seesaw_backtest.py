"""Mechanical SEESAW (price mean-reversion) backtest across all 112 markets.
Rule: per tradeable bracket, anchor = causal EMA of its price; BUY when price dips
GAP below anchor, SELL when it reverts back to anchor. Long-only, one position at a
time, only while price in the tradeable zone [0.15,0.85]. Honest cost: report PnL at
several round-trip cost levels (the make-or-break variable). NO forecast model used,
the anchor is the price's own recent level (this is the operator's actual edge)."""
import sys, numpy as np, pandas as pd
from pathlib import Path
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
DL=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\_downloads'); DL.mkdir(exist_ok=True)

prc=pd.read_parquet(OUT/'clob_prices.parquet').sort_values(['auction_slug','bucket','t'])
print(f"price points: {len(prc):,}  series: {prc.groupby(['auction_slug','bucket']).ngroups}")

EMA_SPAN=60      # ~60-min anchor
GAP=0.04         # buy when price is 4c below anchor
ZONE=(0.12,0.88) # only trade an active/pacing bracket
COSTS=[0.0,0.01,0.02,0.03]

def run(series_price, cost):
    """returns list of round-trip pnls (per share, net of cost)."""
    p=series_price
    if len(p)<EMA_SPAN+5: return []
    ema=pd.Series(p).ewm(span=EMA_SPAN, adjust=False).mean().to_numpy()
    pnls=[]; pos=None
    for i in range(EMA_SPAN, len(p)):
        px=p[i]
        if not (ZONE[0]<px<ZONE[1]):
            if pos is not None:  # left the zone -> close
                pnls.append(px-pos-cost); pos=None
            continue
        if pos is None:
            if px < ema[i]-GAP: pos=px            # BUY the dip
        else:
            if px >= ema[i]: pnls.append(px-pos-cost); pos=None   # SELL on revert to anchor
    if pos is not None: pnls.append(p[-1]-pos-cost)   # force close at end
    return pnls

# run across all bracket-series, per cost level
grids={c:[] for c in COSTS}
per_auction={c:{} for c in COSTS}
for (slug,bk),g in prc.groupby(['auction_slug','bucket']):
    p=g['price'].to_numpy()
    for c in COSTS:
        pn=run(p,c)
        if pn:
            grids[c].extend(pn)
            per_auction[c].setdefault(slug,[]).extend(pn)

print("\n=== SEESAW backtest (price mean-reversion), by round-trip cost ===")
print(f"{'cost':>6}{'trades':>8}{'avg_pnl/trade':>14}{'win%':>7}{'total/share':>12}{'auctions_profitable':>20}")
for c in COSTS:
    a=np.array(grids[c])
    if not len(a): continue
    win=100*(a>0).mean()
    auc_pnl={s:sum(v) for s,v in per_auction[c].items()}
    prof=sum(1 for v in auc_pnl.values() if v>0); tot=len(auc_pnl)
    print(f"{c*100:>5.0f}c{len(a):>8}{a.mean()*100:>13.2f}c{win:>6.0f}%{a.sum()*100:>11.1f}c{f'{prof}/{tot} ({100*prof/tot:.0f}%)':>20}")

# equity curve + per-trade hist at cost=2c
C=0.02; a=np.array(grids[C])
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(13,4.5))
ax1.plot(np.cumsum(a)*100); ax1.set_title(f'Cumulative seesaw PnL per share (cost={int(C*100)}c/round-trip)\n{len(a)} trades across 112 markets')
ax1.set_xlabel('trade #'); ax1.set_ylabel('cumulative PnL (cents/share)'); ax1.grid(alpha=0.25); ax1.axhline(0,color='k',lw=0.6)
ax2.hist(a*100,bins=60,color='#1f77b4'); ax2.axvline(0,color='r',lw=1); ax2.set_title('Per-trade PnL distribution (cents/share)'); ax2.set_xlabel('cents'); ax2.grid(alpha=0.25)
fig.tight_layout(); fig.savefig(DL/'seesaw_backtest.png'); plt.close(fig)
print(f"\nsaved equity curve -> {DL/'seesaw_backtest.png'}")
print("NOTE: 1-min bars + fixed-cost model. Bid/ask bounce can flatter low-cost results;")
print("the honest read is the cost-sensitivity table above (where does it stay profitable?).")
