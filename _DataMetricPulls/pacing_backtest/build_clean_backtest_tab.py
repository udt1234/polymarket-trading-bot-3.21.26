# -*- coding: utf-8 -*-
"""Write the FULL clean sweep (all fully-covered auctions, BASE strategy, trade-by-trade) into the
'New_Backtest_Clean_7.13.2026' tab, matching its headers. Running P&L is cumulative across the whole
sweep so it ends at the pooled total. Re-runs each auction + loads its prices for the audit columns."""
import subprocess, sys, os, glob, json, math, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
from google.oauth2 import service_account
from googleapiclient.discovery import build
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; PMX=ROOT+"/_DataMetricPulls/pmxt_pulled"
OUT=ROOT+"/_DataMetricPulls/pacing_backtest/audit_out3"; HERE=os.path.dirname(os.path.abspath(__file__)); ET=ZoneInfo('America/New_York'); con=duckdb.connect(); MON=['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
def pbk(l):
    l=str(l).strip()
    if l.startswith('<'): return (0,int(l[1:])-1)
    if l.endswith('+'): return (int(l[:-1]),10**9)
    if '-' in l: a,b=l.split('-'); return (int(a),int(b))
    return (int(l),int(l))
def bmid(l):
    lo,hi=pbk(l); return lo+12.0 if hi>=10**9 else ((hi+1)/2.0 if lo==0 else (lo+hi)/2.0)
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); Mm={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
    mo1=Mm[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in Mm: mo2=Mm[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms'); pts=(bf.ms.to_numpy()//1000).astype('int64'); c0=int(pts.min())
def obs(a,b): return int(np.searchsorted(pts,b)-np.searchsorted(pts,a))
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
allA=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    try: w=noon(a.auction_slug)
    except: continue
    if not 1.5<=(w[1]-w[0])/86400<=2.6: continue
    allA.append({'s':w[0],'e':w[1],'final':obs(w[0],w[1])})
def priors_for(s):
    pr=[a['final']/48 for a in allA if a['e']<s]; rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; cur=[]
    while d.timestamp()+48*3600<=s:
        ss=int(d.timestamp()); f=obs(ss,ss+48*3600)
        if f>=5: cur.append(np.array([obs(ss,ss+h*3600) for h in range(1,49)],float)/f)
        d=d+pd.Timedelta(days=1)
    return rmean,Kk,(np.clip(np.median(np.vstack(cur),axis=0),1e-3,1.0) if cur else np.ones(48))
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(PMX+f"/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))
au=pd.read_csv(OUT+"/clean_sweep.csv"); SLUGS=['elon-musk-of-tweets-'+a for a in au.auction]
print(f"building {len(SLUGS)} auctions into '{TAB}'",flush=True)
def process(slug):
    s,e=noon(slug); rmean,Kk,share=priors_for(s)
    def models(o,eh,rh,cp):
        kal=o+(rmean+Kk*(o/eh-rmean))*rh; acc=o/share[min(47,max(0,int(eh)-1))]; ens=(1-cp)*kal+cp*acc; cap=o+min((ens-o)/max(rh,.1),1.5*rmean)*rh
        return kal,acc,ens,cap
    r=auc[auc.auction_slug==slug].iloc[0]; tok=r.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    fs=pmxt_files(s,e); arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'; t2l={str(v):k for k,v in tok.items()}; tl='('+','.join("'"+str(v)+"'" for v in tok.values())+')'
    px=con.execute(f"""SELECT ts,CAST(asset_id AS VARCHAR) aid,best_bid,best_ask FROM read_parquet({arr},union_by_name=true) WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {tl} AND best_ask>0 AND best_ask<1 AND best_bid>0 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df(); px['lab']=px.aid.map(t2l)
    Bk={l:{'ts':g.ts.to_numpy().astype('int64'),'bid':g.best_bid.to_numpy(float),'ask':g.best_ask.to_numpy(float),'mid':((g.best_bid+g.best_ask)/2).to_numpy(float)} for l,g in px.groupby('lab')}
    def q(l,tms,k):
        d=Bk.get(l)
        if not d: return ''
        i=np.searchsorted(d['ts'],tms,'right')-1; return round(float(d[k][i]),3) if i>=0 else ''
    def pp(tms):
        num=den=0.0
        for l,d in Bk.items():
            i=np.searchsorted(d['ts'],tms,'right')-1
            if i>=0: m=d['mid'][i]; num+=m*bmid(l); den+=m
        return round(num/den,1) if den>0 else ''
    env=dict(os.environ,AUCTION=slug); env.pop('REACT6H',None); env.pop('PACE_EDGE',None)
    subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    tr=pd.read_csv(OUT+"/one_auction_trades.csv")
    rows=[]
    for _,tt in tr.iterrows():
        et=tt['et']; p=et.split(); d=p[0].split('-'); tm=p[1].split(':'); mo,da,hh,mm,ssx=int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2])
        tms=int(pd.Timestamp(datetime(2026,mo,da,hh,mm,ssx,tzinfo=ET)).timestamp()); cnt=int(np.searchsorted(pts,tms)-np.searchsorted(pts,s))
        eh=max((tms-s)/3600.0,0.5); rh=max(48-eh,0.1); cp=eh/48; kal,acc,ens,cap=models(cnt,eh,rh,cp)
        date=f"{MON[mo]} {da}"; ap='AM' if hh<12 else 'PM'; h12=hh%12 or 12; tmv=f"{h12}{ap} {mm} mins, {ssx} seconds"
        H=int(rh); Mn=int(round((rh-H)*60));
        if Mn>=60: H+=1; Mn=0
        rows.append({'date':date,'tm':tmv,'dur':f"{H} hrs, {Mn} mins",'pac':f"Kalman {kal:.0f} · Accrual {acc:.0f} · Ensemble {ens:.0f} · Ens+Cap1.5 {cap:.0f}",
            'cnt':cnt,'ctr':tt['our_center'],'pp':pp(tms*1000),'act':tt['action'],'brk':tt['bracket'],'price':tt['price'],'fair':tt['our_fair'],
            'ask':q(tt['bracket'],tms*1000,'ask'),'bid':q(tt['bracket'],tms*1000,'bid'),'rpnl':tt['rpnl'],'hold':"Yes" if tt['held'] else "No"})
    return rows
grid=[]; R=3
for slug in SLUGS:
    for x in process(slug):
        res=(x['act']=='RESOLUTION')
        fQ,fR,fS,fT,fU=('','','','','') if res else (f"=O{R}-N{R}", f"=(O{R}-N{R})/(1-N{R})", f"=T{R}*(O{R}-N{R})", f"=MIN(Config!$B$2*Config!$B$3*R{R},Config!$B$4)/N{R}", f"=T{R}*N{R}")
        grid.append([x['date'],x['tm'],x['dur'],'',x['pac'],x['cnt'],'',x['ctr'],x['pp'],'',x['act'],x['brk'],'',x['price'],x['fair'],'',fQ,fR,fS,fT,fU,x['ask'],x['bid'],x['rpnl'],f"=SUM($X$3:X{R})","Yes" if x['hold']=="Yes" else "No"])
        R+=1
    print(f"  {slug.replace('elon-musk-of-tweets-','')}: total rows so far {len(grid)}",flush=True)
n=len(grid)
sh.spreadsheets().values().clear(spreadsheetId=SEE,range=f"'{TAB}'!A3:Z10000").execute()
sh.spreadsheets().values().update(spreadsheetId=SEE,range=f"'{TAB}'!A3",valueInputOption='USER_ENTERED',body={'values':grid}).execute()
sh.spreadsheets().values().update(spreadsheetId=SEE,range=f"'{TAB}'!A3:A{n+2}",valueInputOption='RAW',body={'values':[[g[0]] for g in grid]}).execute()
def gid(t):
    for x in sh.spreadsheets().get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
g=gid(TAB); reqs=[]
def cp(src,dst): return {'copyPaste':{'source':{'sheetId':gid('Buy+Sell Pace'),'startRowIndex':2,'endRowIndex':3,'startColumnIndex':src,'endColumnIndex':src+1},'destination':{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':dst,'endColumnIndex':dst+1},'pasteType':'PASTE_FORMAT'}}
for c in [7,8,13,14,16,17,18,19,20,23,24]: reqs.append(cp(c,c))   # copy Buy+Sell Pace's number formats for these cols
reqs.append({'updateSheetProperties':{'properties':{'sheetId':g,'gridProperties':{'frozenRowCount':2}},'fields':'gridProperties.frozenRowCount'}})
LOW={'red':0.87,'green':0.93,'blue':0.99}; MID={'red':0.64,'green':0.80,'blue':0.93}; HIGH={'red':0.40,'green':0.61,'blue':0.84}
def rng(c): return [{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}]
for c in (7,8):
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng(c),'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'40'}]},'format':{'backgroundColor':LOW}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng(c),'booleanRule':{'condition':{'type':'NUMBER_BETWEEN','values':[{'userEnteredValue':'40'},{'userEnteredValue':'64'}]},'format':{'backgroundColor':MID}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng(c),'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'64'}]},'format':{'backgroundColor':HIGH}}}}})
for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80}),("SELL-EARLY",{'red':0.98,'green':0.80,'blue':0.80}),("BUY-HOLD-PACE",{'red':0.80,'green':0.87,'blue':0.98}),("RESOLUTION",{'red':0.85,'green':0.85,'blue':0.85})]:
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':[{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':10,'endColumnIndex':11}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}}}})
sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"DONE. {n} trade rows across {len(SLUGS)} auctions. pooled realized+settle = sum of Realized P&L column.",flush=True)
