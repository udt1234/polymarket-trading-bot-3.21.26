"""SUB-MINUTE speed test (the one surviving edge candidate). Event study: how fast does the
market reprice after an Elon tweet, and is there an exploitable lag window? Forward = the outcome
being measured (no look-ahead; the tweet time is the real-time trigger). Obeys BACKTEST_RULES.md.
Data: tick-level best_bid/best_ask (price_change) + trades (last_trade_price) from the L2 repo
(recorder = Jun23-Jul2; extend across Apr13+ once the pmxt backfill completes)."""
import duckdb, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
f48=f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets-48h.parquet"
def q(s): return con.execute(s).df()

lo,hi=q(f"SELECT min(ts) a, max(ts) b FROM read_parquet('{f48}')").iloc[0]
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet")
tw=np.sort(bf[bf.counts_main_feed].ms.to_numpy().astype('int64'))
tw=tw[(tw>=lo)&(tw<hi)]
print(f"L2 window {pd.Timestamp(lo,unit='ms',tz='UTC'):%Y-%m-%d} -> {pd.Timestamp(hi,unit='ms',tz='UTC'):%Y-%m-%d} | {len(tw)} counting tweets inside")

HOR=[1,2,3,5,10,20,30,45,60]
def analyze(anchor_ts, E, TR):
    ts=E['ts'].to_numpy(); mid=E['mid'].to_numpy(); bb=E['best_bid'].to_numpy(); ba=E['best_ask'].to_numpy()
    trs=TR['ts'].to_numpy()
    out=[]
    for T in anchor_ts:
        i=np.searchsorted(ts,T,side='right')-1
        if i<1 or i>=len(ts)-1: continue
        mid0=mid[i]; bb0=bb[i]; ba0=ba[i]
        j=np.searchsorted(ts,T,side='right'); lat=np.nan; k=j
        while k<len(ts) and ts[k]-T<=60000:
            if bb[k]!=bb0 or ba[k]!=ba0: lat=(ts[k]-T)/1000.0; break
            k+=1
        curve={}
        for h in HOR:
            m=np.searchsorted(ts,T+h*1000,side='right')-1
            curve[h]=mid[m]-mid0 if m>=0 else np.nan
        tj=np.searchsorted(trs,T,side='right')
        trlag=(trs[tj]-T)/1000.0 if tj<len(trs) and trs[tj]-T<=60000 else np.nan
        out.append((lat,trlag,curve))
    return out

allres=[]; base=[]
slugs=q(f"SELECT DISTINCT slug FROM read_parquet('{f48}') WHERE outcome='YES'").slug.tolist()
for slug in slugs:
    ev=q(f"""SELECT asset_id, ts, best_bid, best_ask FROM read_parquet('{f48}')
        WHERE slug='{slug}' AND outcome='YES' AND event_type='price_change' AND best_bid IS NOT NULL AND best_ask IS NOT NULL ORDER BY ts""")
    if ev.empty: continue
    ev['mid']=(ev.best_bid+ev.best_ask)/2
    cand=ev.groupby('asset_id').agg(n=('mid','size'),md=('mid','median')).reset_index()
    cand=cand[(cand.md>0.12)&(cand.md<0.88)]
    if cand.empty: continue
    aid=cand.sort_values('n',ascending=False).asset_id.iloc[0]
    E=ev[ev.asset_id==aid].sort_values('ts').reset_index(drop=True)
    TR=q(f"""SELECT ts FROM read_parquet('{f48}') WHERE asset_id='{aid}' AND event_type='last_trade_price' ORDER BY ts""")
    lo2,hi2=E.ts.min(),E.ts.max()
    twin=tw[(tw>=lo2)&(tw<hi2)]
    if not len(twin): continue
    allres+=analyze(twin,E,TR)
    rng=np.random.default_rng(3); rt=np.sort(rng.integers(lo2,hi2,size=len(twin)).astype('int64'))
    base+=analyze(rt,E,TR)

def summ(res,label):
    if not res: print(f"\n{label}: no events"); return
    lats=np.array([r[0] for r in res],float); lats=lats[np.isfinite(lats)]
    trl=np.array([r[1] for r in res],float); trl=trl[np.isfinite(trl)]
    print(f"\n=== {label}  (n={len(res)} events) ===")
    if len(lats): print(f"  quote-move latency (sec to first book change): median {np.median(lats):.1f}  p25 {np.percentile(lats,25):.1f}  p75 {np.percentile(lats,75):.1f}  (moved within 60s: {len(lats)}/{len(res)})")
    if len(trl): print(f"  first-trade lag (sec, = adverse-selection window): median {np.median(trl):.1f}  p25 {np.percentile(trl,25):.1f}  (trade within 60s: {len(trl)}/{len(res)})")
    tot=np.nanmean([abs(r[2][60]) for r in res if np.isfinite(r[2][60])])
    print(f"  repricing curve (mean ABS mid move by horizon; total 60s move = {tot*100:.2f}c):")
    for h in HOR:
        v=np.nanmean([abs(r[2][h]) for r in res if np.isfinite(r[2][h])])
        print(f"    +{h:>2}s: {v*100:5.2f}c   ({100*v/tot if tot else 0:3.0f}% of the 60s move)")
summ(allres,"AFTER A COUNTING TWEET")
summ(base,"BASELINE (random times)")
