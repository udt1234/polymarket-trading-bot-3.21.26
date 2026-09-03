# -*- coding: utf-8 -*-
"""SIR'S DIVERGENCE STRATEGY on ONE FULL AUCTION, with the LOCKED pace model Ensemble+CAP1.5.
Signals only (no fills, no P&L, per standing instruction). Also reports, for every BUY, whether
that bracket ended up being the OFFICIAL winner - so the strategy is tested without simulating money.
Pace: Kalman early + AccrualCurve late, blended, go-forward rate CAPPED at 1.5x baseline."""
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
def share_wf(dur_h,before_ts):
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    return (np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None)

SLUG='elon-musk-of-tweets-may-14-may-16'; CAPMULT=1.5
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
row=auc[auc.auction_slug==SLUG].iloc[0]; s,e=noon(SLUG,row['start_utc'].year); total=(e-s)/3600
t2b={t:l for l,t in json.loads(row.bracket_yes_token_ids).items() if isinstance(t,str) and t.isdigit() and len(t)>18 and pbk(l)}
WINNER=str(row.winning_bucket); FINAL=obs(s,e)
# walk-forward priors (same duration, ended before this auction started)
pr=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w or w[1]>=s or w[1]<=w[0]: continue
    pr.append(obs(*w)/((w[1]-w[0])/3600))
rmean=float(np.mean(pr)); Pk=np.var(pr)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5))
share=share_wf(48,s)
print(f"AUCTION {SLUG} | OFFICIAL WINNER {WINNER} | he finished at {FINAL} tweets")
print(f"LOCKED MODEL Ensemble+CAP{CAPMULT} | baseline rate {rmean:.2f}/h -> cap {CAPMULT*rmean:.2f}/h | {len(pr)} priors")

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
    t=bar/1000.0; elapsed=(t-s)/3600.0; cp=elapsed/total
    if elapsed<3 or elapsed>total-0.3: continue
    o=obs(s,int(t)); rh=total-elapsed
    kal=o+(rmean+Kk*(o/elapsed-rmean))*rh
    acc=o/share[min(len(share)-1,max(0,int(elapsed)-1))]
    ens=(1-cp)*kal+cp*acc
    our=o+min((ens-o)/max(rh,.1), CAPMULT*rmean)*rh              # <-- LOCKED: Ensemble + CAP1.5
    prices={b:grid.loc[bar,b] for b in brs if pd.notna(grid.loc[bar,b]) and grid.loc[bar,b]>0}
    tot=sum(prices.values())
    if tot<=0: continue
    mkt=sum(center(*brs[b])*(p/tot) for b,p in prices.items())
    div=our-mkt; target=next((b for b,(lo,hi) in brs.items() if lo<=round(our)<=hi),None)
    def rec(act,b,px_,reason):
        trades.append({'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'action':act,'bracket':b,
            'was_winner':'WINNER' if b==WINNER else 'loser','tweets_so_far':o,'our_pace':round(our,1),
            'market_pace':round(mkt,1),'divergence':round(div,1),'bracket_price':round(px_,3) if px_==px_ else None,'why':reason})
    action=''
    if pos is None:
        if abs(div)>=ENTER and target and target in prices:
            pos={'b':target}; action='BUY'; rec('BUY',target,prices[target],f"our pace {our:.0f} vs market {mkt:.0f}, edge {abs(div):.0f}")
    else:
        held=pos['b']; hp=prices.get(held,float('nan'))
        if abs(div)<=EXIT or target!=held:
            rec('SELL',held,hp,('divergence converged (<=%.0f)'%EXIT) if abs(div)<=EXIT else f"pace moved to {target}"); pos=None; action='SELL'
            if target and target in prices and abs(div)>=ENTER:
                pos={'b':target}; rec('BUY',target,prices[target],f"rotate to {target}")
    rows.append({'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'hrs_in':round(elapsed,1),'tweets_so_far':o,
        'our_pace(locked)':round(our,1),'market_pace(revpace)':round(mkt,1),'divergence':round(div,1),
        'pace_points_to':target,'holding':pos['b'] if pos else '','action':action,'true_final':FINAL,'true_winner':WINNER})
td=pd.DataFrame(trades); series=pd.DataFrame(rows)
td.to_csv(f"{OUT}/signals_locked.csv",index=False); series.to_csv(f"{OUT}/timeline_locked.csv",index=False)
buys=td[td.action=='BUY']
print(f"\nSIGNALS: {len(td)} orders ({len(buys)} BUY, {len(td[td.action=='SELL'])} SELL) across {len(series)} bars")
print(f"our pace range: {series['our_pace(locked)'].min():.0f} - {series['our_pace(locked)'].max():.0f}   (was 110-311 raw, 66-185 ensemble; TRUE final {FINAL})")
print(f"market pace range: {series['market_pace(revpace)'].min():.0f} - {series['market_pace(revpace)'].max():.0f}")
if len(buys):
    hit=(buys.was_winner=='WINNER').sum()
    print(f"\nSTRATEGY TEST (no fills): {hit}/{len(buys)} BUYs were on the bracket that actually WON ({100*hit/len(buys):.0f}%)")
    print(f"  brackets bought: {buys.bracket.value_counts().to_dict()}")
# how often our pace beat the market's pace (closer to the truth)
series['our_err']=(series['our_pace(locked)']-FINAL).abs(); series['mkt_err']=(series['market_pace(revpace)']-FINAL).abs()
win=(series.our_err<series.mkt_err).mean()
print(f"\nWHOSE PACE WAS CLOSER TO THE TRUTH ({FINAL})? ours beat market on {100*win:.0f}% of bars")
for lab,m in [('first 12h',series.hrs_in<=12),('12-36h',(series.hrs_in>12)&(series.hrs_in<=36)),('last 12h',series.hrs_in>36)]:
    sub=series[m]
    if len(sub): print(f"  {lab:<10} ours {sub.our_err.mean():>6.1f} avg err | market {sub.mkt_err.mean():>6.1f} | ours closer on {100*(sub.our_err<sub.mkt_err).mean():>3.0f}% of bars")
print(f"\nWROTE {OUT}/signals_locked.csv + timeline_locked.csv")
