# -*- coding: utf-8 -*-
"""SIR'S DIVERGENCE STRATEGY, on the shape we agreed, across every 2-day auction with real L2.

  CENTER  = LOCKED pace model Ens+CAP1.5 (Kalman early + AccrualCurve late, rate capped at 1.5x baseline)
  MARKET  = reverse-pace (market's implied count) - used as the OTHER OPINION, not as our fair value
  EDGE    = divergence. Buy the bracket OUR center points to; rotate when it moves; exit on convergence.
  GATE    = hour 12+ ONLY. S0 proved we LOSE to the market in the first 12h (37%) and WIN after
            (58.5% at 12-36h, 69.5% in the last 12h). No trades before hour 12.
  PRICING = the MARKET's prices, never our overconfident probabilities (our edge is the CENTER not the SPREAD).
  FILLS   = conservative MAKER only. A BUY fills only if the bar's LOW ask crosses down to our resting bid.
            A SELL fills only if the bar's HIGH bid crosses up to our resting ask. Haircut on every exit.
            Depth-capped. Winners from OFFICIAL Gamma resolution.
"""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
hd_all=pd.to_datetime(pts,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
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
def center(lo,hi): return (lo+15) if hi>=10**8 else (lo+hi)/2.0
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
_sc={}
def share_wf(dh,bt):
    if (dh,bt) in _sc: return _sc[(dh,bt)]
    n0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=n0; cv=[]
    while d.timestamp()+dh*3600<=bt:
        ss=int(d.timestamp()); ee=ss+dh*3600; f=obs(ss,ee)
        if f>=5: cv.append(np.array([obs(ss,ss+h*3600) for h in range(1,dh+1)],float)/f)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(cv),axis=0),1e-3,1.0) if cv else None; _sc[(dh,bt)]=r; return r
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs

BANK=5394.0; STAKE=0.02*BANK; ENTER=5.0; EXIT=2.0; STOP=0.06; HAIRCUT=0.01; CAPMULT=1.5
GATE_H=float(sys.argv[1]) if len(sys.argv)>1 else 12.0
TAG=f"gate{int(GATE_H)}"
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
L2START=int(datetime(2026,4,13,19,tzinfo=timezone.utc).timestamp()); NOWC=int(datetime(2026,6,23,tzinfo=timezone.utc).timestamp())
ALLP=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w or w[1]>c1 or w[1]<=w[0]: continue
    ALLP.append({'s':w[0],'e':w[1],'final':obs(*w)})

