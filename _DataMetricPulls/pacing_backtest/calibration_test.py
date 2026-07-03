"""STEP 1 (decisive arbiter): is the model's bracket probability SHARPER than the market's
implied probability, and WHERE (by time-to-resolution)? Walk-forward, out-of-sample.
Compares Brier + log-loss of each model vs the market price, sliced by hours-to-go.
If the model never beats the market, slow-forecast convergence is dead -> go to speed/finish-line.
"""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ET = ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
MODELS=['Linear','CurBayes','M0','Decay','M4MMPP','Kalman']
TTG=[120,72,48,36,24,12,6,3,1]   # hours-to-go checkpoints

bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
post_ts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
prc=pd.read_parquet(OUT/'clob_prices.parquet')
price_idx={}
for (sl,bk),g in prc.sort_values('t').groupby(['auction_slug','bucket']):
    price_idx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
def price_at(sl,bk,t):
    a=price_idx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<=v<=1 else None
auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noonET(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
    except: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (int(pd.Timestamp(datetime(yr,mo1,d1,12,0,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,0,tzinfo=ET)).timestamp()))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-');return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(pred,sig,lo,hi):
    sig=max(sig,1.0);zl=(lo-0.5-pred)/sig
    return max(1e-9,(1-ncdf(zl)) if hi is None else (ncdf((hi+0.5-pred)/sig)-ncdf(zl)))
def Linear(o,eh,rh): return 0 if eh<=0 else o*(eh+rh)/eh
def CurBayes(o,eh,rh,pool):
    th=eh+rh
    if not pool or o<=0 or eh<=0: return float(np.mean(pool)) if pool else 0
    ec=min(0.99,max(0.001,eh/th));op=o/ec;pm=float(np.mean(pool));ps=max(1.0,float(np.std(pool,ddof=1)) if len(pool)>1 else pm*0.25);ov=max(1.0,o*(1-ec)/(ec**2));return (pm/ps**2+op/ov)/(1/ps**2+1/ov)
def M0(o,eh,rh,pt,pd_):
    if not pt: return o*(eh+rh)/max(eh,1)
    return o+(sum(pt)+o)/(sum(pd_)+eh)*rh if (sum(pd_)+eh)>0 else o
def Decay(o,eh,rh,pwa,eps=0.85):
    if not pwa: return o*(eh+rh)/max(eh,1)
    a0=sum(t*eps**ag for t,_,ag in pwa);b0=sum(d*eps**ag for _,d,ag in pwa) or 1;return o+(a0+o)/(b0+eh)*rh
def M4MMPP(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    return o+(0.5*(o/max(eh,1))+0.5*float(np.mean(rates)))*rh
def Kalman(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    x=float(np.mean(rates));P=float(np.var(rates))+0.01;R=max(0.1,P*0.5);K=(P+0.01)/(P+0.01+R);return o+(x+K*(o/max(eh,1)-x))*rh
def predof(m,o,eh,rh,pt,pdur,pwa,prate):
    return {'Linear':Linear(o,eh,rh),'CurBayes':CurBayes(o,eh,rh,pt),'M0':M0(o,eh,rh,pt,pdur),'Decay':Decay(o,eh,rh,pwa),'M4MMPP':M4MMPP(o,eh,rh,prate),'Kalman':Kalman(o,eh,rh,prate)}[m]

sel=[]
cur=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
for _,a in cur.iterrows():
    w=noonET(a.auction_slug,a['start_utc'].year)
    if not w: continue
    ns,ne=w;dur=a.duration_type
    if dur=='7-day' and ns<int(pd.Timestamp('2025-09-05',tz='UTC').timestamp()): continue
    if dur=='2-day' and ns<int(pd.Timestamp('2026-01-05',tz='UTC').timestamp()): continue
    try: tokmap=json.loads(a['bracket_yes_token_ids'])
    except: continue
    blab=[b for b in tokmap.keys() if (a.auction_slug,b) in price_idx]
    if not blab: continue
    a_=obs(ns,ne)
    if a_<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,ns=ns,ne=ne,winner=a['winning_bucket'],branges=[(b,pbk(b)) for b in blab if pbk(b)],actual=a_))
sel=sorted(sel,key=lambda x:x['ns'])
print(f"auctions: {len(sel)} (7d={sum(1 for x in sel if x['dur']=='7-day')}, 2d={sum(1 for x in sel if x['dur']=='2-day')})")

# walk-forward error history per (model, ttg) -> time-scaled sigma
errh={(m,t):[] for m in MODELS for t in TTG}
rec=[]
for a in sel:
    ns,ne,winner=a['ns'],a['ne'],a['winner']; total_h=(ne-ns)/3600
    priors=[p for p in sel if p['ne']<ns]
    pt=[p['actual'] for p in priors];pdur=[(p['ne']-p['ns'])/3600 for p in priors]
    prate=[p['actual']/((p['ne']-p['ns'])/3600) for p in priors if p['ne']>p['ns']]
    pwa=[(p['actual'],(p['ne']-p['ns'])/3600,(ns-p['ne'])/604800) for p in priors]
    for ttg in TTG:
        if ttg>=total_h: continue
        eh=total_h-ttg
        if eh<=0.5: continue
        cps=ne-ttg*3600; o=obs(ns,cps)
        # market implied probs
        mk={b:price_at(a['slug'],b,cps) for b,_ in a['branges']}
        mk={b:v for b,v in mk.items() if v is not None}
        if winner not in mk or sum(mk.values())<=0: mkt_ll=mkt_br=None
        else:
            tot=sum(mk.values()); mp={b:v/tot for b,v in mk.items()}
            mkt_ll=-math.log(max(mp.get(winner,1e-9),1e-9))
            mkt_br=sum((mp.get(b,0)-(1.0 if b==winner else 0))**2 for b,_ in a['branges'])
        for m in MODELS:
            pred=predof(m,o,eh,ttg,pt,pdur,pwa,prate)
            eh_=errh[(m,ttg)]; sig=float(np.std(eh_)) if len(eh_)>=5 else max(8.0,0.15*max(pred,1))
            wp={b:bprob(pred,sig,lo,hi) for b,(lo,hi) in a['branges']}; tot=sum(wp.values()) or 1; wp={b:v/tot for b,v in wp.items()}
            ll=-math.log(max(wp.get(winner,1e-9),1e-9))
            br=sum((wp.get(b,0)-(1.0 if b==winner else 0))**2 for b,_ in a['branges'])
            rec.append(dict(dur=a['dur'],ttg=ttg,model=m,mdl_ll=ll,mdl_br=br,mkt_ll=mkt_ll,mkt_br=mkt_br))
            errh[(m,ttg)].append(a['actual']-pred)
R=pd.DataFrame(rec)

# ---- report: model vs market by time-to-go ----
out_rows=[]
for dur in ['7-day','2-day']:
    print(f"\n================= {dur}: model vs MARKET calibration (lower=sharper) =================")
    print(f"{'h_to_go':>8}{'n':>5} | {'MARKET_brier':>12}{'MARKET_ll':>11} | best model (brier) & does any model beat market?")
    for ttg in TTG:
        s=R[(R.dur==dur)&(R.ttg==ttg)]
        s=s.dropna(subset=['mkt_br'])
        if not len(s): continue
        n=int(s.model.eq('Kalman').sum())
        mkt_br=float(s.mkt_br.mean()); mkt_ll=float(s.mkt_ll.mean())
        perm={m:(float(s[s.model==m].mdl_br.mean()), float(s[s.model==m].mdl_ll.mean())) for m in MODELS}
        best=min(perm, key=lambda m:perm[m][0]); bb=perm[best][0]
        beats=[m for m in MODELS if perm[m][0]<mkt_br]
        flag='  <-- MODEL BEATS MARKET: '+','.join(beats) if beats else '   (market sharper)'
        print(f"{ttg:>8}{n:>5} | {mkt_br:>12.3f}{mkt_ll:>11.3f} | best={best} brier={bb:.3f}{flag}")
        out_rows.append([dur,int(ttg),n,round(mkt_br,3),round(mkt_ll,3),best,round(bb,3),','.join(beats) if beats else 'none',
                         *[round(perm[m][0],3) for m in MODELS]])

# write to sheet
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc=build('sheets','v4',credentials=creds); SID='1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'; TAB='_Calibration_vs_Market'
meta=svc.spreadsheets().get(spreadsheetId=SID,fields='sheets(properties(title))').execute()
if TAB not in [s['properties']['title'] for s in meta['sheets']]:
    svc.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':[{'addSheet':{'properties':{'title':TAB}}}]}).execute()
svc.spreadsheets().values().clear(spreadsheetId=SID,range=f'{TAB}!A1:Z200').execute()
hdr=['series','hours_to_go','n','MARKET_brier','MARKET_logloss','best_model','best_model_brier','models_beating_market']+[f'{m}_brier' for m in MODELS]
svc.spreadsheets().values().update(spreadsheetId=SID,range=f'{TAB}!A1',valueInputOption='RAW',
    body={'values':[['STEP 1 calibration: model bracket-prob vs MARKET implied prob, walk-forward, by hours-to-go. Lower brier/logloss = sharper. A model only has edge where its brier < MARKET_brier.'],hdr]+out_rows}).execute()
print(f"\nWrote _Calibration_vs_Market. https://docs.google.com/spreadsheets/d/{SID}/edit")
