# -*- coding: utf-8 -*-
"""S0: RE-PICK THE PACING MODEL ON THE RIGHT OBJECTIVE.
I ranked models by bracket-HIT %. Wrong target. For the divergence strategy to work, our pace must be
CLOSER TO THE TRUTH THAN THE MARKET, bar by bar. Score every model against the market's implied count
(reverse-pace used ONLY as benchmark, never as signal). If no model beats the market on >50% of bars,
the divergence premise is dead."""
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
def share_wf(dur_h,before_ts):
    if (dur_h,before_ts) in _sc: return _sc[(dur_h,before_ts)]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; f=obs(ss,ee)
        if f>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/f)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None; _sc[(dur_h,before_ts)]=r; return r
def diurnal(bs):
    h=hd_all[pts<bs]
    return np.ones(24) if len(h)<240 else (lambda m:m/m.mean())(np.array([np.sum(h==hh) for hh in range(24)],float))
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
L2START=int(datetime(2026,4,13,19,tzinfo=timezone.utc).timestamp()); NOWC=int(datetime(2026,6,23,tzinfo=timezone.utc).timestamp())
ALLP=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w or w[1]>c1 or w[1]<=w[0]: continue
    ALLP.append({'s':w[0],'e':w[1],'final':obs(*w)})
recs=[]; naucs=0
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
    total=(e-s)/3600; FINAL=obs(s,e)
    if FINAL<5: continue
    pr=[p['final']/((p['e']-p['s'])/3600) for p in ALLP if p['e']<s]
    pf=[p['final'] for p in ALLP if p['e']<s]
    if len(pr)<6: continue
    rmean=float(np.mean(pr)); pmean=float(np.mean(pf)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    mult=diurnal(s); share=share_wf(48,s)
    hours=pd.to_datetime(s+np.arange(49)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
    effcum=np.concatenate([[0],np.cumsum(mult[hours[:-1]])])
    ermean=float(np.mean([p['final']/max(effcum[-1],0.1) for p in ALLP if p['e']<s]))
    arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in t2b)+")"
    px=q(f"""SELECT asset_id,(ts//600000)*600000 bar, arg_max(best_bid,ts) bid, arg_max(best_ask,ts) ask
        FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
    if px.empty: continue
    px['bucket']=px.asset_id.map(t2b); px['mid']=np.where(px.bid>0,(px.bid+px.ask)/2,px.ask)
    grid=px.pivot_table(index='bar',columns='bucket',values='mid',aggfunc='last').sort_index().ffill()
    brs={b:pbk(b) for b in grid.columns if pbk(b)}
    if len(brs)<5: continue
    naucs+=1
    for bar in grid.index:
        t=bar/1000.0; eh=(t-s)/3600.0; rh=total-eh; cp=eh/total
        if eh<2 or rh<0.3: continue
        o=obs(s,int(t))
        prices={b:grid.loc[bar,b] for b in brs if pd.notna(grid.loc[bar,b]) and grid.loc[bar,b]>0}
        tot=sum(prices.values())
        if tot<=0: continue
        mkt=sum(center(*brs[b])*(p/tot) for b,p in prices.items())
        lin=o*total/eh
        kal=o+(rmean+Kk*(o/eh-rmean))*rh
        eel=effcum[min(48,int(eh))]; erm=effcum[-1]-eel
        ksl=o+(ermean+Kk*(o/max(eel,.1)-ermean))*erm
        acc=o/share[min(len(share)-1,max(0,int(eh)-1))]
        ens=(1-cp)*kal+cp*acc
        def cap(p,m): r=(p-o)/max(rh,.1); return o+min(r,m*rmean)*rh
        b24=o+((24*rmean+eh*(o/eh))/(24+eh))*rh
        proj={'PriorOnly':pmean,'Linear':lin,'Kalman':kal,'Kalman+Sleep':ksl,'Accrual':acc,'Ensemble':ens,
              'Ens+CAP1.5 (LOCKED)':cap(ens,1.5),'Ens+CAPtv':cap(ens,1.3+1.5*cp),'Bayes-tau24':b24}
        me=abs(mkt-FINAL)
        for m,pv in proj.items():
            recs.append({'model':m,'hrs_in':eh,'our_err':abs(pv-FINAL),'mkt_err':me})
R=pd.DataFrame(recs)
print(f"S0 RE-SCORE: {naucs} two-day auctions with real L2, {len(R)//max(R.model.nunique(),1)} bars per model\n")
def bucket(h): return 'first12h' if h<=12 else ('12-36h' if h<=36 else 'last12h')
R['win']=R.our_err<R.mkt_err; R['wb']=R.hrs_in.apply(bucket)
rows=[]
for m,d in R.groupby('model'):
    r={'model':m,'BEATS MARKET %':100*d.win.mean(),'our_err':d.our_err.mean(),'market_err':d.mkt_err.mean()}
    for b in ['first12h','12-36h','last12h']:
        sub=d[d.wb==b]; r[f'beat_{b}%']=100*sub.win.mean() if len(sub) else np.nan
    rows.append(r)
lb=pd.DataFrame(rows).sort_values('BEATS MARKET %',ascending=False)
pd.set_option('display.width',200)
print(lb.round(1).to_string(index=False))
print("\n"+"="*94)
best=lb.iloc[0]
print(f"BEST vs MARKET: {best.model} beats the market on {best['BEATS MARKET %']:.1f}% of bars")
print(f"  mean error: ours {best.our_err:.1f} tweets  vs  market {best.market_err:.1f} tweets")
print("\nA model must beat the market on >50% of bars for the divergence premise to work.")
print("RESULT: " + ("A MODEL BEATS THE MARKET -> divergence is tradeable." if best['BEATS MARKET %']>50 else
      "NO MODEL BEATS THE MARKET -> the divergence premise is DEAD."))
print("="*94)
lb.to_csv(f"{OUT}/beat_market.csv",index=False)