TR=[]; AU=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w
    if not(1.5<=(e-s)/86400<=2.6) or e<L2START or e>NOWC: continue
    try: tm=json.loads(a.bracket_yes_token_ids)
    except: continue
    t2b={t:l for l,t in tm.items() if isinstance(t,str) and t.isdigit() and len(t)>18 and pbk(l)}
    if len(t2b)<5: continue
    files=l2files(s,e)
    if len(files)<20: continue
    total=(e-s)/3600; FINAL=obs(s,e); W=str(a.winning_bucket).strip()
    if FINAL<5 or not pbk(W): continue
    pr=[p['final']/((p['e']-p['s'])/3600) for p in ALLP if p['e']<s]
    if len(pr)<6: continue
    rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5)); share=share_wf(48,s)
    arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in t2b)+")"
    px=q(f"""SELECT asset_id,(ts//600000)*600000 bar, arg_max(best_bid,ts) bid, arg_max(best_ask,ts) ask,
        min(best_ask) lo_ask, max(best_bid) hi_bid
        FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
    if px.empty: continue
    px['b']=px.asset_id.map(t2b)
    bk=q(f'SELECT asset_id,CAST("data" AS VARCHAR) AS "data" FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type=\'book\' AND ts>={s*1000} AND ts<{e*1000}')
    bk['b']=bk.asset_id.map(t2b); depth={}
    for b in px.b.dropna().unique():
        ds=[]
        for d in bk[bk.b==b].data.dropna():
            try: aa=json.loads(d)['asks'][:2]; ds.append(sum(float(x['price'])*float(x['size']) for x in aa))
            except: pass
        depth[b]=float(np.median(ds)) if ds else 30.0
    P={c:px.pivot_table(index='bar',columns='b',values=c,aggfunc='last').sort_index().ffill() for c in ['bid','ask','lo_ask','hi_bid']}
    brs={b:pbk(b) for b in P['bid'].columns if pbk(b)}
    if len(brs)<5: continue
    pos=None; pnl=0.0; cap=0.0; nb=0
    bars=list(P['bid'].index)
    for i,bar in enumerate(bars):
        t=bar/1000.0; eh=(t-s)/3600.0; rh=total-eh; cp=eh/total
        if eh<GATE_H or rh<0.3: continue                      # <-- THE GATE
        o=obs(s,int(t))
        kal=o+(rmean+Kk*(o/eh-rmean))*rh
        acc=o/share[min(len(share)-1,max(0,int(eh)-1))]
        ens=(1-cp)*kal+cp*acc
        our=o+min((ens-o)/max(rh,.1), CAPMULT*rmean)*rh       # LOCKED Ens+CAP1.5
        pr_={b:P['bid'].loc[bar,b] for b in brs if pd.notna(P['ask'].loc[bar,b]) and P['ask'].loc[bar,b]>0}
        aq={b:P['ask'].loc[bar,b] for b in pr_}
        tot=sum(aq.values())
        if tot<=0: continue
        mkt=sum(center(*brs[b])*(aq[b]/tot) for b in aq)
        div=our-mkt
        target=next((b for b,(lo,hi) in brs.items() if lo<=round(our)<=hi),None)
        def row(act,b,pxx,sh,rsn):
            TR.append({'slug':a.auction_slug.replace('elon-musk-of-tweets-',''),'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),
                'hrs_in':round(eh,1),'action':act,'bracket':b,'won_at_resolution':'WINNER' if b==W else 'loser',
                'fill_price':round(pxx,4),'shares':round(sh,1),'tweets':o,'our_center':round(our,1),
                'market_center':round(mkt,1),'divergence':round(div,1),'why':rsn})
        if pos is None:
            if abs(div)>=ENTER and target and target in pr_:
                bid=float(P['bid'].loc[bar,target]); loa=float(P['lo_ask'].loc[bar,target])
                if bid>0 and loa<=bid+1e-9:                    # maker fill: a seller crossed to our bid
                    fill=min(STAKE,depth.get(target,30.0))
                    if fill>=1:
                        sh=fill/bid; pos={'b':target,'px':bid,'sh':sh}; cap+=fill; nb+=1
                        row('BUY',target,bid,sh,f"our center {our:.0f} vs market {mkt:.0f}, edge {abs(div):.0f}")
        else:
            b=pos['b']; bid=float(P['bid'].loc[bar,b]); ask=float(P['ask'].loc[bar,b]); hib=float(P['hi_bid'].loc[bar,b])
            conv=abs(div)<=EXIT; rot=(target!=b); stop=(bid<=pos['px']-STOP)
            if (conv or rot) and hib>=ask-1e-9 and ask>0:      # maker sell: a buyer crossed to our ask
                px_=max(0.0,ask-HAIRCUT); p=pos['sh']*(px_-pos['px']); pnl+=p
                row('SELL',b,px_,pos['sh'],('divergence converged' if conv else f"pace moved to {target}")); pos=None
            elif stop:
                px_=max(0.0,bid-HAIRCUT); p=pos['sh']*(px_-pos['px']); pnl+=p
                row('SELL',b,px_,pos['sh'],'stop loss'); pos=None
    if pos is not None:                                        # flatten at close on the bid
        bar=bars[-1]; t=bar/1000.0; b=pos['b']; bid=float(P['bid'].loc[bar,b])
        px_=max(0.0,bid-HAIRCUT); pnl+=pos['sh']*(px_-pos['px'])
        eh=(t-s)/3600.0; o=obs(s,int(t)); our=mkt=div=0
        TR.append({'slug':a.auction_slug.replace('elon-musk-of-tweets-',''),'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),
            'hrs_in':round(eh,1),'action':'SELL','bracket':b,'won_at_resolution':'WINNER' if b==W else 'loser',
            'fill_price':round(px_,4),'shares':round(pos['sh'],1),'tweets':o,'our_center':None,'market_center':None,
            'divergence':None,'why':'flatten at close'})
    AU.append({'slug':a.auction_slug.replace('elon-musk-of-tweets-',''),'winner':W,'final':FINAL,'buys':nb,
               'deployed':round(cap,2),'pnl':round(pnl,2),'roi_pct':round(100*pnl/cap,1) if cap else 0.0})
tr=pd.DataFrame(TR); au=pd.DataFrame(AU)
tr.to_csv(f"{OUT}/strategy_trades_{TAG}.csv",index=False); au.to_csv(f"{OUT}/strategy_auctions_{TAG}.csv",index=False)
pd.set_option('display.width',220)
print(f"=== DIVERGENCE STRATEGY | locked Ens+CAP1.5 | GATE hour {GATE_H:.0f}+ | conservative MAKER fills | official winners ===\n")
print(au.to_string(index=False))
tot_cap=au.deployed.sum(); tot_pnl=au.pnl.sum()
buys=tr[tr.action=='BUY']; traded=au[au.buys>0]
print("\n"+"="*100)
print(f"auctions traded: {len(traded)}/{len(au)} | BUY orders: {len(buys)} | SELL orders: {len(tr[tr.action=='SELL'])}")
print(f"capital deployed ${tot_cap:,.0f} | P&L ${tot_pnl:+,.0f} | ROI {100*tot_pnl/tot_cap if tot_cap else 0:+.1f}%")
print(f"profitable auctions: {(traded.pnl>0).sum()}/{len(traded)}")
if len(traded)>1:
    m=traded.roi_pct.mean(); sd=traded.roi_pct.std(); se=sd/math.sqrt(len(traded))
    print(f"per-auction ROI mean {m:+.1f}% | std {sd:.1f}% | std-err {se:.1f}%  -> {'SIGNIFICANT' if abs(m)>2*se else 'NOT significant (inside noise)'}")
if len(buys): print(f"BUYs on the bracket that eventually WON: {(buys.won_at_resolution=='WINNER').sum()}/{len(buys)} ({100*(buys.won_at_resolution=='WINNER').mean():.0f}%)")
print("="*100)
