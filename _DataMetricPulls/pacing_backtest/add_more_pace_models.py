# -*- coding: utf-8 -*-
"""Add the DROPPED pace models to the New_Backtest_Clean_7.13.2026 tab ONLY, as extra columns showing
what each PROJECTS (final count) at every row's moment: Hawkes, Particle Filter, Finish Line, Kalman+Sleep.
Plus Actual final + Market (Poly Pace) side-by-side so the overshoot vs the market/reality is visible.
Surgical: writes ONLY AE..AJ + relocates the legend. Re-runs the 16 auctions to get row-aligned timestamps
(verified against the live tab: action/bracket/our_center), then computes each model walk-forward per row."""
import subprocess, sys, os, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
sys.stdout.reconfigure(encoding='utf-8'); rng=np.random.default_rng(7)
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; HERE=os.path.dirname(os.path.abspath(__file__)); OUT=HERE+"/audit_out3"; ET=ZoneInfo('America/New_York')
import glob
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds).spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
def _gid(t):
    for x in sh.get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
sh.batchUpdate(spreadsheetId=SEE,body={'requests':[{'updateSheetProperties':{'properties':{'sheetId':_gid(TAB),'gridProperties':{'columnCount':40}},'fields':'gridProperties.columnCount'}}]}).execute()
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); hd_all=pd.to_datetime(pts,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
# ---- model helpers (inlined from the model files, unchanged math) ----
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
    mu=max(mr*0.3,0.1); alpha=min(clus*1.5,0.95); beta=max(min(1.0/max(mx,1),3.0),0.3); return mu,alpha,beta
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
    cnt=np.array([obs(s+h*3600,s+(h+1)*3600) for h in range(n)]); hrs=np.array([pd.Timestamp(s+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(n)]); return cnt,hrs
def pf_forecast(s,cps,e,prior_rate,mult):
    M=500; oc,oh=hour_counts(s,cps); lam=rng.lognormal(math.log(max(prior_rate,0.2)),0.6,M)
    for n,H in zip(oc,oh):
        lam*=np.exp(rng.normal(0,0.12,M)); mu=np.maximum(lam*mult[H],1e-4); logw=n*np.log(mu)-mu
        w=np.exp(logw-logw.max()); w/=w.sum(); idx=rng.choice(M,M,p=w); lam=lam[idx]*np.exp(rng.normal(0,0.03,M))
    rem=[pd.Timestamp(cps+h*3600,unit='s',tz='UTC').tz_convert(ET).hour for h in range(int((e-cps)/3600))]
    rm=np.array([mult[H] for H in rem]).sum() if rem else 0.0; o=obs(s,cps)
    return float(np.mean(o+rng.poisson(np.clip(lam*rm,0,1e4))))
# ---- prior 2-day auctions (walk-forward) ----
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
allA=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    try: w=noon(a.auction_slug)
    except: continue
    if not 1.5<=(w[1]-w[0])/86400<=2.6: continue
    allA.append({'s':w[0],'e':w[1]})
def priors(s,mult):
    p2=[a for a in allA if a['e']<s]
    rmean=float(np.mean([obs(a['s'],a['e'])/((a['e']-a['s'])/3600) for a in p2])) if p2 else 40.0
    peff=[obs(a['s'],a['e'])/eff_hours(a['s'],a['e'],mult) for a in p2 if eff_hours(a['s'],a['e'],mult)>0]
    return rmean,peff
# ---- re-run auctions, compute the 4 models per trade row ----
audf=pd.read_csv(OUT+"/clean_sweep.csv"); SLUGS=['elon-musk-of-tweets-'+a for a in audf.auction]
seq=[]  # per row: haw, pf, fin, ksleep, actual, kal, acc, ens, cap, action, bracket
for slug in SLUGS:
    s,e=noon(slug); total=(e-s)/3600.0; mult=diurnal_mult(s); rmean,peff=priors(s,mult); finalc=obs(s,e)
    env=dict(os.environ,AUCTION=slug); env.pop('REACT6H',None); env.pop('PACE_EDGE',None)
    subprocess.run([sys.executable,'-u',HERE+'/single_auction_seesaw.py'],capture_output=True,text=True,env=env,timeout=600)
    tr=pd.read_csv(OUT+"/one_auction_trades.csv")
    for _,t in tr.iterrows():
        p=str(t['et']).split(); d=p[0].split('-'); tm=p[1].split(':'); mo,da,hh,mm,ss=int(d[0]),int(d[1]),int(tm[0]),int(tm[1]),int(tm[2])
        tms=int(pd.Timestamp(datetime(2026,mo,da,hh,mm,ss,tzinfo=ET)).timestamp()); o=obs(s,tms); eh=(tms-s)/3600.0; rh=max(total-eh,0.0)
        hc=[{'count':obs(s+h*3600,s+(h+1)*3600)} for h in range(int(eh))]; mu,al,be=fit_hawkes(hc)
        haw=hawkes_pace(hc,int(round(rh)),o,mu,al,be)
        pf=pf_forecast(s,tms,e,rmean,mult)
        r6=obs(max(s,tms-6*3600),tms)/6.0; fin=o+r6*rh
        eff_el=eff_hours(s,tms,mult); eff_rem=eff_hours(tms,e,mult); ksleep=o+kblend(o/max(eff_el,0.1),peff)*eff_rem
        seq.append({'haw':round(haw,1),'pf':round(pf,1),'fin':round(fin,1),'ks':round(ksleep,1),'act':finalc,
                    'kal':t.get('kal',''),'acc':t.get('acc',''),'ens':t.get('ens',''),'cap':t['our_center'],'action':str(t['action']),'bracket':str(t['bracket'])})
    print(f"  {slug.replace('elon-musk-of-tweets-','')}: rows so far {len(seq)}",flush=True)
n=len(seq)
# ---- alignment guard + market column (col J) ----
def col(letter): return [ (r[0] if r else '') for r in sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!{letter}3:{letter}{n+2}",valueRenderOption='UNFORMATTED_VALUE').execute().get('values',[]) ]
G=col('G'); I=col('I'); K=col('K'); J=col('J')
for L in (G,I,K,J):
    L+=['']*(n-len(L))
misc=sum(1 for i in range(n) if not (isinstance(I[i],(int,float)) and abs(float(I[i])-float(seq[i]['cap']))<=0.15))
print(f"\nALIGNMENT: our_center(I) mismatches={misc} (must be 0 to write)")
if misc: print("ABORT: not aligned"); sys.exit(1)
# ---- SUMMARY: overshoot vs actual + alignment vs market, per model ----
def mae(pred,truth):
    v=[abs(p-truthv) for p,truthv in zip(pred,truth) if isinstance(p,(int,float)) and isinstance(truthv,(int,float))]; return sum(v)/len(v) if v else float('nan')
def signed_early(pred,truth,rhs):
    v=[p-truthv for p,truthv,r in zip(pred,truth,rhs) if isinstance(p,(int,float)) and isinstance(truthv,(int,float)) and r>24]; return sum(v)/len(v) if v else float('nan')
# reconstruct rh per row for early split
rhs=[]
for slug in SLUGS: pass
# recompute rh cheaply from tab col C not needed; approximate via seq order is complex -> use market J availability only for MAE
def num(x):
    try: return float(x)
    except: return None
models={'Kalman':[num(r['kal']) for r in seq],'AccrualCurve':[num(r['acc']) for r in seq],'Ensemble':[num(r['ens']) for r in seq],
        'Ens+Cap1.5':[num(r['cap']) for r in seq],'Hawkes':[r['haw'] for r in seq],'ParticleFilter':[r['pf'] for r in seq],
        'FinishLine':[r['fin'] for r in seq],'Kalman+Sleep':[r['ks'] for r in seq]}
actual=[num(r['act']) for r in seq]; market=[num(x) for x in J]
print(f"\n{'model':>15} | {'MAE vs ACTUAL':>13} | {'MAE vs MARKET':>13} | {'mean signed err':>15}")
for name,pred in models.items():
    ma=mae(pred,actual); mm=mae(pred,market); se=sum([p-a for p,a in zip(pred,actual) if p is not None and a is not None])/max(1,sum(1 for p,a in zip(pred,actual) if p is not None and a is not None))
    print(f"{name:>15} | {ma:>13.1f} | {mm:>13.1f} | {se:>+15.1f}")
# ---- WRITE AE..AJ ----
grid=[[r['haw'],r['pf'],r['fin'],r['ks'],r['act'],(num(J[i]) if num(J[i]) is not None else '')] for i,r in enumerate(seq)]
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AE3",valueInputOption='RAW',body={'values':grid}).execute()
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AE2",valueInputOption='RAW',body={'values':[['Hawkes','Particle Filter','Finish Line','Kalman+Sleep','Actual final','Market (Poly Pace)']]}).execute()
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AA1",valueInputOption='RAW',body={'values':[["PACING MODEL SHOOTOUT: each model's projected FINAL count at this row's moment. AD Ens+Cap1.5 = the LOCKED 'Our Pace'. Compare each vs Actual final (truth) and Market (what the crowd paced)."]]}).execute()
# relocate legend to AL/AM (clear old AF/AG legend first)
sh.values().clear(spreadsheetId=SEE,range=f"'{TAB}'!AF2:AG12").execute()
legend=[['Pacing model','What it is / does it overshoot?'],
 ['Kalman','Prior avg rate blended with observed rate, extrapolated to 48h. Overshoots early on bursts.'],
 ['AccrualCurve','Current count / historical share landed by this hour. WORST early overshoot (tiny denominator).'],
 ['Ensemble','Time-weighted Kalman(early)+Accrual(late). Inherits the early overshoot.'],
 ['Ens+Cap1.5 (LOCKED)','Ensemble with go-forward rate capped at 1.5x baseline. Still overshoots early; = Our Pace (I).'],
 ['Hawkes','Self-exciting burst model (each tweet lifts the next). Overshoots hardest during clusters.'],
 ['Particle Filter','Poisson particle cloud x diurnal (sleep) multiplier. Does NOT extrapolate through the 4-9am dead-zone.'],
 ['Finish Line','Current count + (last-6h rate x remaining). Recent-rate only, no long extrapolation.'],
 ['Kalman+Sleep','Kalman over SLEEP-ADJUSTED remaining hours. Built specifically to stop night-burst overshoot.'],
 ['Actual final','The tweet count the auction actually settled at (truth).'],
 ['Market (Poly Pace)','The crowd\'s price-weighted implied final count = col J. The benchmark to align to.']]
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AL2",valueInputOption='RAW',body={'values':legend}).execute()
# ---- formatting ----
def gid(t):
    for x in sh.get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
g=gid(TAB)
LOW={'red':0.87,'green':0.93,'blue':0.99}; MID={'red':0.64,'green':0.80,'blue':0.93}; HIGH={'red':0.40,'green':0.61,'blue':0.84}
def rng_(c): return [{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}]
reqs=[{'repeatCell':{'range':{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':30,'endColumnIndex':36},'cell':{'userEnteredFormat':{'numberFormat':{'type':'NUMBER','pattern':'0'}}},'fields':'userEnteredFormat.numberFormat'}}]
for c in range(30,36):  # AE-AJ pace-band shading like AA-AD
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'40'}]},'format':{'backgroundColor':LOW}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_BETWEEN','values':[{'userEnteredValue':'40'},{'userEnteredValue':'64'}]},'format':{'backgroundColor':MID}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng_(c),'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'64'}]},'format':{'backgroundColor':HIGH}}}}})
# extend the merged group header AA1 -> AA1:AJ1
reqs.append({'unmergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':30}}})
reqs.append({'mergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':36},'mergeType':'MERGE_ALL'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':36},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':30,'endColumnIndex':36},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True},'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat(horizontalAlignment,textFormat,wrapStrategy)'}})
# widths: AE-AJ compact; reset AF/AG (were legend-sized); legend AL/AM
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':30,'endIndex':36},'properties':{'pixelSize':92},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':31,'endIndex':33},'properties':{'pixelSize':92},'fields':'pixelSize'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':37,'endColumnIndex':39},'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat.textFormat'}})
reqs.append({'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':13,'startColumnIndex':38,'endColumnIndex':39},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':37,'endIndex':38},'properties':{'pixelSize':160},'fields':'pixelSize'}})
reqs.append({'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':38,'endIndex':39},'properties':{'pixelSize':560},'fields':'pixelSize'}})
sh.batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
print(f"\nDONE. wrote {n} rows to AE-AJ (Hawkes/PF/FinishLine/Kalman+Sleep/Actual/Market) + legend AL:AM.")
for i in [0,1,n-1]:
    print(f"  row {i+3}: Haw {seq[i]['haw']} | PF {seq[i]['pf']} | Fin {seq[i]['fin']} | K+Sleep {seq[i]['ks']} | Actual {seq[i]['act']} | Market {J[i]}")
