"""REAL-FILL, KELLY-SIZED head-to-head AT SCALE. Canonical Elon 2-day auctions, real L2 pulled
from the full history (pmxt Apr13-Jun22 + recorder Jun23+), matched by YES token id. Buy at the
real best-ASK, fill only what the real book DEPTH allows, size by fractional Kelly off EV.
Strategies: hold_fav / scrape_sell / scrape_hold vs kalman_edge (NEW). BACKTEST_RULES."""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
REC48=f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets-48h.parquet"
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def q(x): return con.execute(x).df()
npmxt=len(glob.glob(f"{PMXT}/pmxt_tweets_*.parquet")); print(f"pmxt hour-files available: {npmxt}")
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1]); mo2=MONTHS[tk[2].lower()];d2=int(tk[3]); y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(lo,hi,proj,sig):
    zl=(lo-0.5-proj)/sig; return max(1e-9,(1-ncdf(zl)) if hi>=10**8 else (ncdf((hi+0.5-proj)/sig)-ncdf(zl)))
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
cand=auc[(auc.duration_type=='2-day')&(auc.winning_bucket!='')&(auc.confidence.isin(['high','medium']))&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
def l2files(s,e):
    fs=[]; h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0); endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    if len(fs)<5 and os.path.exists(REC48): fs=[REC48]
    return fs
BANK=5394.0; KMULT=0.25; MAXBET=0.10
def kstake(edge,ask): return (min(max(0.0,edge/(1-ask))*KMULT,MAXBET)*BANK) if (edge>0 and 0<ask<1) else 0.0
book={s:{'pnl':0.,'cap':0.,'n':0,'wins':0} for s in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']}
def rec(st,stake,ask,won,depth):
    fill=min(stake,depth)
    if fill<1 or ask<=0: return
    sh=fill/ask; book[st]['pnl']+=sh*((1.0 if won else 0.0)-ask); book[st]['cap']+=fill; book[st]['n']+=1; book[st]['wins']+=1 if won else 0
priors=[]; used=0
for _,a in cand.sort_values('start_utc').iterrows():
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w; total=(e-s)/3600
    if not (1.5<=(e-s)/86400<=2.6): continue
    try: tm=json.loads(a.bracket_yes_token_ids)
    except: continue
    tok2b={}
    for k,v in tm.items():
        ks,vs=str(k),str(v)
        if vs.isdigit() and len(vs)>18: tok2b[vs]=ks
        elif ks.isdigit() and len(ks)>18: tok2b[ks]=vs
    if len(tok2b)<3: continue
    files=l2files(s,e)
    if not files: continue
    toks="("+",".join("'"+t+"'" for t in tok2b)+")"; arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"
    try:
        px=q(f"""SELECT asset_id,(ts//3600000)*3600000 hr, arg_max(best_ask,ts) ask, arg_max(best_bid,ts) bid
            FROM read_parquet({arr}) WHERE asset_id IN {toks} AND event_type='price_change'
            AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
    except Exception:
        continue
    if px.empty: continue
    px['bucket']=px.asset_id.map(tok2b)
    bkd=q(f"SELECT asset_id,data FROM read_parquet({arr}) WHERE asset_id IN {toks} AND event_type='book' AND ts>={s*1000} AND ts<{e*1000}")
    bkd['bucket']=bkd.asset_id.map(tok2b)
    depth={}
    for b in px.bucket.unique():
        ds=[]
        for d in bkd[bkd.bucket==b].data.dropna():
            try: aa=json.loads(d)['asks'][:2]; ds.append(sum(float(x['price'])*float(x['size']) for x in aa))
            except: pass
        depth[b]=float(np.median(ds)) if ds else 30.0
    winner=str(a.winning_bucket); brs=[(b,pbk(b)) for b in px.bucket.unique() if pbk(b)]
    prc=list(priors)
    def kal(hh):
        o=obs(s,int(s+hh*3600)); rh=total-hh
        if not prc: r=o/max(hh,1)
        else: x=float(np.mean(prc));P=float(np.var(prc))+.01;K=(P+.01)/(P+.01+max(.1,P*.5));r=x+K*(o/max(hh,1)-x)
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
    used+=1
    mid=grid[len(grid)//2]; mp={b:mid[b][2] for b,_ in brs if mid.get(b)}; tp=sum(mp.values()) or 1; mp={b:v/tp for b,v in mp.items()}
    pf={b:mid[b] for b in mp if mid.get(b)}
    if pf:
        fav=max(pf,key=lambda b:pf[b][0]); ask=pf[fav][0]; rec('hold_fav',kstake(mp[fav]-ask,ask),ask,fav==winner,depth.get(fav,30))
    inplay=min(mp,key=lambda b:abs(mp[b]-0.5)) if mp else None
    if inplay:
        ser=[(r[inplay][0],r[inplay][1]) for r in grid if r.get(inplay)]
        asks=np.array([x[0] for x in ser]); bids=np.array([x[1] for x in ser]); ema=pd.Series((asks+bids)/2).ewm(span=6,adjust=False).mean().to_numpy(); pos=None
        for i in range(len(asks)):
            m=(asks[i]+bids[i])/2
            if pos is None and 0.15<m<0.75 and m<ema[i]-0.04: pos=asks[i]
            elif pos is not None and (m>=ema[i]+0.04 or m<=pos-0.06):
                fill=min(0.02*BANK,depth.get(inplay,30)); sh=fill/pos
                book['scrape_sell']['pnl']+=sh*(bids[i]-pos); book['scrape_sell']['cap']+=fill; book['scrape_sell']['n']+=1; pos=None
    for b in mp:
        ser=[r[b][0] for r in grid if r.get(b)]
        if len(ser)<5 or not(0.05<np.median(ser)<0.9): continue
        arr2=np.array(ser); rm=pd.Series(arr2).rolling(5,min_periods=3).min().to_numpy()
        for i in range(3,len(arr2)):
            if arr2[i]<rm[i-1]-0.005 and 0.02<arr2[i]<0.9:
                fill=min(0.02*BANK,depth.get(b,30)); sh=fill/arr2[i]
                book['scrape_hold']['pnl']+=sh*((1.0 if b==winner else 0)-arr2[i]); book['scrape_hold']['cap']+=fill; book['scrape_hold']['n']+=1; book['scrape_hold']['wins']+=1 if b==winner else 0; break
    for b in [x for x in mp if mp[x]>=0.08]:
        for r in grid:
            if not r.get(b): continue
            ask=r[b][0]; fair=r[b][2]
            if 0.02<ask<fair-0.03 and fair>0.05:
                rec('kalman_edge',kstake(fair-ask,ask),ask,b==winner,depth.get(b,30)); break
    priors.append(obs(s,e)/total)
print(f"\nauctions used (real L2): {used}")
print(f"{'strategy':<14}{'positions':>10}{'$ deployed':>12}{'$ P&L':>10}{'ROI':>8}{'win%':>7}")
for st in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']:
    d=book[st]; roi=100*d['pnl']/d['cap'] if d['cap'] else 0; wr=100*d['wins']/d['n'] if d['n'] else 0
    print(f"{st:<14}{d['n']:>10}{d['cap']:>11.0f}${d['pnl']:>+9.0f}{roi:>+7.1f}%{wr:>6.0f}%")
print("  BUY at real best-ASK, capped by real book depth; fair-value bets Kelly-sized; scalp/blind = fixed 2%.")
