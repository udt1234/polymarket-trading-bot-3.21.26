"""Backtest the PACING_SPEC layered model. Two questions:
(1) Ablation: does each layer (1=linear, 3=Bayes, 4=clock, 4.5=multipliers, 6=gate) reduce
    the count projection error?
(2) THE EDGE TEST: with the spec's sigma FIX (sqrt(mu-posts)*1.5 + floor) and the Layer-6 final
    gate, does the model's bracket probability finally BEAT the market price (Brier), especially
    near resolution? The earlier "no edge" used the buggy wide sigma; this is the fair rematch.
"""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, json
from scipy.stats import norm
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON=ROOT/'_DataMetricPulls'/'canonical'; OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

full=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet').sort_values('ms')
cnt=full[full.counts_main_feed]
cnt_ts=(cnt.ms.to_numpy()//1000).astype('int64')
all_ts=(full.ms.to_numpy()//1000).astype('int64')              # all tweets (for reply signal)
is_reply_all=(full['type']=='reply').to_numpy()
def obs(s,e): return int(np.searchsorted(cnt_ts,e)-np.searchsorted(cnt_ts,s))
def cnt_times(s,e):
    lo=np.searchsorted(cnt_ts,s); hi=np.searchsorted(cnt_ts,e); return cnt_ts[lo:hi]
def replies_in(s,e):
    lo=np.searchsorted(all_ts,s); hi=np.searchsorted(all_ts,e); return int(is_reply_all[lo:hi].sum())

# clock rate per ET hour (counting tweets/hour) from full history
cet=pd.to_datetime(cnt.ms,unit='ms',utc=True).dt.tz_convert('America/New_York')
ndays=max(1,(cet.max()-cet.min()).days)
clock_rate={h: float(cnt.groupby(cet.dt.hour).size().get(h,0))/ndays for h in range(24)}

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
buckets_by_slug=prc.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
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

sel=[]
cur=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
for _,a in cur.iterrows():
    w=noonET(a.auction_slug,a['start_utc'].year)
    if not w: continue
    ns,ne=w; dur=a.duration_type
    if dur=='7-day' and ns<int(pd.Timestamp('2025-09-05',tz='UTC').timestamp()): continue
    if dur=='2-day' and ns<int(pd.Timestamp('2026-01-05',tz='UTC').timestamp()): continue
    blab=[b for b in buckets_by_slug.get(a.auction_slug,[]) if (a.auction_slug,b) in price_idx]
    if not blab: continue
    actual=obs(ns,ne)
    if actual<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,ns=ns,ne=ne,winner=a['winning_bucket'],actual=actual,
                    branges=[(b,pbk(b)) for b in blab if pbk(b)]))
sel=sorted(sel,key=lambda x:x['ns'])
print(f"auctions: {len(sel)}")

