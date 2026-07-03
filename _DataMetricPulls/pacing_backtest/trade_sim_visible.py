"""Trade-the-edge sim with FULL transparency: logs every trade + a step-by-step walkthrough
of one auction, written to Google Sheet tabs so the logic is auditable by hand."""
import sys, math, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ET = ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
BUY_GAP=0.05; GRID_MIN=30
MODELS=['Linear','CurBayes','M0','Decay','M4MMPP','Kalman']
WALK_MODEL='Kalman'   # which model to show the step-by-step for

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
    v=float(ps[i]); return v if 0<v<1 else None
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
    return max(0.0,1-ncdf(zl)) if hi is None else max(0.0,ncdf((hi+0.5-pred)/sig)-ncdf(zl))
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
    return {'Linear':Linear(o,eh,rh),'CurBayes':CurBayes(o,eh,rh,pt),'M0':M0(o,eh,rh,pt,pdur),
            'Decay':Decay(o,eh,rh,pwa),'M4MMPP':M4MMPP(o,eh,rh,prate),'Kalman':Kalman(o,eh,rh,prate)}[m]

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
TARGET=[x for x in sel if x['dur']=='7-day'][-1]['slug']   # walkthrough = last 7-day auction
print(f"auctions in sim: {len(sel)}   walkthrough auction: {TARGET}")

err_hist={m:[] for m in MODELS}; res=[]; trade_log=[]; walk=[]
for a in sel:
    ns,ne,winner=a['ns'],a['ne'],a['winner']
    priors=[p for p in sel if p['ne']<ns]
    pt=[p['actual'] for p in priors];pdur=[(p['ne']-p['ns'])/3600 for p in priors]
    prate=[p['actual']/((p['ne']-p['ns'])/3600) for p in priors if p['ne']>p['ns']]
    pwa=[(p['actual'],(p['ne']-p['ns'])/3600,(ns-p['ne'])/604800) for p in priors]
    sig={m:(float(np.std(err_hist[m])) if len(err_hist[m])>=5 else 15.0) for m in MODELS}
    tmin=min((price_idx[(a['slug'],b)][0][0] for b,_ in a['branges']),default=ns)
    tmax=max((price_idx[(a['slug'],b)][0][-1] for b,_ in a['branges']),default=ne)
    t0=max(ns,tmin);t1=min(ne,tmax)
    pos={m:{} for m in MODELS};pnl={m:0.0 for m in MODELS};ntr={m:0 for m in MODELS}
    t=t0
    while t<t1:
        o=obs(ns,t);eh=(t-ns)/3600;rh=(ne-t)/3600
        if eh>0.2:
            for m in MODELS:
                pred=predof(m,o,eh,rh,pt,pdur,pwa,prate)
                worth={b:bprob(pred,sig[m],lo,hi) for b,(lo,hi) in a['branges']}
                tot=sum(worth.values()) or 1; worth={b:v/tot for b,v in worth.items()}
                for b,_ in a['branges']:
                    pr=price_at(a['slug'],b,t)
                    if pr is None: continue
                    held=pos[m].get(b); action=''
                    if held is None and worth[b]-pr>BUY_GAP and pr>0.02:
                        pos[m][b]=pr; action='BUY'
                        trade_log.append([a['slug'],a['dur'],m,datetime.fromtimestamp(t,tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),b,'BUY',round(worth[b],3),round(pr,3),''])
                    elif held is not None and pr>=worth[b]:
                        pnl[m]+=pr-held;ntr[m]+=1;action='SELL'
                        trade_log.append([a['slug'],a['dur'],m,datetime.fromtimestamp(t,tz=timezone.utc).strftime('%Y-%m-%d %H:%M'),b,'SELL',round(worth[b],3),round(pr,3),round(pr-held,3)])
                        pos[m][b]=None
                    if a['slug']==TARGET and m==WALK_MODEL:
                        walk.append([datetime.fromtimestamp(t,tz=timezone.utc).strftime('%m-%d %H:%M'),o,round(pred,1),b,round(worth[b],3),round(pr,3),action,'HELD' if pos[m].get(b) is not None else '',round(pnl[m],3)])
        t+=GRID_MIN*60
    for m in MODELS:
        for b,entry in pos[m].items():
            if entry is not None:
                payoff=1.0 if b==winner else 0.0; pnl[m]+=payoff-entry; ntr[m]+=1
                trade_log.append([a['slug'],a['dur'],m,'RESOLUTION',b,'RESOLVE',round(payoff,3),round(entry,3),round(payoff-entry,3)])
    res.append(dict(slug=a['slug'],dur=a['dur'],winner=winner,actual=a['actual'],**{f'pnl_{m}':pnl[m] for m in MODELS},**{f'ntr_{m}':ntr[m] for m in MODELS}))
    tref=ne-86400;oref=obs(ns,tref);ehr=(tref-ns)/3600
    if ehr>0.2:
        for m in MODELS: err_hist[m].append(a['actual']-predof(m,oref,ehr,24.0,pt,pdur,pwa,prate))
R=pd.DataFrame(res)

# aggregate
agg=[]
for m in MODELS:
    s7=R[R.dur=='7-day'];s2=R[R.dur=='2-day']
    agg.append([m,round(s7[f'pnl_{m}'].mean(),3),round(s7[f'ntr_{m}'].mean(),1),round(s2[f'pnl_{m}'].mean(),3),round(s2[f'ntr_{m}'].mean(),1),round(R[f'pnl_{m}'].mean(),3)])
agg=sorted(agg,key=lambda x:-x[5])
print("\n".join(f"{r[0]:<10} 7d={r[1]:+.3f} 2d={r[3]:+.3f} all={r[5]:+.3f}" for r in agg))
print(f"\ntotal trades logged: {len(trade_log)}, walkthrough rows: {len(walk)}")

# ---- write to sheet ----
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(__import__('os').path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc=build('sheets','v4',credentials=creds); SID='1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'
def write_tab(tab, header, rows):
    meta=svc.spreadsheets().get(spreadsheetId=SID,fields='sheets(properties(title))').execute()
    if tab not in [s['properties']['title'] for s in meta['sheets']]:
        svc.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':[{'addSheet':{'properties':{'title':tab}}}]}).execute()
    svc.spreadsheets().values().clear(spreadsheetId=SID,range=f'{tab}!A1:Z50000').execute()
    svc.spreadsheets().values().update(spreadsheetId=SID,range=f'{tab}!A1',valueInputOption='RAW',body={'values':[header]+rows}).execute()
write_tab('_Trade_PnL',['model','7d_$/auc','7d_trades','2d_$/auc','2d_trades','ALL_$/auc'],[[*r] for r in agg])
write_tab('_Trade_Log',['auction','dur','model','time_utc','bracket','action','model_worth','market_price','pnl'],trade_log)
write_tab('_Trade_Walkthrough',['(auction '+TARGET+', model '+WALK_MODEL+')  time','tweets_so_far','model_pred','bracket','worth','price','action','position','cum_pnl'],walk)
print(f"\nWrote _Trade_PnL, _Trade_Log ({len(trade_log)} rows), _Trade_Walkthrough ({len(walk)} rows)")
print(f"https://docs.google.com/spreadsheets/d/{SID}/edit")
