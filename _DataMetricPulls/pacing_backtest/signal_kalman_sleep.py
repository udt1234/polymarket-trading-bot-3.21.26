# -*- coding: utf-8 -*-
"""YOUR divergence strategy, SIGNALS ONLY (no fills), on may-14-may-16, pace model = KALMAN + SLEEP.
Kalman+Sleep: rate is Kalman-blended posts-per-EFFECTIVE-hour, projected over SLEEP-ADJUSTED
remaining hours (each remaining hour weighted by his diurnal posting density; 4-9am ET ~= 0).
So a late-night burst is NOT extrapolated straight through the sleep dead-zone. Walk-forward."""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
hd_all=pd.to_datetime(pts,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def q(x): return con.execute(x).df()
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def center(lo,hi): return (lo+15) if hi>=10**8 else (lo+hi)/2.0
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
def diurnal_mult(before_s):
    h=hd_all[pts<before_s]
    if len(h)<240: return np.ones(24)
    m=np.array([np.sum(h==hh) for hh in range(24)],float); return m/m.mean() if m.mean()>0 else np.ones(24)
def eff_hours(t0,t1,mult):
    n=int((t1-t0)/3600)
    if n<=0: return 0.0
    hrs=pd.to_datetime(t0+np.arange(n)*3600,unit='s',utc=True).tz_convert(ET).hour.to_numpy()
    return float(np.sum(mult[hrs]))
def kblend(obs_rate,priors):
    if not priors: return obs_rate
    x=float(np.mean(priors));P=float(np.var(priors))+0.01;K=(P+0.01)/(P+0.01+max(0.1,P*0.5));return x+K*(obs_rate-x)

SLUG='elon-musk-of-tweets-may-14-may-16'
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
row=auc[auc.auction_slug==SLUG].iloc[0]; s,e=noon(SLUG,row['start_utc'].year); total=(e-s)/3600
t2b={t:l for l,t in json.loads(row.bracket_yes_token_ids).items() if isinstance(t,str) and t.isdigit() and len(t)>18 and pbk(l)}
winner=str(row.winning_bucket); mult=diurnal_mult(s)
prior_eff=[]
for _,a in auc.iterrows():
    if a.duration_type not in ('2-day','7-day'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w or w[1]>=s or w[1]<=w[0]: continue
    eh=eff_hours(w[0],w[1],mult)
    if eh>0: prior_eff.append(obs(*w)/eh)
print(f"AUCTION {SLUG} | winner {winner} | final {obs(s,e)} | {len(prior_eff)} priors | diurnal 4-8am ET weights={[round(mult[h],2) for h in range(4,9)]}")
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
files=l2files(s,e); arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in t2b)+")"
px=q(f"""SELECT asset_id,(ts//600000)*600000 bar, arg_max(best_bid,ts) bid, arg_max(best_ask,ts) ask
    FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
px['bucket']=px.asset_id.map(t2b); px['mid']=np.where(px.bid>0,(px.bid+px.ask)/2,px.ask)
grid=px.pivot_table(index='bar',columns='bucket',values='mid',aggfunc='last').sort_index().ffill()
brs={b:pbk(b) for b in grid.columns if pbk(b)}
ENTER=5.0; EXIT=2.0; rows=[]; trades=[]; pos=None
for bar in grid.index:
    t=bar/1000.0; elapsed=(t-s)/3600.0
    if elapsed<3 or elapsed>total-0.3: continue
    o=obs(s,int(t))
    eff_el=eff_hours(s,int(t),mult); eff_rem=eff_hours(int(t),e,mult)
    rate_eff=o/max(eff_el,0.1); our=o+kblend(rate_eff,prior_eff)*eff_rem
    prices={b:grid.loc[bar,b] for b in brs if pd.notna(grid.loc[bar,b]) and grid.loc[bar,b]>0}
    tot=sum(prices.values())
    if tot<=0: continue
    mkt=sum(center(*brs[b])*(p/tot) for b,p in prices.items())
    div=our-mkt; target=next((b for b,(lo,hi) in brs.items() if lo<=round(our)<=hi),None)
    def rec(act,b,px_,reason):
        trades.append({'action':act,'bracket':b,'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'tweets':o,
            'our_count':round(our,1),'eff_rem_h':round(eff_rem,1),'mkt_count':round(mkt,1),
            'divergence':round(div,1),'price':round(px_,3) if px_==px_ else None,'reason':reason})
    action=''
    if pos is None:
        if abs(div)>=ENTER and target and target in prices:
            pos={'b':target}; action='BUY'; rec('BUY',target,prices[target],f"our pace {our:.0f} vs market {mkt:.0f}, edge {abs(div):.0f}")
    else:
        held=pos['b']; hp=prices.get(held,float('nan'))
        if abs(div)<=EXIT or target!=held:
            rec('SELL',held,hp,('divergence converged (<=%.0f)'%EXIT) if abs(div)<=EXIT else f"pace moved to {target}"); pos=None
            if target and target in prices and abs(div)>=ENTER:
                pos={'b':target}; rec('BUY',target,prices[target],f"rotate to {target}")
    rows.append({'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'elapsed_h':round(elapsed,1),'tweets':o,
        'kalman_sleep(our)':round(our,1),'eff_rem_h':round(eff_rem,1),'mkt(revpace)':round(mkt,1),
        'divergence':round(div,1),'target':target,'holding':pos['b'] if pos else '','action':action})
td=pd.DataFrame(trades); series=pd.DataFrame(rows)
td.to_csv(f"{OUT}/signals_kalman_sleep.csv",index=False); series.to_csv(f"{OUT}/timeline_kalman_sleep.csv",index=False)
nb=int((td.action=='BUY').sum()) if len(td) else 0; ns=int((td.action=='SELL').sum()) if len(td) else 0
print(f"\nKALMAN+SLEEP: {len(td)} signals ({nb} BUY, {ns} SELL)   [raw Accrual=33, ensemble=21]")
print(f"our projection range: {series['kalman_sleep(our)'].min():.0f} - {series['kalman_sleep(our)'].max():.0f}   (raw 110-311, ensemble 66-185; actual final {obs(s,e)})")
print(f"market range: {series['mkt(revpace)'].min():.0f} - {series['mkt(revpace)'].max():.0f} | divergence {series.divergence.min():+.0f} to {series.divergence.max():+.0f}")
if len(td):
    print("\nall signals:")
    for _,r in td.iterrows():
        print(f"  {r.et} | {r.action:<4} | our {r.our_count:>5} (effRem {r.eff_rem_h:>4}h) vs mkt {r.mkt_count:>5} | div {r.divergence:>+5} | px {r.price} | {r.reason}")
print(f"\nWROTE {OUT}/signals_kalman_sleep.csv + timeline_kalman_sleep.csv")
