# -*- coding: utf-8 -*-
"""RECOVERY + clean build of the pace-shootout block on New_Backtest_Clean_7.13.2026.
The tab's tail shifted (user inserted cols) mid-operation, misaligning my earlier writes. This anchors
the block to the user's REAL last column (the 'Hold?' column, found by its row-2 note), wipes only the
region to the RIGHT of it, restores the Hold? header, and writes the FULL 10-col block in one shot:
Kalman, AccrualCurve, Ensemble, Ens+Cap1.5(LOCKED), Hawkes, Particle Filter, Finish Line, Kalman+Sleep,
Actual final, Market(Poly Pace) -- each model's projected FINAL count per row -- plus a legend."""
import subprocess, sys, os, math, glob
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
sys.stdout.reconfigure(encoding='utf-8'); rng=np.random.default_rng(7)
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; HERE=os.path.dirname(os.path.abspath(__file__)); OUT=HERE+"/audit_out3"; ET=ZoneInfo('America/New_York')
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
svc=build('sheets','v4',credentials=creds); sh=svc.spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
def A1(i):
    s=''; i+=1
    while i>0: i,r=divmod(i-1,26); s=chr(65+r)+s
    return s
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); hd_all=pd.to_datetime(pts,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
def diurnal_mult(before_s):
    h=hd_all[pts<before_s]
    if len(h)<240: return np.ones(24)
    m=np.array([np.sum(h==hh) for hh in range(24)],float); return m/m.mean() if m.mean()>0 else np.ones(24)
def eff_hours(t0,t1,mult):
    n=int((t1-t0)/3600)
    if n<=0: return 0.0
    hrs=pd.to_datetime(t0+np.arange(n)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy(); return float(np.sum(mult[hrs]))
def kblend(obs_rate,priors):
    if not priors: return obs_rate
    x=float(np.mean(priors));P=float(np.var(priors))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5)); return x+K*(obs_rate-x)
def hawkes_intensity(evt,now,mu,alpha,beta):
    it=mu
    for t in evt:
        if t<now: it+=alpha*math.exp(-beta*(now-t))
    return it
def fit_hawkes(hc):
    if len(hc)<6: return 0.5,0.8,1.2
    c=[h['count'] for h in hc]; mr=sum(c)/len(c) if c else 0.5
    bp=sum(1 for i in range(1,len(c)) if c[i]>0 and c[i-1]>0); clus=bp/max(len(c)-1,1)
    thr=mr*1.5; ch=mx=0
    for x in c:
        if x>thr: ch+=1; mx=max(mx,ch)
        else: ch=0
    return max(mr*0.3,0.1),min(clus*1.5,0.95),max(min(1.0/max(mx,1),3.0),0.3)
def hawkes_pace(hc,rem_h,run,mu,alpha,beta):
    if not hc or rem_h<=0: return float(run)
    evt=[]; t=0.0
    for h in hc:
        for _ in range(int(h['count'])): evt.append(t+0.5)
        t+=1.0
    now=t; proj=float(run)
    for ha in range(rem_h):
        ct=now+ha; it=hawkes_intensity(evt,ct,mu,alpha,beta); proj+=max(it,0)
        if it>0.1: evt.append(ct+0.5)
    return proj
