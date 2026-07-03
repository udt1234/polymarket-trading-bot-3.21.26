"""v5: SELF-RESOLVED (winner = actual tweet count in the noon window, not canonical) so we finally
include 7-day auctions. Sources: canonical 2-day (pmxt L2) + recorder 2-day & 7-day (recorder L2).
Sir's LOCKED 2-days-left gate: only enter in the final 48h (for 7-day this is the last 2 days;
2-day is the whole thing). Real best-ASK fills, real depth caps, Kelly-off-EV sizing, Brier throttle."""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
REC={'2-day':f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets-48h.parquet",'7-day':f"{ROOT}/_DataMetricPulls/recordings_pulled/elon-tweets.parquet"}
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
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(lo,hi,proj,sig):
    zl=(lo-0.5-proj)/sig; return max(1e-9,(1-ncdf(zl)) if hi>=10**8 else (ncdf((hi+0.5-proj)/sig)-ncdf(zl)))
lo_cov=int(pts.min()); hi_cov=int(pts.max())
# ---- build auction list ----
aucs={}  # slug -> dict
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
c2=auc[(auc.duration_type=='2-day')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
for _,a in c2.iterrows():
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w
    if not(1.5<=(e-s)/86400<=2.6) or e>hi_cov or s<lo_cov+7200: continue
    try: tm=json.loads(a.bracket_yes_token_ids)
    except: continue
    t2b={}
    for k,v in tm.items():
        ks,vs=str(k),str(v)
        if vs.isdigit() and len(vs)>18: t2b[vs]=ks
        elif ks.isdigit() and len(ks)>18: t2b[ks]=vs
    if len(t2b)>=3: aucs[a.auction_slug]={'slug':a.auction_slug,'s':s,'e':e,'dur':'2-day','src':'pmxt','tok2b':t2b}
for dur,rf in REC.items():
    for slug in q(f"SELECT DISTINCT slug FROM read_parquet('{rf}') WHERE outcome='YES'").slug:
        w=noon(slug,2026)
        if not w: continue
        s,e=w
        d=(e-s)/86400
        if dur=='2-day' and not 1.5<=d<=2.6: continue
        if dur=='7-day' and not 6.5<=d<=7.6: continue
        if e>hi_cov or obs(s,e)<=0: continue
        if slug not in aucs: aucs[slug]={'slug':slug,'s':s,'e':e,'dur':dur,'src':'recorder'}
auclist=sorted(aucs.values(),key=lambda x:x['s'])
print(f"auctions collected: {len(auclist)} ({sum(a['dur']=='2-day' for a in auclist)}x2d, {sum(a['dur']=='7-day' for a in auclist)}x7d)")
BANK=5394.0; KMULT=0.25; MAXBET=0.10
def kstake(edge,ask,mult): return (min(max(0.0,edge/(1-ask))*mult,MAXBET)*BANK) if (edge>0 and 0<ask<1) else 0.0
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
def get_px(a,gs):
    s,e=a['s'],a['e']
    if a['src']=='pmxt':
        files=l2files(gs,e)
        if len(files)<4: files=[REC['2-day']]
        toks="("+",".join("'"+t+"'" for t in a['tok2b'])+")"; arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"
        px=q(f"""SELECT asset_id,(ts//3600000)*3600000 hr, arg_max(best_ask,ts) ask, arg_max(best_bid,ts) bid
            FROM read_parquet({arr}) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={gs*1000} AND ts<{e*1000} GROUP BY 1,2""")
        if px.empty: return None,None
        px['bucket']=px.asset_id.map(a['tok2b'])
        bk=q(f"SELECT asset_id,data FROM read_parquet({arr}) WHERE asset_id IN {toks} AND event_type='book' AND ts>={gs*1000} AND ts<{e*1000}"); bk['bucket']=bk.asset_id.map(a['tok2b'])
    else:
        rf=REC[a['dur']]
        px=q(f"""SELECT bucket,(ts//3600000)*3600000 hr, arg_max(best_ask,ts) ask, arg_max(best_bid,ts) bid
            FROM read_parquet('{rf}') WHERE slug='{a['slug']}' AND outcome='YES' AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={gs*1000} AND ts<{e*1000} GROUP BY 1,2""")
        if px.empty: return None,None
        bk=q(f"SELECT bucket,data FROM read_parquet('{rf}') WHERE slug='{a['slug']}' AND outcome='YES' AND event_type='book' AND ts>={gs*1000} AND ts<{e*1000}")
    return px,bk
def run(gate):
    res=[]; priors=[]; mbr=[]; kbr=[]
    for a in auclist:
        s,e=a['s'],a['e']; total=(e-s)/3600; gs=max(s, e-48*3600) if gate else s
        px,bk=get_px(a,gs)
        if px is None: continue
        depth={}
        for b in px.bucket.unique():
            ds=[]
            for d in bk[bk.bucket==b].data.dropna():
                try: aa=json.loads(d)['asks'][:2]; ds.append(sum(float(x['price'])*float(x['size']) for x in aa))
                except: pass
            depth[b]=float(np.median(ds)) if ds else 30.0
        actual=obs(s,e); brs=[(b,pbk(b)) for b in px.bucket.unique() if pbk(b)]
        winner=next((b for b,(lo,hi) in brs if lo<=actual<=hi),None)
        if winner is None: continue
        prc=list(priors)
        def kal(hh):
            o=obs(s,int(s+hh*3600)); rh=total-hh
            if not prc: r=o/max(hh,1)
            else: x=float(np.mean(prc));P=float(np.var(prc))+.01;K=(P+.01)/(P+.01+max(.1,P*.5));r=x+K*(o/max(hh,1)-x)
            proj=o+r*rh; return proj,math.sqrt(max(proj-o,1))*1.5+4
        grid=[]
        for hr in sorted(px.hr.unique()):
            hh=(hr/1000-s)/3600; rh=total-hh
            if hh>0.985*total or rh<0.5: continue
            proj,sig=kal(hh); row={'hh':hh}
            for b,(lo,hi) in brs:
                r=px[(px.bucket==b)&(px.hr==hr)]
                row[b]=(float(r.ask.iloc[0]),float(r.bid.iloc[0]),bprob(lo,hi,proj,sig)) if len(r) else None
            grid.append(row)
        if len(grid)<3: continue
        mid=grid[len(grid)//2]; mp={b:mid[b][2] for b,_ in brs if mid.get(b)}; tp=sum(mp.values()) or 1; mp={b:v/tp for b,v in mp.items()}
        calib=1.0
        if len(mbr)>=4: mm=np.mean(mbr[-8:]);km=np.mean(kbr[-8:]);calib=float(np.clip((mm/km) if km>0 else 1.0,0.5,1.3))
        R={st:{'pnl':0.,'cap':0.} for st in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']}
        def buy(st,stake,ask,won,dep):
            fill=min(stake,dep)
            if fill<1 or ask<=0: return
            sh=fill/ask; R[st]['pnl']+=sh*((1.0 if won else 0)-ask); R[st]['cap']+=fill
        pf={b:mid[b] for b in mp if mid.get(b)}
        if pf:
            fav=max(pf,key=lambda b:pf[b][0]); ask=pf[fav][0]; buy('hold_fav',kstake(mp[fav]-ask,ask,KMULT),ask,fav==winner,depth.get(fav,30))
        inplay=min(mp,key=lambda b:abs(mp[b]-0.5)) if mp else None
        if inplay:
            ser=[(r[inplay][0],r[inplay][1]) for r in grid if r.get(inplay)]
            asks=np.array([x[0] for x in ser]); bids=np.array([x[1] for x in ser]); ema=pd.Series((asks+bids)/2).ewm(span=6,adjust=False).mean().to_numpy(); pos=None
            for i in range(len(asks)):
                m=(asks[i]+bids[i])/2
                if pos is None and 0.15<m<0.75 and m<ema[i]-0.04: pos=asks[i]
                elif pos is not None and (m>=ema[i]+0.04 or m<=pos-0.06):
                    fill=min(0.02*BANK,depth.get(inplay,30)); sh=fill/pos; R['scrape_sell']['pnl']+=sh*(bids[i]-pos); R['scrape_sell']['cap']+=fill; pos=None
        for b in mp:
            ser=[r[b][0] for r in grid if r.get(b)]
            if len(ser)<3 or not(0.05<np.median(ser)<0.9): continue
            arr2=np.array(ser); rm=pd.Series(arr2).rolling(4,min_periods=2).min().to_numpy()
            for i in range(2,len(arr2)):
                if arr2[i]<rm[i-1]-0.005 and 0.02<arr2[i]<0.9:
                    fill=min(0.02*BANK,depth.get(b,30)); sh=fill/arr2[i]; R['scrape_hold']['pnl']+=sh*((1.0 if b==winner else 0)-arr2[i]); R['scrape_hold']['cap']+=fill; break
        for b in [x for x in mp if mp[x]>=0.08]:
            for r in grid:
                if not r.get(b): continue
                ask=r[b][0]; fair=r[b][2]
                if 0.02<ask<fair-0.03 and fair>0.05: buy('kalman_edge',kstake(fair-ask,ask,KMULT*calib),ask,b==winner,depth.get(b,30)); break
        res.append({'dur':a['dur'],**R})
        mbr.append(sum((mp.get(b,0)-(1.0 if b==winner else 0))**2 for b,_ in brs))
        prm={b:mid[b][0] for b,_ in brs if mid.get(b)};ptot=sum(prm.values()) or 1
        kbr.append(sum((prm.get(b,0)/ptot-(1.0 if b==winner else 0))**2 for b,_ in brs)); priors.append(actual/total)
    return res
def report(rows,label):
    if not rows: print(f"  {label}: none"); return
    print(f"  {label} (n={len(rows)}):")
    for st in ['hold_fav','scrape_sell','scrape_hold','kalman_edge']:
        cap=sum(r[st]['cap'] for r in rows); pnl=sum(r[st]['pnl'] for r in rows)
        print(f"    {st:<13}{('$%.0f'%cap):>9}dep {('%+.0f'%pnl):>7}$ ROI {(100*pnl/cap if cap else 0):>+6.1f}%")
for gate,lab in [(True,"WITH 2-days-left gate (Sir's rule)"),(False,"WITHOUT gate")]:
    r=run(gate)
    print(f"\n############ {lab} ############")
    report(r,"ALL"); report([x for x in r if x['dur']=='2-day'],"2-day only"); report([x for x in r if x['dur']=='7-day'],"7-day only")
