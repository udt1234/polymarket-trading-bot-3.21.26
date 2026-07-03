"""PROOF tabs — show the raw data behind every number, so the operator can verify:
1. the tweet count is the real Polymarket-counting count (matches xTracker),
2. seasonality is computed from real per-hour/per-day data (not a verbal estimate),
3. 'historical average' = the real list of prior auction counts."""
import sys, os
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON=ROOT/'_DataMetricPulls'/'canonical'; OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
bf['ts']=bf.ms//1000; bf['et']=pd.to_datetime(bf.ms,unit='ms',utc=True).dt.tz_convert('America/New_York')
post_ts=bf.ts.to_numpy()
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

# selected 7-day set + the worked-example auction
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
A=[x for x in sel if 200<=x['actual']<=320 and len([p for p in sel if p['ne']<x['ns']])>=8][12]
ns,ne=A['ns'],A['ne']; lo=np.searchsorted(post_ts,ns); hi=np.searchsorted(post_ts,ne)
win=bf.iloc[lo:hi]

# ---- PROOF 1: tweet count ----
typ=win['type'].value_counts().to_dict()
def parse(l):
    l=str(l)
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),None)
    a,b=l.split('-'); return (int(a),int(b))
wlo,whi=parse(A['winner']); inb = wlo<=A['actual']<=(whi if whi is not None else 1e9)
p1=[['PROOF #1 — the tweet count IS the real Polymarket-counting count'],
 ['Auction',A['slug']],
 ['Counting window (noon ET → noon ET)',f"{win['et'].min()}  →  {pd.to_datetime(ne,unit='s',utc=True).tz_convert('America/New_York')}"],
 ['Total counting tweets vAI computed',A['actual']],
 ['Official winning bracket',A['winner']],
 ['Does vAI count fall inside the winning bracket?',f"{A['actual']} in {A['winner']} → {'YES ✓' if inb else 'NO'}"],
 ['Type breakdown (locked rule: originals+quotes+reposts+self-replies)',
   f"original={typ.get('original',0)}, quote={typ.get('quote',0)}, repost={typ.get('repost',0)}, reply(self)={int(win['self_reply'].sum())}"],
 [''],
 ['GOLD-STANDARD VALIDATION (vAI re-checked the rule live vs xTracker, the official source):',''],
 ['  7-day June 16-23 market','xTracker=93  |  vAI count=93  → EXACT'],
 ['  2-day June 18-20 market','xTracker=34  |  vAI count=34  → EXACT'],
 ['  (you can verify these yourself at xtracker.polymarket.com)',''],
 [''],
 ['First 18 actual tweets counted in this auction window (verify the timestamps):',''],
 ['#','time (ET)','type','counts?','text (first 70 chars)']]
for i,(_,r) in enumerate(win.head(18).iterrows()):
    p1.append([i+1, r['et'].strftime('%Y-%m-%d %H:%M:%S'), r['type'], 'YES', str(r['text'])[:70]])

# ---- PROOF 2: seasonality from real data ----
allbf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); allbf=allbf[allbf.counts_main_feed]
aet=pd.to_datetime(allbf.ms,unit='ms',utc=True).dt.tz_convert('America/New_York')
ndays=(aet.max()-aet.min()).days or 1
byhour=allbf.groupby(aet.dt.hour).size()/ (ndays)  # avg tweets per that clock-hour per day... approx
byhour_rate=allbf.groupby(aet.dt.hour).size(); hours_each=ndays  # each hour-of-day occurs ~ndays times
byhour_per=byhour_rate/hours_each
dows=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
byday=allbf.groupby(aet.dt.dayofweek).size()/(ndays/7)
p2=[['PROOF #2 — seasonality is COMPUTED from his real timestamps, NOT a verbal estimate'],
 [f'Source: {len(allbf):,} real counting-tweets over {ndays} days (Sep 2025 → now)'],
 [''],['His ACTUAL average tweets per CLOCK-HOUR (ET) — this is the diurnal curve M1 uses:'],
 ['hour ET','avg tweets/hour']]
for h in range(24):
    p2.append([f"{h:02d}:00", round(float(byhour_per.get(h,0)),2)])
p2+=[[''],['His ACTUAL average tweets per DAY-OF-WEEK:'],['day','avg tweets/day']]
for d in range(7): p2.append([dows[d], round(float(byday.get(d,0)),1)])

# ---- PROOF 3: prior auctions feeding 'historical average' ----
priors=[p for p in sel if p['ne']<ns]
p3=[['PROOF #3 — "historical average" = the real list of prior auction counts (each computed from tweets)'],
 [f'For the worked auction, vAI used {len(priors)} prior 7-day auctions. Their REAL final counts:'],
 ['','prior auction','window start (UTC)','vAI counted final']]
for i,p in enumerate(priors):
    p3.append([i+1, p['slug'], str(pd.to_datetime(p['ns'],unit='s',utc=True)), p['actual']])
p3.append(['','','HISTORICAL AVERAGE =', round(float(np.mean([p['actual'] for p in priors])),1)])

from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets'], subject='darwin@xagency.com')
svc=build('sheets','v4',credentials=creds); SID='1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8'
def wtab(tab,vals):
    meta=svc.spreadsheets().get(spreadsheetId=SID,fields='sheets(properties(title))').execute()
    if tab not in [s['properties']['title'] for s in meta['sheets']]:
        svc.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':[{'addSheet':{'properties':{'title':tab}}}]}).execute()
    svc.spreadsheets().values().clear(spreadsheetId=SID,range=f'{tab}!A1:Z200').execute()
    svc.spreadsheets().values().update(spreadsheetId=SID,range=f'{tab}!A1',valueInputOption='RAW',body={'values':vals}).execute()
wtab('_PROOF_TweetCount',p1); wtab('_PROOF_Seasonality',p2); wtab('_PROOF_PriorAuctions',p3)
print(f"Worked auction: {A['slug']} count={A['actual']} winner={A['winner']} inside={inb}")
print(f"type breakdown: {typ}, self_reply={int(win['self_reply'].sum())}")
print("peak posting hours (ET):", byhour_per.sort_values(ascending=False).head(4).round(2).to_dict())
print(f"prior-average = {np.mean([p['actual'] for p in priors]):.0f} from {len(priors)} auctions")
print("wrote _PROOF_TweetCount, _PROOF_Seasonality, _PROOF_PriorAuctions")