def hour_counts(s,cps):
    n=int((cps-s)/3600)
    if n<=0: return np.array([]),np.array([])
    return np.array([obs(s+h*3600,s+(h+1)*3600) for h in range(n)]),np.array([pd.Timestamp(s+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(n)])
def pf_forecast(s,cps,e,prior_rate,mult):
    M=500; oc,oh=hour_counts(s,cps); lam=rng.lognormal(math.log(max(prior_rate,0.2)),0.6,M)
    for n,H in zip(oc,oh):
        lam*=np.exp(rng.normal(0,0.12,M)); mu=np.maximum(lam*mult[H],1e-4); logw=n*np.log(mu)-mu
        w=np.exp(logw-logw.max()); w/=w.sum(); idx=rng.choice(M,M,p=w); lam=lam[idx]*np.exp(rng.normal(0,0.03,M))
    rem=[pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(int((e-cps)/3600))]
    rm=np.array([mult[H] for H in rem]).sum() if rem else 0.0; o=obs(s,cps)
    return float(np.mean(o+rng.poisson(np.clip(lam*rm,0,1e4))))
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
allA=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    try: w=noon(a.auction_slug)
    except: continue
    if 1.5<=(w[1]-w[0])/86400<=2.6: allA.append({'s':w[0],'e':w[1]})
def priors(s,mult):
    p2=[a for a in allA if a['e']<s]
    rmean=float(np.mean([obs(a['s'],a['e'])/((a['e']-a['s'])/3600) for a in p2])) if p2 else 40.0
    peff=[obs(a['s'],a['e'])/eff_hours(a['s'],a['e'],mult) for a in p2 if eff_hours(a['s'],a['e'],mult)>0]
    return rmean,peff
# ---- compute per-row models (re-run auctions, tab order) ----
audf=pd.read_csv(OUT+"/clean_sweep.csv"); SLUGS=['elon-musk-of-tweets-'+a for a in audf.auction]
seq=[]
for slug in SLUGS:
    s,e=noon(slug); total=(e-s)/3600.0; mult=diurnal_mult(s); rmean,peff=priors(s,mult); finalc=obs(s,e)
    env=dict(os.environ,AUCTION=slug); env.pop('REACT6H',None); env.pop('PACE_EDGE',None)
    subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    tr=pd.read_csv(OUT+"/one_auction_trades.csv")
    for _,t in tr.iterrows():
        p=str(t['et']).split(); d=p[0].split('-'); tm=p[1].split(':'); mo,da,hh,mm,ss=int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2])
        tms=int(pd.Timestamp(datetime(2026,mo,da,hh,mm,ss,tzinfo=ET)).timestamp()); o=obs(s,tms); eh=(tms-s)/3600.0; rh=max(total-eh,0.0)
        hc=[{'count':obs(s+h*3600,s+(h+1)*3600)} for h in range(int(eh))]; mu,al,be=fit_hawkes(hc)
        haw=hawkes_pace(hc,int(round(rh)),o,mu,al,be); pf=pf_forecast(s,tms,e,rmean,mult)
        fin=o+(obs(max(s,tms-6*3600),tms)/6.0)*rh
        ks=o+kblend(o/max(eff_hours(s,tms,mult),0.1),peff)*eff_hours(tms,e,mult)
        seq.append([t.get('kal',''),t.get('acc',''),t.get('ens',''),t['our_center'],round(haw,1),round(pf,1),round(fin,1),round(ks,1),finalc,
                    str(t['action']),str(t['bracket'])])
    print(f"  {slug.replace('elon-musk-of-tweets-','')}: rows {len(seq)}",flush=True)
n=len(seq)
# ---- find the user's REAL last column via the Hold? row-2 note; get row count; market col J; alignment cols ----
meta=sh.get(spreadsheetId=SEE).execute(); sheet=[x for x in meta['sheets'] if x['properties']['title']==TAB][0]; g=sheet['properties']['sheetId']
r2=(sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!A2:BB2").execute().get('values',[[]]) or [[]])[0]
hold_idx=next((i for i,v in enumerate(r2) if isinstance(v,str) and 'BUY-HOLD-PACE' in v), 26)
START=hold_idx+2
def colvals(letter): return [ (rr[0] if rr else '') for rr in sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!{letter}3:{letter}{n+2}",valueRenderOption='UNFORMATTED_VALUE').execute().get('values',[]) ]
G=colvals('G'); I=colvals('I'); K=colvals('K'); J=colvals('J')
for L in (G,I,K,J): L+=['']*(n-len(L))
misc=sum(1 for i in range(n) if not (isinstance(I[i],(int,float)) and abs(float(I[i])-float(seq[i][3]))<=0.15))
print(f"Hold? col = {A1(hold_idx)} | block starts {A1(START)} | our_center(I) mismatches={misc}")
if misc: print("ABORT: pace not aligned to live col I"); sys.exit(1)
def num(x):
    try: return float(x)
    except: return None
# ---- STEP 1: expand grid + unmerge my old row-1 banner merges (>= hold_idx) ----
u=[{'updateSheetProperties':{'properties':{'sheetId':g,'gridProperties':{'columnCount':52}},'fields':'gridProperties.columnCount'}}]
for m in sheet.get('merges',[]):
    if m.get('startRowIndex')==0 and m.get('startColumnIndex',0)>=hold_idx:
        u.append({'unmergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':m['startColumnIndex'],'endColumnIndex':m['endColumnIndex']}}})
