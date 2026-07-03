"""LIVE pacing snapshot for ONE auction (default: elon June 22-24, 2-day).
Pulls the live tweet count via X API (locked rule), runs EVERY pacing model with the
SAME code as the validated leaderboard, and records HOW each arrives at its number.
Outputs live_pace.json (+ prints a table). A separate step pushes it to a Google Sheet.
"""
import os, sys, json, math, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')
np.random.seed(42)
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON = ROOT/'_DataMetricPulls'/'canonical'
ET = ZoneInfo('America/New_York'); ELON_ID='44196397'
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
SLUG = sys.argv[1] if len(sys.argv)>1 else 'elon-musk-of-tweets-june-22-june-24'

# ---- historical clean source (through backfill end) + canonical priors ----
bf = pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet')
bf = bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
post_ts=(bf.ms.to_numpy()//1000).astype('int64'); cover0,cover1=int(post_ts.min()),int(post_ts.max())
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def parse_noonET(slug,ref_year):
    toks=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[toks[0].lower()]; d1=int(toks[1])
        if len(toks)>=4 and toks[2].lower() in MONTHS: mo2=MONTHS[toks[2].lower()]; d2=int(toks[3])
        else: mo2=mo1; d2=int(toks[2])
    except Exception: return None
    y2=ref_year+(1 if mo2<mo1 else 0)
    return (pd.Timestamp(datetime(ref_year,mo1,d1,12,0,tzinfo=ET)).tz_convert('UTC'),
            pd.Timestamp(datetime(y2,mo2,d2,12,0,tzinfo=ET)).tz_convert('UTC'))
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')
         &(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))].copy()
sel=[]
for _,a in cand.iterrows():
    w=parse_noonET(a['auction_slug'],a['start_utc'].year)
    if not w: continue
    ns,ne=w; dur=a['duration_type']; days=(ne-ns).total_seconds()/86400
    if dur=='7-day' and not (6.5<=days<=7.6): continue
    if dur=='2-day' and not (1.5<=days<=2.6): continue
    s=int(ns.timestamp()); e=int(ne.timestamp())
    if e>cover1 or s<cover0+7200: continue
    sel.append({'slug':a['auction_slug'],'dur':dur,'s':s,'e':e,'actual':obs(s,e)})
sel=[x for x in sel if x['actual']>0]

# ---- LIVE window + count from X API ----
w=parse_noonET(SLUG, 2026); assert w, f"cannot parse {SLUG}"
ws,we=w; s=int(ws.timestamp()); e=int(we.timestamp())
now=datetime.now(timezone.utc); now_ts=int(now.timestamp())
eh=(now_ts-s)/3600.0; rh=max(0.0,(e-now_ts)/3600.0); total_h=(e-s)/3600.0
BEARER=next(l.split('=',1)[1].strip() for l in open(ROOT/'.env',encoding='utf-8') if l.startswith('X_BEARER_TOKEN='))
def pull(start_iso,end_iso):
    rows=[]; tok=None
    while True:
        p={'query':f'from:{ELON_ID}','start_time':start_iso,'end_time':end_iso,'max_results':'500',
           'tweet.fields':'created_at,referenced_tweets,in_reply_to_user_id'}
        if tok: p['next_token']=tok
        req=urllib.request.Request('https://api.x.com/2/tweets/search/all?'+urllib.parse.urlencode(p),
                                   headers={'Authorization':f'Bearer {BEARER}'})
        for att in range(6):
            try:
                with urllib.request.urlopen(req) as r: body=json.loads(r.read()); break
            except urllib.error.HTTPError as ex:
                if ex.code==429: time.sleep(8*(att+1)); continue
                print('HTTP',ex.code,ex.read().decode()[:200]); raise
        rows+=body.get('data',[]); tok=body.get('meta',{}).get('next_token')
        if not tok: break
        time.sleep(1.1)
    return rows
def snow_ms(tid): return (int(tid)>>22)+1288834974657
def classify(t):
    refs=[r['type'] for r in t.get('referenced_tweets',[])]
    if 'retweeted' in refs: return 'repost'
    if 'quoted' in refs: return 'quote'
    if 'replied_to' in refs: return 'reply'
    return 'original'
