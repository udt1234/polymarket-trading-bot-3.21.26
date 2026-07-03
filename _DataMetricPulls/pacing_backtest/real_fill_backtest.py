"""REAL-FILL, KELLY-SIZED head-to-head on actual L2 order-book data (recorder, Jun23-Jul2).
Fixes the 3 critiques: (1) BUY at the real best_ASK, not the mid; (2) fill only what the real ASK
DEPTH allows; (3) size each bet by fractional Kelly off EV (fair - ask), not 1 flat share.
Strategies: hold_fav / scrape_sell / scrape_hold (existing) vs kalman_edge (NEW). $ bankroll 5394.
Winner self-resolved from the actual tweet count. Walk-forward Kalman priors. BACKTEST_RULES."""
import duckdb, sys, math, json
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
f48=f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets-48h.parquet"
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def q(x): return con.execute(x).df()
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1]); mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        yr=2026; y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(lo,hi,proj,sig):
    zl=(lo-0.5-proj)/sig; return max(1e-9,(1-ncdf(zl)) if hi>=10**8 else (ncdf((hi+0.5-proj)/sig)-ncdf(zl)))

slugs=[s for s in q(f"SELECT DISTINCT slug FROM read_parquet('{f48}') WHERE outcome='YES'").slug if noon(s)]
aucs=[]
for slug in slugs:
    s,e=noon(slug)
    if e>int(pts.max()) or s<int(pts.min()): continue
    a=obs(s,e)
    if a>0: aucs.append((slug,s,e,a))
aucs=sorted(aucs,key=lambda x:x[1])
print(f"2-day auctions with REAL L2 + resolved count: {len(aucs)}")
BANK=5394.0; KMULT=0.25; MAXBET=0.10
def kelly_stake(edge,ask):
    if edge<=0 or ask<=0 or ask>=1: return 0.0
    return min(max(0.0,edge/(1-ask))*KMULT,MAXBET)*BANK
