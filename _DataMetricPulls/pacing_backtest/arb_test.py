"""Clean structural-arb test. Brackets are mutually exclusive + exhaustive, so a complete set
(one of each) pays exactly $1 at resolution. If the sum of all bracket prices < $1, buying the
set is riskless profit = $1 - sum. Only count minutes where EVERY bracket already has a real
price (after its first trade), so the sum is complete (fixes the earlier ffill artifact).
CAVEAT: clob_prices 'price' is a traded/mid price, not the ask. True buy-side arb needs the ASK
sum (higher) + L2 depth (size available), which we don't have. So this is the UPPER BOUND of the
opportunity; realizable arb is <= this."""
import sys, numpy as np, pandas as pd
from pathlib import Path
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; DL=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\_downloads')
prc=pd.read_parquet(OUT/'clob_prices.parquet').sort_values(['auction_slug','bucket','t'])

all_sums=[]; per_auc=[]; deepest=[]
for slug,g in prc.groupby('auction_slug'):
    wide=g.pivot_table(index='t', columns='bucket', values='price', aggfunc='last').sort_index().ffill()
    valid=wide.dropna(how='any')          # only minutes where EVERY bracket has a (last-known) price
    if len(valid)<30: continue
    setsum=valid.sum(axis=1).to_numpy()
    all_sums.append(setsum)
    n=len(setsum)
    per_auc.append(dict(slug=slug, n=n, median=float(np.median(setsum)), minsum=float(setsum.min()),
                        p_lt99=100*np.mean(setsum<0.99), p_lt97=100*np.mean(setsum<0.97), p_lt95=100*np.mean(setsum<0.95)))
    if setsum.min()<0.97: deepest.append((slug, float(setsum.min())))
S=np.concatenate(all_sums)
print(f"valid complete-set minutes across {len(per_auc)} auctions: {len(S):,}")
print("\n=== complete-set sum distribution (efficient market ~ $1.00) ===")
for p in [1,5,25,50,75,95,99]: print(f"  {p:>2}th pct: ${np.percentile(S,p):.3f}")
print(f"\n  % of minutes sum < $0.99 (>=1c arb): {100*np.mean(S<0.99):.2f}%")
print(f"  % of minutes sum < $0.97 (>=3c arb): {100*np.mean(S<0.97):.2f}%")
print(f"  % of minutes sum < $0.95 (>=5c arb): {100*np.mean(S<0.95):.3f}%")
print(f"  deepest single discount seen: ${S.min():.3f}  (= {100*(1-S.min()):.1f}c arb if instant)")
arb_minutes_3c=int(np.sum(S<0.97))
print(f"  total minutes with >=3c arb across ALL auctions/history: {arb_minutes_3c}")

# the gross capturable, IF you could buy at these prices for 1 share each, every such minute (very optimistic)
gross=float(np.sum(np.clip(1.0-S,0,None)[S<0.99]))
print(f"  hyper-optimistic gross (sum of all sub-$1 discounts, 1 share each minute): ${gross:.2f}")

pd.DataFrame(per_auc).to_csv(OUT/'arb_per_auction.csv', index=False)
print("\ntop 8 auctions by deepest discount:")
for slug,m in sorted(deepest,key=lambda x:x[1])[:8]:
    print(f"   {slug:<42} min complete-set sum = ${m:.3f}")

# chart: histogram of the complete-set sum
fig,ax=plt.subplots(figsize=(9,4.5))
ax.hist(S,bins=120,range=(0.7,1.3),color='#1f77b4')
ax.axvline(1.0,color='r',lw=1.2,ls='--',label='$1.00 (fair)')
ax.set_title('Complete-set sum across all 112 markets (valid minutes only)\nleft of red dashed = buy-side arb (sum < $1)')
ax.set_xlabel('sum of all bracket prices ($)'); ax.set_ylabel('minutes'); ax.legend(); ax.grid(alpha=0.2)
fig.tight_layout(); fig.savefig(DL/'arb_histogram.png'); plt.close(fig)
print(f"\nsaved {DL/'arb_histogram.png'}")