raw=pull(ws.strftime('%Y-%m-%dT%H:%M:%SZ'),(now-timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ'))
ev=[]; counted=0; mix={}
for t in raw:
    ty=classify(t); irt=str(t.get('in_reply_to_user_id'))
    cnt = ty in ('original','quote','repost') or (ty=='reply' and irt==ELON_ID)
    mix[ty]=mix.get(ty,0)+1
    if cnt:
        ms=snow_ms(t['id']); ts=ms/1000.0
        if s<=ts<=now_ts: ev.append((ts-s)/3600.0); counted+=1
ev=sorted(ev); o=counted

# ---- priors for this auction ----
priors=[p for p in sel if p['e']<s]
pt=[p['actual'] for p in priors]; pdur=[(p['e']-p['s'])/3600 for p in priors]
prate=[p['actual']/((p['e']-p['s'])/3600) for p in priors if p['e']>p['s']]
pwa=[(p['actual'],(p['e']-p['s'])/3600,(s-p['e'])/604800) for p in priors]
sm={}; dflt=float(np.mean(prate)) if prate else 1.0
hi=len(post_ts)
if hi>100:
    hd=pd.to_datetime(post_ts,unit='s',utc=True).tz_convert(ET)
    cnts=pd.DataFrame({'dow':hd.dayofweek,'hour':hd.hour}).groupby(['dow','hour']).size()
    span=max(1,(s-post_ts[0])/86400); occ=span/7
    for (dw,hr),cc in cnts.items(): sm[(dw,hr)]=cc/occ

# ---- models (verbatim from backtest_clean.py) + derivations ----
def m_linear(o,eh,rh): return 0 if eh<=0 else o*(eh+rh)/eh
def m_curbayes(o,eh,rh,pool):
    th=eh+rh
    if not pool or o<=0 or eh<=0: return float(np.mean(pool)) if pool else 0
    ec=min(0.99,max(0.001,eh/th)); op=o/ec; pm=float(np.mean(pool))
    ps=max(1.0,float(np.std(pool,ddof=1)) if len(pool)>1 else pm*0.25)
    ov=max(1.0,o*(1-ec)/(ec**2)); pp=1/ps**2; po=1/ov
    return (pp*pm+po*op)/(pp+po)
def m_gp(o,eh,rh,pt,pd_):
    if not pt: return o*(eh+rh)/max(eh,1)
    lp=(sum(pt)+o)/(sum(pd_)+eh) if (sum(pd_)+eh)>0 else 0
    return o+lp*rh
def m_seasonal(o,eh,rh,sm,cur,dflt):
    if not sm: return o*(eh+rh)/max(eh,1)
    er=0.0
    for h in range(int(rh)):
        et=pd.Timestamp(cur+h*3600,unit='s',tz='UTC').tz_convert(ET); er+=sm.get((et.dayofweek,et.hour),dflt)
    return o+er
def m_decay(o,eh,rh,pwa,eps=0.85):
    if not pwa: return o*(eh+rh)/max(eh,1)
    a0=sum(t*(eps**ag) for t,_,ag in pwa); b0=sum(d*(eps**ag) for _,d,ag in pwa) or 1
    return o+(a0+o)/(b0+eh)*rh
def _nll(p,evv,T):
    mu,al,be=p
    if mu<=0 or al<0 or be<=0 or al>=be: return 1e10
    ll=0.0; ds=0.0; pt_=0.0
    for i,t in enumerate(evv):
        ds=ds*math.exp(-be*(t-pt_))+1.0 if i>0 else 0.0
        inten=mu+al*ds
        if inten<=0: return 1e10
        ll+=math.log(inten); pt_=t
    integ=mu*T+sum((al/be)*(1-math.exp(-be*(T-t))) for t in evv)
    return -(ll-integ)
def fit_hawkes(evv,T):
    if len(evv)<5: return None
    try:
        r=minimize(_nll,[len(evv)/T*0.5,0.5,1.0],args=(evv,T),method='Nelder-Mead',options={'maxiter':200,'xatol':1e-3,'fatol':1e-3})
        if r.success or r.fun<1e9:
            mu,al,be=r.x
            if mu>0 and al>=0 and be>0 and al<be: return (mu,al,be)
    except Exception: pass
    return None
def sim_hawkes(mu,al,be,t0,t1,hist,n=50):
    if mu<=0 or be<=0: return 0
    h=np.asarray(hist,float); A0=float(np.sum(np.exp(-be*(t0-h)))) if len(h) else 0.0
    tot=[]
    for _ in range(n):
        A=A0; t=t0; c=0
        while True:
            lb=mu+al*A
            if lb<=0: break
            wv=np.random.exponential(1.0/lb); t+=wv
            if t>=t1: break
            A*=math.exp(-be*wv)
            if np.random.random()<(mu+al*A)/lb:
                A+=1.0; c+=1
                if c>=5000: break
        tot.append(c)
    return float(np.mean(tot)) if tot else 0
def m_mmpp(o,eh,rh,rates): return o+(0.5*(o/max(eh,1))+0.5*float(np.mean(rates)))*rh if rates else o*(eh+rh)/max(eh,1)
def m_negbin(o,eh,rh,pt):
    if not pt: return o*(eh+rh)/max(eh,1)
    me=float(np.mean(pt))
    if len(pt)<2: return me
    pf=(o/max(eh,1))/(me/(eh+rh)) if me>0 else 1
    return me*(0.7+0.3*pf)
def m_kalman(o,eh,rh,rates):
    if not rates: return o*(eh+rh)/max(eh,1)
    x=float(np.mean(rates)); P=float(np.var(rates))+0.01; R=max(0.1,P*0.5)
    K=(P+0.01)/(P+0.01+R); xn=x+K*(o/max(eh,1)-x)
    return o+xn*rh

fit=fit_hawkes(ev,eh) if len(ev)>=5 else None
cur_rate=o/eh if eh>0 else 0; hmean=float(np.mean(prate)) if prate else 0
rowsout=[]
def add(name,cat,pred,how): rowsout.append({'model':name,'category':cat,'forecast':round(pred),'how':how})

add('Linear','naive: pace continues',m_linear(o,eh,rh),
    f"{o} tweets in {eh:.1f}h = {cur_rate:.2f}/h, x {total_h:.0f}h total = {m_linear(o,eh,rh):.0f}")
add('Kalman','self-correcting average',m_kalman(o,eh,rh,prate),
    (lambda x=hmean,P=(float(np.var(prate))+0.01 if prate else 0):
     f"usual rate {x:.3f}/h (var {P-0.01:.3f}); gain K={(P+0.01)/(P+0.01+max(0.1,P*0.5)):.2f}; "
     f"blended {x+((P+0.01)/(P+0.01+max(0.1,P*0.5)))*(cur_rate-x):.3f}/h x {rh:.1f}h + {o} = {m_kalman(o,eh,rh,prate):.0f}")())
add('M4MMPP','quiet/manic 50-50',m_mmpp(o,eh,rh,prate),
    f"blend .5x current {cur_rate:.3f} + .5x usual {hmean:.3f} = {0.5*cur_rate+0.5*hmean:.3f}/h x {rh:.1f}h + {o} = {m_mmpp(o,eh,rh,prate):.0f}")
add('CurBayes','Bayesian blend (was deployed)',m_curbayes(o,eh,rh,pt),
    f"extrapolate {o}/(elapsed frac {min(.99,eh/total_h):.2f})={o/min(.99,eh/total_h):.0f}, precision-weighted vs prior mean count {np.mean(pt):.0f} -> {m_curbayes(o,eh,rh,pt):.0f}")
add('M0','Bayesian Gamma-Poisson',m_gp(o,eh,rh,pt,pdur),
    f"pooled rate (sum prior {sum(pt)}+{o})/(sum prior hrs {sum(pdur):.0f}+{eh:.0f})={(sum(pt)+o)/(sum(pdur)+eh):.3f}/h; {o}+rate x {rh:.1f}h = {m_gp(o,eh,rh,pt,pdur):.0f}")
add('M1Seas','time-of-day (sleep-aware)',m_seasonal(o,eh,rh,sm,now_ts,dflt),
    f"sum of expected tweets per remaining ET clock-hour over {rh:.0f}h = {m_seasonal(o,eh,rh,sm,now_ts,dflt)-o:.0f}; + {o} so far = {m_seasonal(o,eh,rh,sm,now_ts,dflt):.0f}")
add('Decay','Gamma-Poisson, recency-weighted',m_decay(o,eh,rh,pwa),
    f"recency-weighted prior rate (older weeks x0.85/wk) applied to {rh:.1f}h remaining + {o} = {m_decay(o,eh,rh,pwa):.0f}")
add('M5NB','fat-tailed average',m_negbin(o,eh,rh,pt),
    f"prior mean count {np.mean(pt):.0f} x pace-adjust = {m_negbin(o,eh,rh,pt):.0f}")
if fit:
    mu,al,be=fit; sim=sim_hawkes(mu,al,be,eh,eh+rh,ev)
    add('M2Hawk','self-exciting (MLE)',o+sim,
        f"fit mu={mu:.3f},alpha={al:.3f},beta={be:.3f}; simulate {rh:.0f}h -> +{sim:.0f}; total {o+sim:.0f}")
    sim3=sim_hawkes(mu,al*1.0,be,eh,eh+rh,ev,n=30)
    add('M3Hawk','marked self-exciting',o+sim3,f"Hawkes weighting reposts higher; +{sim3:.0f}; total {o+sim3:.0f}")
else:
    add('M2Hawk','self-exciting (MLE)',m_linear(o,eh,rh),"too few events to fit -> falls back to Linear")
    add('M3Hawk','marked self-exciting',m_linear(o,eh,rh),"too few events to fit -> falls back to Linear")

out={'slug':SLUG,'window_start_utc':ws.isoformat(),'window_end_utc':we.isoformat(),
     'now_utc':now.isoformat(),'elapsed_h':round(eh,1),'remaining_h':round(rh,1),
     'observed':o,'current_rate_per_h':round(cur_rate,3),'usual_rate_per_h':round(hmean,3),
     'n_priors':len(priors),'type_mix_pulled':mix,'models':rowsout}
(OUT/'live_pace.json').write_text(json.dumps(out,indent=2))
print(f"\nAUCTION {SLUG}  ({ws:%b %d %H:%M} -> {we:%b %d %H:%M} UTC)")
print(f"now {now:%b %d %H:%M} UTC | elapsed {eh:.1f}h | remaining {rh:.1f}h | OBSERVED so far = {o} (pulled mix {mix})")
print(f"current rate {cur_rate:.2f}/h | usual rate {hmean:.2f}/h | priors used = {len(priors)}\n")
print(f"{'MODEL':<10}{'FORECAST':>9}   HOW")
for r in sorted(rowsout,key=lambda x:x['forecast']):
    print(f"{r['model']:<10}{r['forecast']:>9}   {r['how']}")
