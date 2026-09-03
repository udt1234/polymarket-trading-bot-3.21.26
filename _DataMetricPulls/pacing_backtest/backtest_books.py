# -*- coding: utf-8 -*-
"""Backtest the THREE books (S1 Pace-Scalp / S2 Basket-Hold / S3 Anchor+Harvest) on real L2,
OFFICIAL Gamma winners, TRUE MAKER conservative fills. Per-trade decision log so every order
traces to a rule + the data that triggered it. Spec: ELON_EDGE_STRATEGY.md + 'Strategy Walkthrough'.

MAKER FILL MODEL (conservative, no taking):
  BUY  : we rest a bid at the best bid. It fills in hour h ONLY if the hour's LOW ask reached down
         to our bid (lo_ask <= bid) - a seller actually crossed to us. Fill price = bid. We never
         lift the ask. Signal to place the bid: (fair - bid) >= MARGIN (bid is >=3c below fair).
  SELL : we rest an ask above fair. It fills in hour h ONLY if the hour's HIGH bid crossed up to
         fair+MARGIN (a buyer reached our offer). Fill price = fair+MARGIN minus a HAIRCUT (slippage).
  If the price never crosses to our resting order, NO FILL (we miss it - realistic maker behaviour).
  Fills are capped by real book depth. Adverse selection is captured by holding fills to the OFFICIAL
  resolution outcome.

RULES (each has a conformance test in test_conformance.py):
  R1 winner ONLY from canonical official Gamma resolution (confidence high/med), never self-count.
  R2 every fill is MAKER: BUY fill_price == the rested bid (<= that hour's ask); SELL only when hi_bid crosses up.
  R3 S2 NEVER sells (zero SELL orders); holds to resolution.
  R4 S2 buys ONLY band brackets (fair>=BAND_FLOOR) and ONLY below fair ((fair-bid)>=MARGIN).
  R5 S1 enters ONLY below fair ((fair-bid)>=MARGIN) and exits ONLY above fair (hi_bid>=fair+MARGIN) or a stop.
  R6 S3 never sells a CORE lot (core is held; all S3 SELLs are sleeve).
  R7 no look-ahead: decisions at hour h use only hour-h book + walk-forward pace/priors.
  R8 conservative: SELL exits pay a HAIRCUT and every fill is capped by real depth.
"""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out2"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

BANK=5394.0; KMULT=0.25; MAXBET=0.10
BAND_FLOOR=0.05; MARGIN=0.03; STOP=0.06; HAIRCUT=0.01; SLEEVE=0.30; SCALP_STAKE=0.02*BANK

bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def q(x): return con.execute(x).df()
lo_cov=int(pts.min()); hi_cov=int(pts.max())
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

auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
L2START=int(datetime(2026,4,13,19,tzinfo=timezone.utc).timestamp())
aucs=[]
for _,a in auc.iterrows():
    dur=a.duration_type
    if dur not in ('2-day','7-day'): continue
    if str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w; d=(e-s)/86400
    if dur=='2-day' and not 1.5<=d<=2.6: continue
    if dur=='7-day' and not 6.5<=d<=7.6: continue
    if e>hi_cov or e<L2START: continue
    try: tm=json.loads(a.bracket_yes_token_ids)
    except: continue
    t2b={}
    for lbl,tok in tm.items():
        if isinstance(tok,str) and tok.isdigit() and len(tok)>18 and pbk(lbl): t2b[tok]=lbl
    if len(t2b)<3: continue
    win=str(a.winning_bucket).strip()
    if not pbk(win): continue
    aucs.append({'slug':a.auction_slug,'s':s,'e':e,'dur':dur,'tok2b':t2b,'winner':win})
aucs=sorted(aucs,key=lambda x:x['s'])
print(f"auctions with OFFICIAL winner + tokens + L2 window: {len(aucs)} ({sum(x['dur']=='2-day' for x in aucs)}x2d, {sum(x['dur']=='7-day' for x in aucs)}x7d)")

