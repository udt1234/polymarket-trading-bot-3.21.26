# -*- coding: utf-8 -*-
"""Whose odds do you trust? At checkpoints across every pmxt-covered 2-day auction, score OUR
Ens+Cap1.5 odds vs the MARKET's odds against the actual winning bracket. Log-loss (lower=better) +
hit-rate (did the top-prob bracket win). Answers: can we beat the market's probability, or is EV=0?"""
import glob, os, json, math, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; PMX=ROOT+"/_DataMetricPulls/pmxt_pulled"; ET=ZoneInfo('America/New_York'); con=duckdb.connect()
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms'); pts=(bf.ms.to_numpy()//1000).astype('int64'); c0=int(pts.min()); c1=int(pts.max())
def obs(a,b): return int(np.searchsorted(pts,b)-np.searchsorted(pts,a))
M={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); mo1=M[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in M: mo2=M[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
def pbk(l):
    l=str(l).strip()
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),10**9)
    if '-' in l: a,b=l.split('-'); return (int(a),int(b))
    return (int(l),int(l))
SQRT2=math.sqrt(2)
def Phi(x,mu,sd): return 0.5*(1+math.erf((x-mu)/(sd*SQRT2)))
def fair(lo,hi,c,sd): return max(1e-6,min(1-1e-6, Phi((hi+0.5) if hi<10**9 else 1e9,c,sd)-Phi(lo-0.5,c,sd)))
_SIG_RH=[1,4,8,12,18,24,32,40,48]; _SIG_SD=[5.0,7.8,10.8,15.5,16.8,18.9,31.4,38.2,42.0]
def calib_sigma(rh): return max(float(np.interp(rh,_SIG_RH,_SIG_SD)),1.0)
def share_wf(before):
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; cur=[]
    while d.timestamp()+48*3600<=before:
        ss=int(d.timestamp()); f=obs(ss,ss+48*3600)
        if f>=5: cur.append(np.array([obs(ss,ss+h*3600) for h in range(1,49)],float)/f)
        d=d+pd.Timedelta(days=1)
    return np.clip(np.median(np.vstack(cur),axis=0),1e-3,1.0) if cur else None
def cap15(o,eh,rh,rmean,Kk,share,cp):
    kal=o+(rmean+Kk*(o/eh-rmean))*rh; acc=o/share[min(47,max(0,int(eh)-1))]; ens=(1-cp)*kal+cp*acc; return o+min((ens-o)/max(rh,.1),1.5*rmean)*rh
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
PMS=int(pd.Timestamp(datetime(2026,4,15,tzinfo=ET)).timestamp()); PME=int(pd.Timestamp(datetime(2026,6,22,tzinfo=ET)).timestamp())
A=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    try: s,e=noon(a.auction_slug)
    except: continue
    if not 1.5<=(e-s)/86400<=2.6 or s<max(PMS,c0+7200) or e>min(PME,c1): continue
    tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    if not tok: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'win':str(a.winning_bucket),'tok':tok})
A=sorted(A,key=lambda x:x['s'])
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(PMX+f"/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))
CK=[36,24,18,12,6,3]; rows={h:{'our_ll':[],'mkt_ll':[],'our_hit':[],'mkt_hit':[]} for h in CK}; nau=0
for a in A:
    s,e=a['s'],a['e']; priors=[p for p in A if p['e']<s]
    if len(priors)<4: continue
    pr=[obs(p['s'],p['e'])/48 for p in priors]; rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5)); share=share_wf(s)
    if share is None: continue
    fs=pmxt_files(s,e)
    if not fs: continue
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'; t2l={str(v):k for k,v in a['tok'].items()}; tlk='('+','.join("'"+str(v)+"'" for v in a['tok'].values())+')'
    px=con.execute(f"""SELECT ts,CAST(asset_id AS VARCHAR) aid, CASE WHEN COALESCE(best_bid,0)>0 THEN (best_bid+best_ask)/2 ELSE best_ask END AS mid FROM read_parquet({arr},union_by_name=true) WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {tlk} AND best_ask>0 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if len(px)<300: continue
    px['lab']=px.aid.map(t2l); Bk={l:{'ts':g.ts.to_numpy().astype('int64'),'mid':g['mid'].to_numpy(float)} for l,g in px.groupby('lab')}
    order=sorted(a['tok'].keys(),key=lambda l:pbk(l)[0]); rng={l:pbk(l) for l in order}; win=a['win']
    if win not in order: continue
    nau+=1
    for H in CK:
        t=e-H*3600; eh=(t-s)/3600; rh=H; cp=eh/48; o=obs(s,t)
        c=cap15(o,eh,rh,rmean,Kk,share,cp); sd=calib_sigma(rh)
        of={l:fair(rng[l][0],rng[l][1],c,sd) for l in order}; tot=sum(of.values()); of={l:of[l]/tot for l in of}
        mk={}
        for l in order:
            d=Bk.get(l); i=(np.searchsorted(d['ts'],t*1000,'right')-1) if d else -1; mk[l]=max(d['mid'][i],1e-6) if (d and i>=0) else 1e-6
        mt=sum(mk.values()); mk={l:mk[l]/mt for l in mk}
        rows[H]['our_ll'].append(-math.log(max(of[win],1e-4))); rows[H]['mkt_ll'].append(-math.log(max(mk[win],1e-4)))
        rows[H]['our_hit'].append(1 if max(of,key=of.get)==win else 0); rows[H]['mkt_hit'].append(1 if max(mk,key=mk.get)==win else 0)
print(f"calibration set: {nau} auctions (pmxt-covered, resolved)\n")
print(f"{'hrs_left':>8} | {'OUR logloss':>11} | {'MKT logloss':>11} | {'OUR top-hit':>11} | {'MKT top-hit':>11}")
for H in CK:
    r=rows[H]
    print(f"{H:>7}h | {np.mean(r['our_ll']):>11.3f} | {np.mean(r['mkt_ll']):>11.3f} | {100*np.mean(r['our_hit']):>10.0f}% | {100*np.mean(r['mkt_hit']):>10.0f}%")
print("\n(log-loss LOWER = better/more accurate odds; top-hit% = did the highest-prob bracket actually win)")
