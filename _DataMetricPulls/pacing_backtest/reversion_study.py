"""§11 (your realized PnL + selective rule) + §10#2 reversion event-study + charts, from the
June 18-20 Elon full trade tape. Tests the brief's core hypothesis: do prices transiently
overshoot and mean-revert (fadeable net of cost)?"""
import sys, numpy as np, pandas as pd
from pathlib import Path
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
DL=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\_downloads'); DL.mkdir(exist_ok=True)
WALLET='0x2eEF3A18bC771827aF0649a81aA54148A8E8eAca'.lower()

df=pd.read_parquet(OUT/'june1820_tape.parquet').sort_values('timestamp').reset_index(drop=True)
df['yes_price']=np.where(df['outcome']=='Yes', df['price'], 1-df['price'])
df['dt']=pd.to_datetime(df['timestamp'],unit='s',utc=True)
tmin,tmax=df.timestamp.min(),df.timestamp.max()

# Elon counting tweets in window
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed]
tw=bf[(bf.ms//1000>=tmin)&(bf.ms//1000<=tmax)].copy(); tw['ts']=tw.ms//1000
tw_ts=np.sort(tw['ts'].to_numpy())
print(f"tape {len(df)} trades, {len(tw)} counting tweets in window")

# ---------- §11: your realized PnL (FIFO per bracket) ----------
mine=df[df['proxyWallet'].astype(str).str.lower()==WALLET].copy()
print(f"\n=== §11 YOUR realized round-trips (FIFO match per bracket) ===")
tot_real=0.0; tot_open_cost=0.0; open_pos={}
for bk,g in mine.groupby('_bracket_label'):
    lots=[]; realized=0.0
    for _,r in g.sort_values('timestamp').iterrows():
        p,s=r['yes_price'],r['size']
        if r['side']=='BUY': lots.append([p,s])
        else:
            rem=s
            while rem>1e-9 and lots:
                bp,bs=lots[0]; m=min(rem,bs); realized+=(p-bp)*m; rem-=m; bs-=m
                if bs<=1e-9: lots.pop(0)
                else: lots[0][1]=bs
    open_sz=sum(s for _,s in lots); open_cost=sum(p*s for p,s in lots)
    tot_real+=realized; tot_open_cost+=open_cost; open_pos[bk]=(open_sz,open_cost)
    print(f"  {bk:<8} realized=${realized:+8.2f}  open {open_sz:7.1f} sh @ ${(open_cost/open_sz if open_sz else 0):.3f} (cost ${open_cost:.0f})")
print(f"  TOTAL realized round-trip PnL: ${tot_real:+.2f}  (+ open positions valued at resolution)")

# ---------- per-bracket 1-min VWAP price series ----------
df['minute']=(df['timestamp']//60)*60
def vwap_series(bk):
    g=df[df._bracket_label==bk]
    v=g.groupby('minute').apply(lambda x:np.average(x['yes_price'],weights=x['size']) if x['size'].sum()>0 else x['yes_price'].mean())
    return v
brackets=['<40','40-64','65-89','90-114','115-139']
series={bk:vwap_series(bk) for bk in df._bracket_label.unique()}

# ---------- §10#2 reversion event-study ----------
THRESH=0.04; W=3  # shock = |Δ over 3 min| > 4c
def burst_after(t, win=900, k=3):  # >=k tweets within `win` sec after t
    return int(np.searchsorted(tw_ts,t+win)-np.searchsorted(tw_ts,t))>=k
def tweet_before(t, win=180):
    return int(np.searchsorted(tw_ts,t)-np.searchsorted(tw_ts,t-win))>=1
HOR=[2,5,10,15,30,60]
rows_all=[]; rows_tw=[]
for bk,s in series.items():
    s=s.sort_index(); idx=s.index.to_numpy(); val=s.to_numpy()
    pos={t:i for i,t in enumerate(idx)}
    for i in range(W,len(idx)):
        if idx[i]-idx[i-W] > 4*60: continue  # need contiguous-ish
        d=val[i]-val[i-W]
        if abs(d)<THRESH: continue
        t=idx[i]
        fwd={}
        for h in HOR:
            tgt=t+h*60; j=np.searchsorted(idx,tgt)
            if j>=len(idx): continue
            revfrac=-np.sign(d)*(val[j]-val[i])/abs(d)   # fraction of shock that reverted
            fwd[h]=revfrac
        if not fwd: continue
        tw_driven = tweet_before(t) and not burst_after(t)
        rows_all.append(fwd)
        if tw_driven: rows_tw.append(fwd)
def summarize(rows,label):
    print(f"\n=== reversion event-study: {label}  (n={len(rows)} shocks) ===")
    print(f"  {'horizon':>8} {'mean rev_frac':>14} {'median':>8}  (1.0=full revert, 0=stuck, <0=continued)")
    for h in HOR:
        v=[r[h] for r in rows if h in r]
        if v: print(f"  {h:>5}min {np.mean(v):>14.2f} {np.median(v):>8.2f}")
summarize(rows_all,"ALL shocks (>4c in 3min)")
summarize(rows_tw,"TWEET-driven, NO burst after (the brief's hypothesis)")
# cost proxy: typical 1-min bounce in quiet periods
allchg=np.concatenate([np.abs(np.diff(s.to_numpy())) for s in series.values() if len(s)>2])
print(f"\ncost proxy (median |1-min price change|, ~half-spread bounce): {np.median(allchg):.3f} = {np.median(allchg)*100:.1f}c")
print(f"   -> a fadeable edge needs reversion (in c) > ~2x this round-trip")

# ---------- charts ----------
plt.rcParams.update({'figure.dpi':110,'font.size':9})
# Chart 1: bracket price paths + your trades + tweet rug
fig,ax=plt.subplots(figsize=(13,5.5))
colors={'<40':'#1f77b4','40-64':'#d62728','65-89':'#2ca02c','90-114':'#9467bd','115-139':'#ff7f0e'}
for bk in brackets:
    s=series.get(bk)
    if s is None or not len(s): continue
    ax.plot(pd.to_datetime(s.index,unit='s',utc=True), s.values, label=bk, color=colors.get(bk), lw=1.1)
for _,r in mine.iterrows():
    ax.scatter(r['dt'], r['yes_price'], marker='^' if r['side']=='BUY' else 'v',
               color='lime' if r['side']=='BUY' else 'black', s=22, zorder=5, edgecolors='k', linewidths=0.3)
for t in tw_ts: ax.axvline(pd.to_datetime(t,unit='s',utc=True), color='gray', alpha=0.06, lw=0.5)
ax.set_title('June 18-20 Elon: bracket YES-price paths (VWAP/min) | ▲=your BUY ▼=your SELL | grey=tweets')
ax.set_ylabel('YES price (implied prob)'); ax.legend(loc='upper left',ncol=5,fontsize=8); ax.grid(alpha=0.2)
fig.tight_layout(); fig.savefig(DL/'rev_chart1_pricepaths.png'); plt.close(fig)

# Chart 2: reversion event-study curve (avg forward path after a +shock)
fig,ax=plt.subplots(figsize=(8,5))
for rows,lab,c in [(rows_all,'all shocks','#888'),(rows_tw,'tweet-driven, no burst','#d62728')]:
    if not rows: continue
    xs=HOR; ys=[np.mean([r[h] for r in rows if h in r]) for h in HOR]
    ax.plot(xs,ys,'-o',label=f'{lab} (n={len(rows)})',color=c)
ax.axhline(0,color='k',lw=0.6); ax.axhline(1,color='g',lw=0.6,ls='--',alpha=0.5)
ax.set_xlabel('minutes after shock'); ax.set_ylabel('fraction of shock reverted')
ax.set_title('Reversion event-study: does an overshoot snap back?\n(1.0=full revert, 0=stuck, <0=momentum/continued)')
ax.legend(); ax.grid(alpha=0.25); fig.tight_layout(); fig.savefig(DL/'rev_chart2_reversion.png'); plt.close(fig)

# Chart 3: complete-set sum (arb)
allmin=sorted(set().union(*[set(s.index) for s in series.values()]))
setsum=pd.DataFrame({bk:series[bk].reindex(allmin).ffill() for bk in series}).sum(axis=1)
fig,ax=plt.subplots(figsize=(13,3.5))
ax.plot(pd.to_datetime(setsum.index,unit='s',utc=True), setsum.values, lw=0.8, color='#1f77b4')
ax.axhline(1.0,color='r',lw=0.8,ls='--'); ax.set_ylim(0.85,1.25)
ax.set_title('Complete-set sum (Σ bracket YES mids). <$1.00 (red line) = arb window'); ax.grid(alpha=0.25)
fig.tight_layout(); fig.savefig(DL/'rev_chart3_arbsum.png'); plt.close(fig)
print(f"\nsaved 3 charts to {DL}")
print(f"  complete-set sum: min={setsum.min():.3f} max={setsum.max():.3f}, %time<1.0={100*(setsum<1.0).mean():.1f}%")
PY