def l2files(gs,e):
    fs=[];h=datetime.fromtimestamp(gs,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
def load_book(a,gs):
    s,e=a['s'],a['e']; files=l2files(gs,e)
    if len(files)<4: return None
    toks="("+",".join("'"+t+"'" for t in a['tok2b'])+")"; arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"
    px=q(f"""SELECT asset_id,(ts//3600000)*3600000 hr, arg_max(best_ask,ts) ask, arg_max(best_bid,ts) bid,
        min(best_ask) lo_ask, max(best_bid) hi_bid
        FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={gs*1000} AND ts<{e*1000} GROUP BY 1,2""")
    if px.empty: return None
    px['bucket']=px.asset_id.map(a['tok2b'])
    bk=q(f'SELECT asset_id,CAST("data" AS VARCHAR) AS "data" FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type=\'book\' AND ts>={gs*1000} AND ts<{e*1000}')
    bk['bucket']=bk.asset_id.map(a['tok2b'])
    depth={}
    for b in px.bucket.dropna().unique():
        ds=[]
        for d in bk[bk.bucket==b].data.dropna():
            try: aa=json.loads(d)['asks'][:2]; ds.append(sum(float(x['price'])*float(x['size']) for x in aa))
            except: pass
        depth[b]=float(np.median(ds)) if ds else 30.0
    return px,depth

def kal(a,hh,priors):
    s,e=a['s'],a['e']; total=(e-s)/3600
    o=obs(s,int(s+hh*3600)); rh=total-hh
    if not priors: r=o/max(hh,1)
    else: x=float(np.mean(priors));P=float(np.var(priors))+.01;K=(P+.01)/(P+.01+max(.1,P*.5));r=x+K*(o/max(hh,1)-x)
    proj=o+r*rh; return proj,math.sqrt(max(proj-o,1))*1.5+4
def kstake(edge,px): return (min(max(0.0,edge/(1-px))*KMULT,MAXBET)*BANK) if (edge>0 and 0<px<1) else 0.0

TRADES=[]
def logrow(a,book,ts,b,side,fillpx,shares,rule,fair,ask,bid,lo_ask,hi_bid,proj):
    TRADES.append({'slug':a['slug'],'dur':a['dur'],'book':book,'hour_ts':int(ts),'bracket':b,'side':side,
        'fill_price':round(fillpx,4),'shares':round(shares,1),'rule':rule,'fair':round(fair,4),
        'ask':round(ask,4),'bid':round(bid,4),'lo_ask':round(lo_ask,4),'hi_bid':round(hi_bid,4),
        'proj':round(proj,1),'winner':a['winner']})

def run():
    res=[]; priors=[]
    for a in aucs:
        s,e=a['s'],a['e']; total=(e-s)/3600; gs=max(s,e-48*3600)
        lb=load_book(a,gs)
        if lb is None: continue
        px,depth=lb
        brs=[(b,pbk(b)) for b in px.bucket.dropna().unique() if pbk(b)]
        W=a['winner']; prc=list(priors)
        proj_by_hr={}
        for hr in sorted(px.hr.unique()):
            hh=(hr/1000-s)/3600; rh=total-hh
            if rh<0.5: continue
            proj_by_hr[hr]=kal(a,hh,prc)
        series={}
        for b,(lo,hi) in brs:
            ser=[]
            for hr in sorted(proj_by_hr):
                r=px[(px.bucket==b)&(px.hr==hr)]
                if not len(r): continue
                proj,sig=proj_by_hr[hr]
                ser.append((hr/1000,float(r.ask.iloc[0]),float(r.bid.iloc[0]),float(r.lo_ask.iloc[0]),float(r.hi_bid.iloc[0]),bprob(lo,hi,proj,sig),proj))
            if len(ser)>=3: series[b]=ser
        if not series: continue
        R={k:{'pnl':0.,'cap':0.} for k in ['S1','S2','S3']}

        def hold_book(book):
            lots=[]
            for b,ser in series.items():
                deployed=0.0; capb=depth.get(b,30.0)*2.0
                for ts,ask,bid,lo_ask,hi_bid,fair,proj in ser:
                    if fair>=BAND_FLOOR and (fair-bid)>=MARGIN and bid>0 and lo_ask<=bid+1e-9 and deployed<capb:
                        stake=kstake(fair-bid,bid)
                        fill=min(stake,depth.get(b,30.0),capb-deployed)
                        if fill>=1:
                            sh=fill/bid; deployed+=fill; R[book]['cap']+=fill; lots.append((b,bid,sh))
                            logrow(a,book,ts,b,'BUY',bid,sh,'R4/R6 maker dip-buy below fair (held)',fair,ask,bid,lo_ask,hi_bid,proj)
            return lots

        def scalp_book(book,stake):
            for b,ser in series.items():
                pos=None
                for ts,ask,bid,lo_ask,hi_bid,fair,proj in ser:
                    if pos is None:
                        if (fair-bid)>=MARGIN and bid>0 and lo_ask<=bid+1e-9:
                            fill=min(stake,depth.get(b,30.0))
                            if fill>=1:
                                sh=fill/bid; pos={'px':bid,'sh':sh}; R[book]['cap']+=fill
                                logrow(a,book,ts,b,'BUY',bid,sh,'R5 maker scalp entry below fair',fair,ask,bid,lo_ask,hi_bid,proj)
                    else:
                        q_=fair+MARGIN
                        if hi_bid>=q_-1e-9:
                            sellpx=max(0.0,q_-HAIRCUT); R[book]['pnl']+=pos['sh']*(sellpx-pos['px'])
                            logrow(a,book,ts,b,'SELL',sellpx,pos['sh'],'R5 maker scalp exit above fair',fair,ask,bid,lo_ask,hi_bid,proj); pos=None
                        elif bid<=pos['px']-STOP:
                            sellpx=max(0.0,bid-HAIRCUT); R[book]['pnl']+=pos['sh']*(sellpx-pos['px'])
                            logrow(a,book,ts,b,'SELL',sellpx,pos['sh'],'R5 scalp stop',fair,ask,bid,lo_ask,hi_bid,proj); pos=None
                if pos is not None:
                    ts,ask,bid,lo_ask,hi_bid,fair,proj=ser[-1]; sellpx=max(0.0,bid-HAIRCUT)
                    R[book]['pnl']+=pos['sh']*(sellpx-pos['px'])
                    logrow(a,book,ts,b,'SELL',sellpx,pos['sh'],'R5 flatten at close',fair,ask,bid,lo_ask,hi_bid,proj)

        for (b2,px_,sh) in hold_book('S2'): R['S2']['pnl']+=sh*((1.0 if b2==W else 0.0)-px_)
        scalp_book('S1',SCALP_STAKE)
        for (b2,px_,sh) in hold_book('S3'): R['S3']['pnl']+=sh*((1.0 if b2==W else 0.0)-px_)
        scalp_book('S3',SLEEVE*SCALP_STAKE)

        res.append({'slug':a['slug'],'dur':a['dur'],**{k:R[k] for k in R}})
        priors.append(obs(s,e)/total)
    return res

res=run()
def report(rows,label):
    if not rows: print(f"  {label}: none"); return
    print(f"  {label} (n={len(rows)}):")
    for k in ['S1','S2','S3']:
        cap=sum(r[k]['cap'] for r in rows); pnl=sum(r[k]['pnl'] for r in rows)
        print(f"    {k}  {('$%.0f'%cap):>8}dep {('%+.0f'%pnl):>7}$  ROI {(100*pnl/cap if cap else 0):>+6.1f}%")
print("\n############ TRUE-MAKER CONSERVATIVE FILLS, OFFICIAL WINNERS ############")
report(res,"ALL"); report([r for r in res if r['dur']=='2-day'],"2-day only"); report([r for r in res if r['dur']=='7-day'],"7-day only")
pd.DataFrame(TRADES).to_csv(f"{OUT}/trades.csv",index=False)
arows=[]
for r in res:
    for k in ['S1','S2','S3']: arows.append({'slug':r['slug'],'dur':r['dur'],'book':k,'pnl':round(r[k]['pnl'],2),'cap':round(r[k]['cap'],2)})
pd.DataFrame(arows).to_csv(f"{OUT}/auctions.csv",index=False)
srows=[]
for lab,rows in [('ALL',res),('2-day',[r for r in res if r['dur']=='2-day']),('7-day',[r for r in res if r['dur']=='7-day'])]:
    for k in ['S1','S2','S3']:
        cap=sum(r[k]['cap'] for r in rows); pnl=sum(r[k]['pnl'] for r in rows)
        srows.append({'segment':lab,'n':len(rows),'book':k,'cap':round(cap,2),'pnl':round(pnl,2),'roi_pct':round(100*pnl/cap if cap else 0,1)})
pd.DataFrame(srows).to_csv(f"{OUT}/summary.csv",index=False)
print(f"\nWROTE {OUT}/trades.csv ({len(TRADES)} orders), auctions.csv, summary.csv")