def clock_remaining(cps,ne):
    rem=0.0; t=cps
    while t<ne:
        hr_et=pd.Timestamp(t,unit='s',tz='UTC').tz_convert('America/New_York').hour
        nxt=min(ne, (t//3600+1)*3600); frac=(nxt-t)/3600
        rem+=clock_rate[hr_et]*frac; t=nxt
    return rem

def gate(cps, times, ns):
    if len(times)==0: return False, 0.0
    silence=(cps-times[-1])/60.0
    pdone=1/(1+math.exp(-(-2.649+0.761*math.log(max(silence,1)))))
    h_et=pd.Timestamp(cps,unit='s',tz='UTC').tz_convert('America/New_York').hour
    bedtime = 1 if 3<=h_et<9 else 0
    gaps=np.diff(times)/60.0; clusters=1+int(np.sum(gaps>90))
    conf=min(1.0, pdone*(1.0 if bedtime else 0.6)*(1.15 if clusters>=5 else 1.0))
    return conf>=0.7, conf

def bracket_probs(mu, sigma, o, branges):
    wp={}
    for b,(lo,hi) in branges:
        if hi is not None and hi<o: wp[b]=0.0; continue   # floor: can't be below posts_so_far
        zl=(max(lo,o)-0.5-mu)/sigma
        zh=1.0 if hi is None else norm.cdf((hi+0.5-mu)/sigma)
        wp[b]=max(0.0, zh-norm.cdf(zl))
    tot=sum(wp.values()) or 1
    return {b:v/tot for b,v in wp.items()}

TTG=[48,24,12,6,3,1,0.5]
CONFIGS=['L1_linear','L3_bayes','L4_clock','L45_mult','L6_gate']
err_hist={m:[] for m in CONFIGS}   # not strictly needed; sigma uses spec fix
rec=[]
for a in sel:
    ns,ne,actual=a['ns'],a['ne'],a['actual']; total_h=(ne-ns)/3600
    priors=[p for p in sel if p['ne']<ns]
    pt=[p['actual'] for p in priors]; pdur=[(p['ne']-p['ns'])/3600 for p in priors]
    # recent daily + yesterday (Layer 2 momentum)
    rd=obs(ns-7*86400,ns)/7.0; yd=obs(ns-86400,ns)
    daily_prior=0.6*rd+0.4*yd if (rd>0 or yd>0) else (np.mean([p['actual']/((p['ne']-p['ns'])/3600)*24 for p in priors]) if priors else 50)
    for ttg in TTG:
        eh=total_h-ttg
        if eh<=0.5 or ttg>=total_h: continue
        cps=int(ne-ttg*3600); o=obs(ns,cps); tms=cnt_times(ns,cps)
        # layers
        L1=o*total_h/eh
        # Bayes (L3): blend linear obs_proj with prior(total)+momentum
        prior_total=daily_prior*(total_h/24.0)
        ec=min(0.99,max(0.001,eh/total_h)); op=o/ec
        ps=max(1.0,float(np.std(pt,ddof=1)) if len(pt)>1 else prior_total*0.25)
        ov=max(1.0,o*(1-ec)/(ec**2)); L3=(prior_total/ps**2+op/ov)/(1/ps**2+1/ov)
        # L4 clock
        L4=o+clock_remaining(cps,ne)
        # L4.5 multipliers
        morn_exp=clock_remaining(ns, min(cps, ns+ (12-12)*3600)) # placeholder
        morn_act=obs(ns,cps) and 0  # simple: count morning ET hours [6,12) so far
        # morning posts in [6,12) ET so far
        m_lo=ns; m_hi=cps
        morn_posts=0
        tt=pd.to_datetime(cnt_times(ns,cps),unit='s',utc=True)
        if len(tt): morn_posts=int(((tt.tz_convert('America/New_York').hour>=6)&(tt.tz_convert('America/New_York').hour<12)).sum())
        morn_mult=1.15 if morn_posts>=max(3, 0.30*o) else 1.0
        reps=replies_in(ns,cps); reply_share=reps/max(o,1); reply_mult=1.10 if reply_share>0.8 else 1.0
        L45=(o+clock_remaining(cps,ne))*morn_mult*reply_mult
        # L6 gate
        fired,conf=gate(cps,tms,ns)
        L6 = float(o) if fired else L45
        proj={'L1_linear':max(L1,o),'L3_bayes':max(L3,o),'L4_clock':max(L4,o),'L45_mult':max(L45,o),'L6_gate':max(L6,o)}
        # market brier
        mk={b:price_at(a['slug'],b,cps) for b,_ in a['branges']}; mk={b:v for b,v in mk.items() if v is not None}
        if a['winner'] in mk and sum(mk.values())>0:
            tot=sum(mk.values()); mp={b:v/tot for b,v in mk.items()}
            mkt_br=sum((mp.get(b,0)-(1.0 if b==a['winner'] else 0))**2 for b,_ in a['branges'])
        else: mkt_br=None
        row=dict(dur=a['dur'],ttg=ttg,actual=actual,o=o,gate=int(fired),mkt_br=mkt_br)
        for cfg in CONFIGS:
            mu=proj[cfg]
            sigma=max(0.7, math.sqrt(max(mu-o,1.0))*1.5)
            if cfg=='L6_gate' and fired: sigma=0.7   # gate fired -> count locked, tight
            wp=bracket_probs(mu,sigma,o,a['branges'])
            pw=wp.get(a['winner'],1e-9)
            row[f'{cfg}_err']=abs(mu-actual)/actual*100
            row[f'{cfg}_br']=sum((wp.get(b,0)-(1.0 if b==a['winner'] else 0))**2 for b,_ in a['branges'])
            rgw=pbk(a['winner']); row[f'{cfg}_hit']=int(bool(rgw and rgw[0]<=mu<=(rgw[1] if rgw[1] is not None else 1e9)))
        rec.append(row)
R=pd.DataFrame(rec)

print("\n=== (1) ABLATION: mean count-error % by layer & time-to-go ===")
print(f"{'ttg':>5} " + "".join(f"{c.split('_')[0]:>9}" for c in CONFIGS))
for ttg in TTG:
    s=R[R.ttg==ttg]
    if not len(s): continue
    print(f"{ttg:>5} " + "".join(f"{s[f'{c}_err'].mean():>8.1f}%" for c in CONFIGS))

print("\n=== (2) THE EDGE TEST: bracket Brier vs MARKET (lower=better), by time-to-go ===")
print("    (does the spec model with sigma-fix + gate finally BEAT the market price?)")
print(f"{'ttg':>5}{'n':>5}{'MARKET':>9}" + "".join(f"{c.split('_')[0]:>9}" for c in CONFIGS) + "   beats market?")
for ttg in TTG:
    s=R[R.ttg==ttg].dropna(subset=['mkt_br'])
    if not len(s): continue
    mkt=s.mkt_br.mean(); vals={c:s[f'{c}_br'].mean() for c in CONFIGS}
    beats=[c.split('_')[0] for c in CONFIGS if vals[c]<mkt]
    print(f"{ttg:>5}{len(s):>5}{mkt:>9.3f}" + "".join(f"{vals[c]:>9.3f}" for c in CONFIGS) + f"   {','.join(beats) if beats else 'NO'}")
print(f"\ngate fired on {100*R.gate.mean():.1f}% of checkpoints (mostly near resolution / bedtime)")
R.to_csv(OUT/'backtest_layers_results.csv',index=False)
