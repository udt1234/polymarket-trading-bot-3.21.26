"""Real-L2 microstructure backtests on recorder data (validated == pmxt, ~Jun23-Jul2 2026;
extends as the pmxt backfill lands). Obeys BACKTEST_RULES.md.
  PART A: TRUE complete-set ARB using the best_ASK sum (cost to actually BUY one of each YES
          bracket). ask-sum < $1 = riskless. (Old arb_test used mid = optimistic upper bound.)
  PART B: TWEET overreaction — does the in-play bracket's mid react to a tweet and then revert?
          Measured at 1-min resolution on real book top-of-book (finally possible with L2)."""
import duckdb, sys, datetime as dt
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
f48=f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets-48h.parquet"
f7=f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets.parquet"
def q(s): return con.execute(s).df()

print("="*72); print("PART A  —  TRUE complete-set ARB (best-ASK sum, the real cost to buy the set)"); print("="*72)
for label,fp in [("2-day",f48),("7-day",f7)]:
    slugs=q(f"SELECT slug FROM read_parquet('{fp}') WHERE outcome='YES' GROUP BY 1 HAVING count(*)>2000").slug.tolist()
    rows=[]
    for slug in slugs:
        ev=q(f"""SELECT asset_id, ts, best_ask FROM read_parquet('{fp}')
            WHERE slug='{slug}' AND outcome='YES' AND event_type='price_change' AND best_ask IS NOT NULL AND best_ask>0 ORDER BY ts""")
        if ev.empty: continue
        brs=sorted(ev.asset_id.unique())
        if len(brs)<3: continue
        grid=pd.DataFrame({'ts':np.arange(ev.ts.min(),ev.ts.max(),60000).astype('int64')})
        wide=grid.copy()
        for aid in brs:
            sub=ev[ev.asset_id==aid][['ts','best_ask']].sort_values('ts')
            wide[aid]=pd.merge_asof(grid,sub,on='ts')['best_ask']
        full=wide.dropna()
        if full.empty: continue
        asum=full[brs].sum(axis=1)
        rows.append(dict(slug=slug[-22:], nbr=len(brs), mins=len(full),
            p99=100*(asum<0.99).mean(), p97=100*(asum<0.97).mean(), minsum=round(asum.min(),3), medsum=round(asum.median(),3)))
    R=pd.DataFrame(rows)
    print(f"\n{label}: {len(R)} auctions with full YES-bracket coverage")
    if len(R):
        print(f"  mean % of minutes ask-sum < $0.99 (>=1c arb): {R.p99.mean():.2f}%")
        print(f"  mean % of minutes ask-sum < $0.97 (>=3c arb): {R.p97.mean():.2f}%")
        print(f"  median complete-set ask-sum: ${R.medsum.median():.3f}   deepest: ${R.minsum.min():.3f}")
        print(R.sort_values('minsum').head(5).to_string(index=False))

print("\n"+"="*72); print("PART B  —  TWEET reaction + reversion (2-day, in-play bracket, real L2 mid)"); print("="*72)
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet")
tw=np.sort(bf[bf.counts_main_feed].ms.to_numpy().astype('int64'))
tweet_moves=[]; quiet_moves=[]; reverts=[]
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
    s=ev[ev.asset_id==aid][['ts','mid']].sort_values('ts')
    grid=pd.DataFrame({'ts':np.arange(s.ts.min(),s.ts.max(),60000).astype('int64')})
    grid['mid']=pd.merge_asof(grid,s,on='ts')['mid']; grid=grid.dropna().reset_index(drop=True)
    if len(grid)<30: continue
    twin=tw[(tw>=grid.ts.min())&(tw<grid.ts.max())]; twmins=set(twin//60000)
    grid['minb']=grid.ts//60000; grid['dmid']=grid.mid.diff().abs()
    grid['istweet']=grid.minb.isin(twmins)|(grid.minb-1).isin(twmins)
    tweet_moves+=grid.loc[grid.istweet,'dmid'].dropna().tolist()
    quiet_moves+=grid.loc[~grid.istweet,'dmid'].dropna().tolist()
    for i in range(1,len(grid)-10):
        d=grid.mid.iloc[i]-grid.mid.iloc[i-1]
        if abs(d)>=0.02 and grid.istweet.iloc[i]:
            reverts.append(-np.sign(d)*(grid.mid.iloc[i+10]-grid.mid.iloc[i])/abs(d))
print(f"avg |1-min mid move|  TWEET minutes: {np.mean(tweet_moves)*100:.2f}c  (n={len(tweet_moves)})")
print(f"avg |1-min mid move|  QUIET minutes: {np.mean(quiet_moves)*100:.2f}c  (n={len(quiet_moves)})")
print(f"reaction ratio (tweet/quiet): {np.mean(tweet_moves)/max(1e-9,np.mean(quiet_moves)):.2f}x  -> {'market REACTS to tweets' if np.mean(tweet_moves)>np.mean(quiet_moves) else 'no reaction'}")
rv=np.array(reverts); rv=rv[np.isfinite(rv)]
if len(rv):
    print(f"\nreversion after a >=2c tweet-driven move (over next 10 min; >0=reverts, <0=momentum):")
    print(f"  median {np.median(rv):.2f}  mean {np.mean(rv):.2f}  %reverting {100*np.mean(rv>0):.0f}%  (n={len(rv)})")
    print("  (>+0.30 median = a real fadeable overreaction edge; ~0 = efficient; <0 = momentum)")