sh.batchUpdate(spreadsheetId=SEE,body={'requests':u}).execute()
# ---- STEP 2: wipe everything to the RIGHT of Hold? (my corruption only; never touches user cols) ----
sh.values().clear(spreadsheetId=SEE,range=f"'{TAB}'!{A1(hold_idx+1)}1:{A1(50)}{n+2}").execute()
# ---- STEP 3: write block (values+headers+banner), legend, restore Hold? header -- one batch ----
block=[[seq[i][0],seq[i][1],seq[i][2],seq[i][3],seq[i][4],seq[i][5],seq[i][6],seq[i][7],seq[i][8],(num(J[i]) if num(J[i]) is not None else '')] for i in range(n)]
hdr=['Kalman','AccrualCurve','Ensemble','Ens+Cap1.5 (LOCKED)','Hawkes','Particle Filter','Finish Line','Kalman+Sleep','Actual final','Market (Poly Pace)']
banner=["PACING MODEL SHOOTOUT: each model's projected FINAL count at this row's moment. Ens+Cap1.5 = LOCKED 'Our Pace'. Compare each vs Actual final (truth) and Market (what the crowd paced)."]
LEGx=START+11
legend=[['Pacing model','What it is / does it overshoot?'],
 ['Kalman','Prior avg rate blended with observed rate, extrapolated to 48h. Overshoots early on bursts.'],
 ['AccrualCurve','Current count / historical share landed by this hour. WORST early overshoot (tiny denominator).'],
 ['Ensemble','Time-weighted Kalman(early)+Accrual(late). Inherits the early overshoot.'],
 ['Ens+Cap1.5 (LOCKED)','Ensemble with go-forward rate capped at 1.5x baseline. Still overshoots early; = Our Pace.'],
 ['Hawkes','Self-exciting burst model (each tweet lifts the next). Best fit here (lowest error, least bias).'],
 ['Particle Filter','Poisson particle cloud x diurnal (sleep) multiplier. Does NOT extrapolate through the 4-9am dead-zone.'],
 ['Finish Line','Current count + (last-6h rate x remaining). Recent-rate only, no long extrapolation.'],
 ['Kalman+Sleep','Kalman over SLEEP-ADJUSTED remaining hours. Built to stop night-burst overshoot.'],
 ['Actual final','The tweet count the auction actually settled at (truth).'],
 ['Market (Poly Pace)','The crowd\'s price-weighted implied final count (= the Poly Pace column). The benchmark to align to.']]
sh.values().batchUpdate(spreadsheetId=SEE,body={'valueInputOption':'RAW','data':[
    {'range':f"'{TAB}'!{A1(START)}3",'values':block},
    {'range':f"'{TAB}'!{A1(START)}2",'values':[hdr]},
    {'range':f"'{TAB}'!{A1(START)}1",'values':[banner]},
    {'range':f"'{TAB}'!{A1(LEGx)}2",'values':legend},
    {'range':f"'{TAB}'!{A1(hold_idx)}1",'values':[['Hold?']]},
]}).execute()
# ---- STEP 4: formatting ----
LOW={'red':0.87,'green':0.93,'blue':0.99}; MID={'red':0.64,'green':0.80,'blue':0.93}; HIGH={'red':0.40,'green':0.61,'blue':0.84}
BE=START+10  # block end (exclusive)
def rng_(c): return [{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}]
reqs=[{'repeatCell':{'range':{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':START,'endColumnIndex':BE},'cell':{'userEnteredFormat':{'numberFormat':{'type':'NUMBER','pattern':'0'}}},'fields':'userEnteredFormat.numberFormat'}}]
for c in range(START,BE):
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'40'}]},'format':{'backgroundColor':LOW}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_BETWEEN','values':[{'userEnteredValue':'40'},{'userEnteredValue':'64'}]},'format':{'backgroundColor':MID}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'64'}]},'format':{'backgroundColor':HIGH}}}}})
reqs.append({'mergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':START,'endColumnIndex':BE},'mergeType':'MERGE_ALL'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':START,'endColumnIndex':BE},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':START,'endColumnIndex':BE},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':START,'endIndex':BE},'properties':{'pixelSize':92},'fields':'pixelSize'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':LEGx,'endColumnIndex':LEGx+2},'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat.textFormat'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':13,'startColumnIndex':LEGx+1,'endColumnIndex':LEGx+2},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':LEGx,'endIndex':LEGx+1},'properties':{'pixelSize':160},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':LEGx+1,'endIndex':LEGx+2},'properties':{'pixelSize':560},'fields':'pixelSize'}})
sh.batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
# ---- verify ----
chk=(sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!{A1(START)}2:{A1(BE-1)}3").execute().get('values',[]))
print(f"\nDONE. block {A1(START)}..{A1(BE-1)} | legend {A1(LEGx)}:{A1(LEGx+1)} | Hold? restored at {A1(hold_idx)}")
print("headers:",chk[0] if chk else '')
print("row3   :",chk[1] if len(chk)>1 else '')
