"""Transparency: write (1) plain-English descriptions of all 10 pacing models, and
(2) ONE real auction run through every model at T-1d showing the actual numbers / formula
evaluation, so the operator can verify the math by hand. Two Google Sheet tabs."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8'); np.random.seed(42)
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON=ROOT/'_DataMetricPulls'/'canonical'; OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
post_ts=(bf.ms.to_numpy()//1000).astype('int64')
m_repost=(bf['type']=='repost').to_numpy(); m_quote=(bf['type']=='quote').to_numpy(); m_reply=(bf['type']=='reply').to_numpy()
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
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

# build selected 7-day auctions, pick a clean mid one with good priors
sel=[]
cur=auc[(auc.duration_type=='7-day')&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
for _,a in cur.iterrows():
    w=noonET(a.auction_slug,a['start_utc'].year)
    if not w: continue
    ns,ne=w
    if ns<int(pd.Timestamp('2025-09-05',tz='UTC').timestamp()): continue
    if (ne-ns)/3600<150 or (ne-ns)/3600>180: continue
    a_=obs(ns,ne)
    if a_<=0: continue
    sel.append(dict(slug=a.auction_slug,ns=ns,ne=ne,winner=a['winning_bucket'],actual=a_))
sel=sorted(sel,key=lambda x:x['ns'])
TARGET=[x for x in sel if 200<=x['actual']<=320 and len([p for p in sel if p['ne']<x['ns']])>=8][12]  # a typical one with priors
A=TARGET; ns,ne=A['ns'],A['ne']; total_h=(ne-ns)/3600; hr=24; eh=total_h-hr
cps=ns+int(eh*3600); o=obs(ns,cps); actual=A['actual']
priors=[p for p in sel if p['ne']<ns]
pt=[p['actual'] for p in priors]; pdur=[(p['ne']-p['ns'])/3600 for p in priors]
prate=[p['actual']/((p['ne']-p['ns'])/3600) for p in priors if p['ne']>p['ns']]
pwa=[(p['actual'],(p['ne']-p['ns'])/3600,(ns-p['ne'])/604800) for p in priors]
print(f"TARGET {A['slug']} | actual={actual} | observed@T-1d={o} | elapsed={eh:.0f}h remaining={hr}h | priors n={len(pt)} mean={np.mean(pt):.0f}")

# event times for Hawkes
lo=np.searchsorted(post_ts,ns); hi=np.searchsorted(post_ts,cps)
ev=((post_ts[lo:hi]-ns)/3600.0).tolist(); rp=m_repost[lo:hi]; qt=m_quote[lo:hi]

def fmt(x): return f"{x:.1f}"
rows=[]  # [model, what it uses, computation with numbers, prediction, abs_err]

# Linear
pred=o*(eh+hr)/eh
rows.append(['Linear','observed + elapsed time',f"{o} × {total_h:.0f}h ÷ {eh:.0f}h = keep the same pace to the end",fmt(pred),fmt(abs(pred-actual))])
# CurBayes
ec=min(0.99,max(0.001,eh/total_h)); op=o/ec; pm=float(np.mean(pt)); ps=max(1.0,float(np.std(pt,ddof=1))); ov=max(1.0,o*(1-ec)/(ec**2))
pp=1/ps**2; po=1/ov; cb=(pp*pm+po*op)/(pp+po)
rows.append(['CurBayes (deployed)','observed pace + history, precision-weighted',
   f"naive proj={op:.0f}, history avg={pm:.0f}±{ps:.0f}; blend by confidence → leans {'history' if pp>po else 'observed'}",fmt(cb),fmt(abs(cb-actual))])
# M0 Gamma-Poisson
a0=sum(pt); b0=sum(pdur); lam=(a0+o)/(b0+eh); m0=o+lam*hr
rows.append(['M0 Gamma-Poisson (Bayesian)','tweet RATE updated Bayesian-style',
   f"rate λ=(Σhist_tweets {a0:.0f}+{o})/(Σhist_hours {b0:.0f}+{eh:.0f})={lam:.2f}/h × {hr}h left = +{lam*hr:.0f}",fmt(m0),fmt(abs(m0-actual))])
# M1 Seasonal
hd=pd.to_datetime(post_ts[:hi],unit='s',utc=True).tz_convert('America/New_York')
cnts=pd.DataFrame({'dow':hd.dayofweek,'hour':hd.hour}).groupby(['dow','hour']).size(); span=max(1,(cps-post_ts[0])/86400)
sm={k:v/(span/7) for k,v in cnts.items()}; dflt=float(np.mean(prate))
er=0.0
for h in range(int(hr)):
    et2=pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert('America/New_York'); er+=sm.get((et2.dayofweek,et2.hour),dflt)
m1=o+er
rows.append(['M1 Seasonal','his hour-of-day × day-of-week rhythm',
   f"sum the expected tweets for each of the next {hr} clock-hours (knows sleep/wake) = +{er:.0f}",fmt(m1),fmt(abs(m1-actual))])
# Decay
eps=0.85; a0d=sum(t*eps**ag for t,_,ag in pwa); b0d=sum(d*eps**ag for _,d,ag in pwa) or 1; lamd=(a0d+o)/(b0d+eh); dec=o+lamd*hr
rows.append(['Decay (ε=0.85)','M0 but recent weeks count more',
   f"same as M0 but older weeks down-weighted ×0.85/week → λ={lamd:.2f}/h × {hr}h = +{lamd*hr:.0f}",fmt(dec),fmt(abs(dec-actual))])
# Hawkes fit
def nll(p,evs,T):
    mu,al,be=p
    if mu<=0 or al<0 or be<=0 or al>=be: return 1e10
    ll=0.0; ds=0.0; ptm=0.0
    for i,t in enumerate(evs):
        ds=ds*math.exp(-be*(t-ptm))+1.0 if i>0 else 0.0; inten=mu+al*ds
        if inten<=0: return 1e10
        ll+=math.log(inten); ptm=t
    integ=mu*T+sum((al/be)*(1-math.exp(-be*(T-t))) for t in evs); return -(ll-integ)
fit=None
if len(ev)>=5:
    r=minimize(nll,[len(ev)/eh*0.5,0.5,1.0],args=(ev,eh),method='Nelder-Mead',options={'maxiter':200,'xatol':1e-3,'fatol':1e-3})
    mu,al,be=r.x
    if mu>0 and 0<=al<be: fit=(mu,al,be)
def sim(mu,al,be,t0,t1,hist,n=50,amul=1.0):
    al*=amul; h=np.asarray(hist,float); A0=float(np.sum(np.exp(-be*(t0-h)))) if len(h) else 0.0; tot=[]
    for _ in range(n):
        Aa=A0; t=t0; c=0
        while True:
            lb=mu+al*Aa
            if lb<=0: break
            w=np.random.exponential(1.0/lb); t+=w
            if t>=t1: break
            Aa*=math.exp(-be*w)
            if np.random.random()<(mu+al*Aa)/lb: Aa+=1.0; c+=1
            if c>=5000: break
        tot.append(c)
    return float(np.mean(tot))
if fit:
    sc=sim(*fit,eh,eh+hr,ev); h2=o+sc; mu,al,be=fit
    rows.append(['M2 Hawkes','"tweets trigger more tweets" (self-exciting)',
      f"fit μ={mu:.2f},α={al:.2f},β={be:.2f}; simulate the cascade {hr}h forward = +{sc:.0f}",fmt(h2),fmt(abs(h2-actual))])
    mw=float(np.mean(np.where(rp,1.2,np.where(qt,0.7,1.0)))); sc3=sim(*fit,eh,eh+hr,ev,n=30,amul=mw); h3=o+sc3
    rows.append(['M3 Marked Hawkes','Hawkes, but reposts excite more than quotes',
      f"same fit, α scaled ×{mw:.2f} by tweet-type mix; simulate = +{sc3:.0f}",fmt(h3),fmt(abs(h3-actual))])
else:
    rows.append(['M2 Hawkes','self-exciting','too few events to fit → fell back to Linear',fmt(o*(eh+hr)/eh),'-'])
    rows.append(['M3 Marked Hawkes','marked self-exciting','too few events → fell back',fmt(o*(eh+hr)/eh),'-'])
# M4 MMPP
cr=o/eh; mr=float(np.mean(prate)); m4=o+(0.5*cr+0.5*mr)*hr
rows.append(['M4 MMPP (regime)','blend "current pace" with "his usual pace"',
   f"current={cr:.2f}/h, usual={mr:.2f}/h → 50/50 blend ={0.5*cr+0.5*mr:.2f}/h × {hr}h = +{(0.5*cr+0.5*mr)*hr:.0f}",fmt(m4),fmt(abs(m4-actual))])
# M5 NegBin
me=float(np.mean(pt)); pf=(o/eh)/(me/total_h) if me>0 else 1; m5=me*(0.7+0.3*pf)
rows.append(['M5 NegBin','history average, nudged by current pace',
   f"history avg={me:.0f}, pace factor={pf:.2f} → {me:.0f}×(0.7+0.3×{pf:.2f})",fmt(m5),fmt(abs(m5-actual))])
# Kalman
x=float(np.mean(prate)); P=float(np.var(prate))+0.01; R=max(0.1,P*0.5); K=(P+0.01)/(P+0.01+R); z=o/eh; xn=x+K*(z-x); km=o+xn*hr
rows.append(['Kalman','smart running-average of his tweet rate',
   f"prior rate={x:.2f}/h, observed={z:.2f}/h, trust K={K:.2f} → updated={xn:.2f}/h × {hr}h = +{xn*hr:.0f}",fmt(km),fmt(abs(km-actual))])

# ---- descriptions tab ----
DESC=[
 ['Linear','Naive extrapolation','Whatever his pace has been so far, assume it continues exactly to the end. Dumbest baseline.'],
 ['CurBayes','Bayesian blend (deployed)','Mix two guesses: "his pace right now" and "his historical average," weighting whichever vAI is more confident in. This is what the dashboard currently uses.'],
 ['M0 Gamma-Poisson','Bayesian (conjugate)','Treats his tweeting as a random rate and updates that rate the textbook Bayesian way as evidence comes in. Classic, clean.'],
 ['M1 Seasonal','Time-of-day rhythm','Knows he sleeps 3-9am ET and blasts late-night, so it does not spread tweets evenly, it counts the actual clock-hours left.'],
 ['Decay','Bayesian + recency','Same as M0 but recent weeks count more than old ones (his behavior drifts), older weeks fade ×0.85 each week.'],
 ['M2 Hawkes','Self-exciting process','"A tweet makes the next tweet more likely" (fire catches fire). Fits how contagious his bursts are, then simulates them forward.'],
 ['M3 Marked Hawkes','Self-exciting + type','Same as Hawkes, but a repost is treated as more contagious than a quote. Adds tweet-type to the cascade.'],
 ['M4 MMPP','Regime switch (simplified)','He has a "quiet mode" and a "manic mode." This blends his current pace 50/50 with his usual pace to mean-revert.'],
 ['M5 NegBin','Fat-tailed average','Mostly his historical average, widened to allow for a wild week, nudged up/down by whether he is currently ahead of pace.'],
 ['Kalman','Smart running average','A self-correcting estimate of his tweet rate: starts at his usual rate, then nudges toward what it is observing, by how much it trusts the new data.'],
]

from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc=build('sheets','v4',credentials=creds); SID='1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'
def wtab(tab,vals):
    meta=svc.spreadsheets().get(spreadsheetId=SID,fields='sheets(properties(title))').execute()
    if tab not in [s['properties']['title'] for s in meta['sheets']]:
        svc.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':[{'addSheet':{'properties':{'title':tab}}}]}).execute()
    svc.spreadsheets().values().clear(spreadsheetId=SID,range=f'{tab}!A1:Z100').execute()
    svc.spreadsheets().values().update(spreadsheetId=SID,range=f'{tab}!A1',valueInputOption='RAW',body={'values':vals}).execute()
wtab('_Models_Explained',[['The 10 pacing models — what each one is and how it works (plain English)'],
    ['Model','Type','How it works']]+DESC)
we=[[f'WORKED EXAMPLE — one real auction run through all 10 models (verify the math yourself)'],
    ['Auction',A['slug']],['Window (noon ET → noon ET)',f"{datetime.utcfromtimestamp(ns)} → {datetime.utcfromtimestamp(ne)} UTC"],
    ['Checkpoint','T-1d (24h before close)'],['Tweets observed by then',o],['Hours elapsed',f"{eh:.0f}"],['Hours remaining',hr],
    ['Prior auctions used',f"{len(pt)} (their final counts avg {np.mean(pt):.0f}, range {min(pt)}-{max(pt)})"],
    ['ACTUAL final count',actual],['Winning bracket',A['winner']],[''],
    ['Model','What it uses','How it computed its number (real values)','Prediction','Abs error']]+rows
wtab('_Worked_Example',we)
print("\n=== worked example (also written to sheet) ===")
print(f"{'Model':<22}{'pred':>7}{'err':>7}")
for r in rows: print(f"{r[0]:<22}{r[3]:>7}{r[4]:>7}")
print(f"\nactual={actual}. Wrote _Models_Explained + _Worked_Example.")
print(f"https://docs.google.com/spreadsheets/d/{SID}/edit")