book={s:{'pnl':0.0,'cap':0.0,'n':0,'wins':0} for s in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']}
def rec(st,stake,ask,won,depth):
    fill=min(stake,depth)
    if fill<1 or ask<=0: return
    sh=fill/ask; book[st]['pnl']+=sh*((1.0 if won else 0.0)-ask); book[st]['cap']+=fill; book[st]['n']+=1; book[st]['wins']+=1 if won else 0
priorrates=[]
for slug,s,e,actual in aucs:
    total=(e-s)/3600; winner=None
    brs=[(b,pbk(b)) for b in q(f"SELECT DISTINCT bucket FROM read_parquet('{f48}') WHERE slug='{slug}' AND outcome='YES'").bucket if pbk(b)]
    for b,(lo,hi) in brs:
        if lo<=actual<=hi: winner=b
    px=q(f"""SELECT bucket,(ts//3600000)*3600000 hr, arg_max(best_ask,ts) ask, arg_max(best_bid,ts) bid
        FROM read_parquet('{f48}') WHERE slug='{slug}' AND outcome='YES' AND event_type='price_change'
        AND best_ask IS NOT NULL AND best_ask>0 AND best_ask<1 GROUP BY 1,2""")
    if px.empty: continue
    bkd=q(f"SELECT bucket,data FROM read_parquet('{f48}') WHERE slug='{slug}' AND outcome='YES' AND event_type='book'")
    depth={}
    for b in px.bucket.unique():
        ds=[]
        for d in bkd[bkd.bucket==b].data:
            try: a2=json.loads(d)['asks'][:2]; ds.append(sum(float(x['price'])*float(x['size']) for x in a2))
            except: pass
        depth[b]=float(np.median(ds)) if ds else 30.0
    priors=list(priorrates)
    def kal(hh):
        o=obs(s,int(s+hh*3600)); rh=total-hh
        if not priors: r=o/max(hh,1)
        else:
            x=float(np.mean(priors));P=float(np.var(priors))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));r=x+K*(o/max(hh,1)-x)
        proj=o+r*rh; return proj,math.sqrt(max(proj-o,1))*1.5+4
    hrs=sorted(px.hr.unique()); grid=[]
    for hr in hrs:
        hh=(hr/1000-s)/3600
        if hh<0.05*total or hh>0.97*total: continue
        proj,sig=kal(hh); row={'hh':hh}
        for b,(lo,hi) in brs:
            r=px[(px.bucket==b)&(px.hr==hr)]
            row[b]=(float(r.ask.iloc[0]),float(r.bid.iloc[0]),bprob(lo,hi,proj,sig)) if len(r) else None
        grid.append(row)
    if len(grid)<5: continue
    mid=grid[len(grid)//2]
    mp={b:mid[b][2] for b,_ in brs if mid.get(b)}; tp=sum(mp.values()) or 1; mp={b:v/tp for b,v in mp.items()}
    pf={b:mid[b] for b in mp if mid.get(b)}
    if pf:
        fav=max(pf,key=lambda b:pf[b][0]); ask=pf[fav][0]; rec('hold_fav',kelly_stake(mp[fav]-ask,ask),ask,fav==winner,depth.get(fav,30))
    inplay=min(mp,key=lambda b:abs(mp[b]-0.5)) if mp else None
    if inplay:
        ser=[(r[inplay][0],r[inplay][1]) for r in grid if r.get(inplay)]
        asks=np.array([x[0] for x in ser]); bids=np.array([x[1] for x in ser]); ema=pd.Series((asks+bids)/2).ewm(span=6,adjust=False).mean().to_numpy()
        pos=None
        for i in range(len(asks)):
            m=(asks[i]+bids[i])/2
            if pos is None and 0.15<m<0.75 and m<ema[i]-0.04: pos=asks[i]
            elif pos is not None and (m>=ema[i]+0.04 or m<=pos-0.06):
                fill=min(0.02*BANK,depth.get(inplay,30)); sh=fill/pos
                book['scrape_sell']['pnl']+=sh*(bids[i]-pos); book['scrape_sell']['cap']+=fill; book['scrape_sell']['n']+=1; pos=None
    for b in mp:
        ser=[r[b][0] for r in grid if r.get(b)]
        if len(ser)<5 or not(0.05<np.median(ser)<0.9): continue
        arr=np.array(ser); rm=pd.Series(arr).rolling(5,min_periods=3).min().to_numpy()
        for i in range(3,len(arr)):
            if arr[i]<rm[i-1]-0.005 and 0.02<arr[i]<0.9:
                fill=min(0.02*BANK,depth.get(b,30)); sh=fill/arr[i]
                book['scrape_hold']['pnl']+=sh*((1.0 if b==winner else 0)-arr[i]); book['scrape_hold']['cap']+=fill; book['scrape_hold']['n']+=1; book['scrape_hold']['wins']+=1 if b==winner else 0
                break
    for b in [x for x in mp if mp[x]>=0.08]:
        for r in grid:
            if not r.get(b): continue
            ask=r[b][0]; fair=r[b][2]
            if 0.02<ask<fair-0.03 and fair>0.05:
                rec('kalman_edge',kelly_stake(fair-ask,ask),ask,b==winner,depth.get(b,30)); break
    priorrates.append(actual/total)

print(f"\n{'strategy':<14}{'positions':>10}{'$ deployed':>12}{'$ P&L':>10}{'ROI':>8}{'win%':>7}")
for st in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']:
    d=book[st]; roi=100*d['pnl']/d['cap'] if d['cap'] else 0; wr=100*d['wins']/d['n'] if d['n'] else 0
    print(f"{st:<14}{d['n']:>10}{d['cap']:>11.0f}${d['pnl']:>+9.0f}{roi:>+7.1f}%{wr:>6.0f}%")
print("  BUY at real best-ASK, capped by real book depth; fair-value bets Kelly-sized; scalp/blind = fixed 2%.")
print(f"  auctions={len(aucs)} (recorder window). SMALL sample; extends to Apr13+ as the pmxt backfill lands.")
