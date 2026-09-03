# -*- coding: utf-8 -*-
"""Populate the user's existing 'Buy+Sell Pace' tab (april-23-25 pace+edge run) matching the
'SeeSaw Trade' headers + formulas, and copy that tab's cell FORMAT over. Surgical: writes only the
data rows (3+); leaves the user's header rows 1-2 alone."""
import os, glob, json, math, string, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; PMX=ROOT+"/_DataMetricPulls/pmxt_pulled"
OUT=ROOT+"/_DataMetricPulls/pacing_backtest/audit_out3"; ET=ZoneInfo('America/New_York'); con=duckdb.connect()
MON=['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'
SLUG='elon-musk-of-tweets-april-23-april-25'; s=int(pd.Timestamp(datetime(2026,4,23,12,tzinfo=ET)).timestamp()); e=int(pd.Timestamp(datetime(2026,4,25,12,tzinfo=ET)).timestamp())
def pbk(l):
    l=str(l).strip()
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),10**9)
    if '-' in l: a,b=l.split('-'); return (int(a),int(b))
    return (int(l),int(l))
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); M={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
    mo1=M[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in M: mo2=M[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
# tweets + priors
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms'); pts=(bf.ms.to_numpy()//1000).astype('int64'); c0=int(pts.min())
def obs(a,b): return int(np.searchsorted(pts,b)-np.searchsorted(pts,a))
def count_at(et_str):
    p=et_str.strip().split(); d=p[0].split('-'); tm=p[1].split(':')
    t=int(pd.Timestamp(datetime(2026,int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2]),tzinfo=ET)).timestamp())
    return int(np.searchsorted(pts,t)-np.searchsorted(pts,s)), t
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
pr=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    try: w=noon(a.auction_slug)
    except: continue
    if not 1.5<=(w[1]-w[0])/86400<=2.6 or w[1]>=s: continue
    pr.append(obs(w[0],w[1])/48)
rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; cur=[]
while d.timestamp()+48*3600<=s:
    ss=int(d.timestamp()); fnl=obs(ss,ss+48*3600)
    if fnl>=5: cur.append(np.array([obs(ss,ss+h*3600) for h in range(1,49)],float)/fnl)
    d=d+pd.Timedelta(days=1)
share=np.clip(np.median(np.vstack(cur),axis=0),1e-3,1.0)
def models(o,eh,rh,cp):
    kal=o+(rmean+Kk*(o/eh-rmean))*rh; acc=o/share[min(47,max(0,int(eh)-1))]; ens=(1-cp)*kal+cp*acc; cap=o+min((ens-o)/max(rh,.1),1.5*rmean)*rh
    return kal,acc,ens,cap
# pmxt quote
row=auc[auc.auction_slug==SLUG].iloc[0]; tok=row.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
fs=[]; tt=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
while tt<=end: fs+=glob.glob(PMX+f"/pmxt_tweets_{tt.strftime('%Y-%m-%dT%H')}*.parquet"); tt=tt+dt.timedelta(hours=1)
arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in sorted(set(fs)))+']'; t2l={str(v):k for k,v in tok.items()}; tl='('+','.join("'"+str(v)+"'" for v in tok.values())+')'
px=con.execute(f"""SELECT ts,CAST(asset_id AS VARCHAR) aid,best_bid,best_ask FROM read_parquet({arr},union_by_name=true) WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {tl} AND best_ask>0 AND best_ask<1 AND best_bid>0 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df(); px['lab']=px.aid.map(t2l)
B={l:{'ts':g.ts.to_numpy().astype('int64'),'bid':g.best_bid.to_numpy(float),'ask':g.best_ask.to_numpy(float)} for l,g in px.groupby('lab')}
def quote(lab,tms):
    d=B.get(lab)
    if not d: return '',''
    i=np.searchsorted(d['ts'],tms,'right')-1
    return (round(float(d['ask'][i]),3),round(float(d['bid'][i]),3)) if i>=0 else ('','')

tr=pd.read_csv(OUT+"/one_auction_trades_react.csv")
grid=[]
for i,r in tr.iterrows():
    R=i+3; cnt,t=count_at(r['et']); eh=max((t-s)/3600.0,0.5); rh=max(48-eh,0.1); cp=eh/48
    mo,da=r['et'][:5].split('-'); hh,mm,ssx=r['et'][6:].split(':'); mo,da,hh,mm,ssx=int(mo),int(da),int(hh),int(mm),int(ssx)
    date=f"{MON[mo]} {da}"; ap='AM' if hh<12 else 'PM'; h12=hh%12 or 12; tm=f"{h12}{ap} {mm} mins, {ssx} seconds"
    H=int(rh); Mn=int(round((rh-H)*60)); dur=f"{H} hrs, {Mn} mins"
    kal,acc,ens,cap=models(cnt,eh,rh,cp); pac=f"Kalman {kal:.0f} · Accrual {acc:.0f} · Ensemble {ens:.0f} · Ens+Cap1.5 {cap:.0f}"
    ask,bid=quote(r['bracket'],t*1000)
    grid.append([date,tm,dur,'',r['action'],r['bracket'],'',r['our_center'],cnt,'',r['price'],r['our_fair'],'',
        f"=L{R}-K{R}", f"=(L{R}-K{R})/(1-K{R})", f"=Q{R}*(L{R}-K{R})", f"=MIN(Config!$B$2*Config!$B$3*O{R},Config!$B$4)/K{R}", f"=Q{R}*K{R}",
        pac,ask,bid])
n=len(grid)
sh.spreadsheets().values().update(spreadsheetId=SEE,range="'Buy+Sell Pace'!A3",valueInputOption='USER_ENTERED',body={'values':grid}).execute()
# match formatting: copy SeeSaw Trade data-row format down + freeze + action colors
def gid(t):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
see_g=gid('SeeSaw Trade'); bsp_g=gid('Buy+Sell Pace'); reqs=[]
reqs.append({'copyPaste':{'source':{'sheetId':see_g,'startRowIndex':2,'endRowIndex':3,'startColumnIndex':0,'endColumnIndex':21},
    'destination':{'sheetId':bsp_g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':0,'endColumnIndex':21},'pasteType':'PASTE_FORMAT'}})
reqs.append({'updateSheetProperties':{'properties':{'sheetId':bsp_g,'gridProperties':{'frozenRowCount':2}},'fields':'gridProperties.frozenRowCount'}})
for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80}),("SELL-EARLY",{'red':0.98,'green':0.80,'blue':0.80}),("BUY-HOLD-PACE",{'red':0.80,'green':0.87,'blue':0.98})]:
    reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':bsp_g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':4,'endColumnIndex':5}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"DONE {n} trade rows into 'Buy+Sell Pace'. actions: {tr.action.value_counts().to_dict()}")
print("https://docs.google.com/spreadsheets/d/"+SEE+"/edit#gid="+str(bsp_g))
