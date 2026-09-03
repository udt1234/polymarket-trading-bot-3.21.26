# -*- coding: utf-8 -*-
"""SWEEP variant: SCALP the seesaw instead of HOLDING to resolution. Same pace-model bracket pick
(no look-ahead, event-driven), but we SELL: take profit when a bracket pops >= POP over avg cost,
and FLATTEN everything at the bid FLAT_H hours before close (never eat a -100% held loser). This
tests the data's verdict from the hold sweep: the -100% wipeouts are a CHOICE (holding), not a law.
Sells at the bid (conservative maker exit). Compare pooled ROI vs the hold version (-10.8%)."""
import duckdb, sys, glob, os, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"
PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"; OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
DIP=0.03; TRANCHE=50.0; COOLDOWN=180; MAXPOS=500.0; EMA_ALPHA=0.02; GATE_H=3.0; PROJ_EVERY=120; POP=0.05; FLAT_H=2.0   # knobs

bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug):
    try:
        tk=str(slug).replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
    except Exception: return None
_sc={}
def share_wf(dur_h,before_ts):
    if (dur_h,before_ts) in _sc: return _sc[(dur_h,before_ts)]
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    r=np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None; _sc[(dur_h,before_ts)]=r; return r
def ens_cap15(o,eh,rh,rmean,Kk,share,cp):
    if eh<1e-6: return o
    kal=o+(rmean+Kk*(o/eh-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(eh)-1))] if share is not None else o*(eh+rh)/eh
    ens=(1-cp)*kal+cp*acc
    r=(ens-o)/max(rh,.1); return o+min(r,1.5*rmean)*rh
def pick2(P,order,rng):
    r=round(P); idx=None
    for i,lab in enumerate(order):
        lo,hi=rng[lab]
        if lo<=r<=hi: idx=i; break
    if idx is None: idx=0 if r<rng[order[0]][0] else len(order)-1
    lo,hi=rng[order[idx]]; up=(hi-r)<(r-lo); j=idx+1 if up else idx-1
    if j<0: j=idx+1
    if j>=len(order): j=idx-1
    return {order[idx], order[max(0,min(len(order)-1,j))]}

auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True,errors='coerce'); A=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug)
    if not w: continue
    s,e=w; days=(e-s)/86400
    if not 1.5<=days<=2.6 or e>c1 or s<c0+7200: continue
    win=pbk(str(a.winning_bucket))
    if not win: continue
    tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    if not tok: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'win':win,'winlab':str(a.winning_bucket),'final':obs(s,e),'tok':tok})
A=sorted(A,key=lambda x:x['s'])
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))
print(f"sweep set: {len(A)} two-day auctions | MODE=SCALP (sell on +{POP} pop, flatten {FLAT_H}h before close)")

