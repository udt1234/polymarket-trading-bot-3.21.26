"""Bracket-level scoring of the CLEAN backtest, split by series (7-day / 2-day).
worth = P(final count in bracket). Metrics: bracket-hit, logloss, brier, P_winner,
convergence PnL vs real prices, and a Market baseline. Writes grid to the sheet.
"""
import os, sys, math
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
GAP=0.05; MODELS=['Linear','CurBayes','M0','M1Seas','Decay','M2Hawk','M3Hawk','M4MMPP','M5NB','Kalman']

res = pd.read_csv(OUT/'backtest_clean_results.csv')
res['ns_dt']=pd.to_datetime(res['ns'],utc=True)
res=res.sort_values('ns_dt').reset_index(drop=True)
pri = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'prices/elonmusk').glob('*.parquet'))], ignore_index=True)
pri['hsec']=(pd.to_datetime(pri['hour_utc'],utc=True).astype('int64')//10**9)
buckets_by_slug=pri.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
price_idx={}
for (sl,bk),g in pri.sort_values('hsec').groupby(['auction_slug','bucket']):
    price_idx[(sl,bk)]=(g['hsec'].to_numpy(),g['close'].to_numpy())

def parse_bucket(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def ncdf(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def bprob(pred,sig,lo,hi):
    sig=max(sig,1.0); zl=(lo-0.5-pred)/sig
    return max(0.0,1-ncdf(zl)) if hi is None else max(0.0,ncdf((hi+0.5-pred)/sig)-ncdf(zl))
def price_at(sl,bk,cs):
    arr=price_idx.get((sl,bk))
    if arr is None: return None
    hs,cl=arr; i=np.searchsorted(hs,cs,side='right')-1
    if i<0: return None
    v=float(cl[i]); return v if 0<v<1 else None

records=[]
for cp,hr in [('T2d',48),('T1d',24)]:
    ehist={m:[] for m in MODELS}
    for _,r in res.iterrows():
        if r.get(f'Linear_{cp}','')=='' or pd.isna(r.get(f'Linear_{cp}',np.nan)): continue
        slug=r['slug']; dur=r['dur']; actual=float(r['actual']); winner=r['winner']
        blabels=buckets_by_slug.get(slug)
        if not blabels: continue
        if winner not in blabels: blabels=sorted(set(blabels)|{winner})
        branges=[(b,parse_bucket(b)) for b in blabels]; branges=[(b,rg) for b,rg in branges if rg]
        ns=int(r['ns_dt'].timestamp()); eh=float(r['total_hours'])-hr; cps=ns+int(eh*3600)
        mkt={b:price_at(slug,b,cps) for b,_ in branges}; mkta={b:v for b,v in mkt.items() if v is not None}
        for m in MODELS+['Market']:
            if m=='Market':
                if len(mkta)<2: continue
                worth=dict(mkta); pred=None
            else:
                pred=float(r[f'{m}_{cp}']); eh_=ehist[m]
                sig=float(np.std(eh_)) if len(eh_)>=5 else math.sqrt(max(pred,1.0))
                worth={b:bprob(pred,sig,lo,hi) for b,(lo,hi) in branges}
            tot=sum(worth.values())
            if tot<=0: continue
            worth={b:v/tot for b,v in worth.items()}; pw=worth.get(winner,0.0)
            amax=max(worth,key=worth.get)
            ll=-math.log(max(pw,1e-6)); br=sum((worth[b]-(1.0 if b==winner else 0))**2 for b in worth)
            if m=='Market': phit=(amax==winner)
            else:
                rgw=parse_bucket(winner); phit=bool(rgw and rgw[0]<=pred<=(rgw[1] if rgw[1] is not None else 1e12))
            cpnl=0.0;cn=0;cw=0
            if m!='Market':
                for b,_ in branges:
                    pr=mkt.get(b)
                    if pr is None: continue
                    if worth.get(b,0)-pr>GAP:
                        cn+=1; won=1.0 if b==winner else 0.0; cpnl+=won-pr; cw+=int(won)
            records.append(dict(cp=cp,dur=dur,model=m,pw=pw,ll=ll,br=br,phit=int(phit),
                                amx=int(amax==winner),cpnl=cpnl,cn=cn,cw=cw))
            if m!='Market': ehist[m].append(actual-pred)
rec=pd.DataFrame(records)

def grid_for(dur,cp):
    g=[]
    for m in MODELS+['Market']:
        s=rec[(rec.cp==cp)&(rec.dur==dur)&(rec.model==m)]
        if not len(s): continue
        ntr=int(s.cn.sum())
        g.append({'model':m,'n':len(s),'bracket_hit%':round(100*s.phit.mean(),1),
                  'logloss':round(s.ll.mean(),3),'brier':round(s.br.mean(),3),'P_winner':round(s.pw.mean(),3),
                  'conv_PnL/auc':round(s.cpnl.mean(),3) if m!='Market' else '',
                  'conv_win%':round(100*s.cw.sum()/ntr,1) if (m!='Market' and ntr) else ''})
    return pd.DataFrame(g).sort_values('logloss')

blocks=[]
for dur,cp,label in [('7-day','T1d','7-DAY @ T-1d'),('7-day','T2d','7-DAY @ T-2d'),('2-day','T1d','2-DAY @ T-1d')]:
    g=grid_for(dur,cp)
    if not len(g): continue
    print(f"\n================= {label} (clean target) =================")
    print(g.to_string(index=False))
    blocks.append((label,g))

# ---- write to sheet ----
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc=build('sheets','v4',credentials=creds)
SID='1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'; TAB='_Backtest_Clean_Brackets'
meta=svc.spreadsheets().get(spreadsheetId=SID,fields='sheets(properties(title,sheetId))').execute()
if TAB not in [s['properties']['title'] for s in meta['sheets']]:
    svc.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':[{'addSheet':{'properties':{'title':TAB}}}]}).execute()
svc.spreadsheets().values().clear(spreadsheetId=SID,range=f'{TAB}!A1:Z200').execute()
vals=[['CLEAN backtest (X-API counts + noon-ET windows, current-structure auctions). Lower logloss/brier = better calibrated. conv_PnL = value-trade $ vs real prices. Market = the crowd baseline.']]
for label,g in blocks:
    vals.append([]); vals.append([label]); vals.append(list(g.columns))
    vals+= g.astype(str).values.tolist()
svc.spreadsheets().values().update(spreadsheetId=SID,range=f'{TAB}!A1',valueInputOption='RAW',body={'values':vals}).execute()
print(f"\nWrote grid to tab {TAB}")
print(f"https://docs.google.com/spreadsheets/d/{SID}/edit")