allrows=[]; alltr=[]
for ai,a in enumerate(A):
    s,e=a['s'],a['e']; total=(e-s)/3600.0; dur_h=48
    priors=[p for p in A if p['e']<s]
    if len(priors)<4: continue
    pr=[p['final']/((p['e']-p['s'])/3600) for p in priors]; rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    share=share_wf(dur_h,s); fs=pmxt_files(s,e)
    if not fs: continue
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    tok2lab={str(v):k for k,v in a['tok'].items()}; toklist='('+','.join("'"+str(v)+"'" for v in a['tok'].values())+')'
    px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1
        AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if len(px)<500: continue
    px['lab']=px.aid.map(tok2lab); px['mid']=np.where(px.best_bid>0,(px.best_bid+px.best_ask)/2,px.best_ask)
    order=sorted(a['tok'].keys(), key=lambda l:pbk(l)[0]); rng={l:pbk(l) for l in order}
    tw=pts[(pts>=s)&(pts<e)]
    tp=(px.ts.to_numpy()//1000).astype('int64'); lab=px.lab.to_numpy(); ask=px.best_ask.to_numpy(float); bid=px.best_bid.to_numpy(float); mid=px.mid.to_numpy(float)
    ts_all=np.concatenate([tp,tw]); typ=np.concatenate([np.zeros(len(tp),np.int8),np.ones(len(tw),np.int8)]); idxp=np.concatenate([np.arange(len(tp)),-np.ones(len(tw),int)])
    o_=np.argsort(ts_all,kind='stable'); ts_all=ts_all[o_]; typ=typ[o_]; idxp=idxp[o_]
    o=0; ema={l:None for l in order}; bbid={l:0.0 for l in order}; last_buy={l:-10**9 for l in order}
    shares={l:0.0 for l in order}; cost={l:0.0 for l in order}; realized=0.0; P=None; last_proj=-10**9; targets=set()
    for k in range(len(ts_all)):
        t=int(ts_all[k])
        if typ[k]==1: o+=1
        else:
            i=idxp[k]; l=lab[i]; ema[l]=mid[i] if ema[l] is None else EMA_ALPHA*mid[i]+(1-EMA_ALPHA)*ema[l]; bbid[l]=bid[i]
        eh=(t-s)/3600.0; rh=total-eh; cp=eh/total
        if eh>=GATE_H and rh>0.2 and (typ[k]==1 or t-last_proj>=PROJ_EVERY or P is None):
            P=ens_cap15(o,eh,rh,rmean,Kk,share,cp); targets=pick2(P,order,rng); last_proj=t
        if typ[k]==0 and P is not None:
            i=idxp[k]; l=lab[i]; a_=ask[i]; b_=bid[i]
            # SELL: take profit on pop, or flatten near close
            if shares[l]>0:
                avg=cost[l]/shares[l]
                if (b_>=avg+POP) or (rh<=FLAT_H):
                    realized+=shares[l]*b_-cost[l]; alltr.append({'slug':a['slug'],'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'act':'SELL','bracket':l,'price':round(b_,3),'rh':round(rh,1),'pnl':round(shares[l]*b_-cost[l],1)}); shares[l]=0.0; cost[l]=0.0
            # BUY dip on target brackets (only while not flattening window)
            if eh>=GATE_H and rh>FLAT_H and l in targets and ema[l] is not None and a_<=ema[l]-DIP and t-last_buy[l]>=COOLDOWN and cost[l]+TRANCHE<=MAXPOS:
                sh=TRANCHE/a_; shares[l]+=sh; cost[l]+=TRANCHE; last_buy[l]=t
                alltr.append({'slug':a['slug'],'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'act':'BUY','bracket':l,'price':round(a_,3),'rh':round(rh,1),'pnl':0})
    # force-flatten any residual at last seen bid
    for l in order:
        if shares[l]>0: realized+=shares[l]*bbid[l]-cost[l]; shares[l]=0.0; cost[l]=0.0
    deployed=sum(TRANCHE for tr in alltr if tr['slug']==a['slug'] and tr['act']=='BUY')
    allrows.append({'#':ai,'slug':a['slug'].replace('elon-musk-of-tweets-',''),'winner':a['winlab'],'actual':a['final'],
        'deployed':round(deployed),'pnl':round(realized),'roi%':round(100*realized/deployed,1) if deployed else 0.0,
        'nbuys':sum(1 for tr in alltr if tr['slug']==a['slug'] and tr['act']=='BUY'),'nsells':sum(1 for tr in alltr if tr['slug']==a['slug'] and tr['act']=='SELL')})
    print(f"  {a['slug'].replace('elon-musk-of-tweets-',''):<24} win {a['winlab']:<7} act {a['final']:>3} | deployed ${round(deployed):>4} | P&L ${round(realized):>+5} ({round(100*realized/deployed,1) if deployed else 0:+.0f}%)")

R=pd.DataFrame(allrows); pd.DataFrame(alltr).to_csv(f"{OUT}/sweep_scalp_trades.csv",index=False); R.to_csv(f"{OUT}/sweep_scalp_auctions.csv",index=False)
tr=R[R.deployed>0]
print("\n=== SCALP SWEEP SUMMARY ===")
print(f"auctions traded: {len(tr)} | total deployed ${tr.deployed.sum():,.0f} | total P&L ${tr.pnl.sum():,.0f} | pooled ROI {100*tr.pnl.sum()/tr.deployed.sum():+.1f}%")
print(f"win-rate (auctions +P&L): {100*(tr.pnl>0).mean():.0f}% ({(tr.pnl>0).sum()}/{len(tr)}) | median auction ROI {tr['roi%'].median():+.1f}% | worst {tr['roi%'].min():+.0f}% best {tr['roi%'].max():+.0f}%")
print(f"\nHOLD version was -10.8% pooled. SCALP is {100*tr.pnl.sum()/tr.deployed.sum():+.1f}%.")
print(f"WROTE {OUT}/sweep_scalp_auctions.csv and sweep_scalp_trades.csv")
