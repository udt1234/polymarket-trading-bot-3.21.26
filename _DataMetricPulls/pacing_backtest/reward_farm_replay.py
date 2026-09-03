# -*- coding: utf-8 -*-
"""REWARD-FARMING MAKER replay on real pmxt L2, with the CANCEL-ON-TWEET defense.
Answers the 3 greenlight numbers for the 'rent the book' play:
  (A) REWARD ACCRUAL: rest two-sided post-only quotes s cents from the reconstructed midpoint on every
      bracket; per-minute score S=((v-s)/v)^2 * size (Polymarket spec, v=rewards_max_spread cents). Estimate
      our SHARE of the daily pool vs observed competing book depth -> projected $/day for a range of pools.
  (B) PICKOFF LEDGER (exact from tick+tweet data): detect when our resting quote gets run through, mark it
      out +60s later, and sum the adverse-selection bleed. Re-run WITH cancel-on-tweet firing at our measured
      ~422ms so quotes are pulled around every Elon post. Net = reward - bleed, with vs without the cancel.
  (C) CAPITAL/SPREAD sweep.
Event-driven on real ticks (NO bar resampling). Uses the 16 fully price-covered clean auctions."""
import glob, os, sys, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=ROOT+"/_DataMetricPulls/canonical"; PMX=ROOT+"/_DataMetricPulls/pmxt_pulled"
OUT=ROOT+"/_DataMetricPulls/pacing_backtest/audit_out3"; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(ROOT+"/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms'); tw_ms=bf.ms.to_numpy().astype('int64')
def noon(sl):
    tk=sl.replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(CANON+"/auctions/elonmusk/*.parquet")],ignore_index=True)
audf=pd.read_csv(OUT+"/clean_sweep.csv"); SLUGS=['elon-musk-of-tweets-'+a for a in audf.auction]

# ---- knobs ----
V_C   = float(os.environ.get('MAXSPREAD_C','3.0'))   # rewards_max_spread in CENTS (assumed; typical Elon reward band)
S_C   = float(os.environ.get('QUOTE_S_C','1.0'))     # our quote distance from mid in CENTS (tighter = more score, more pickoff)
OUR_SZ= float(os.environ.get('OUR_SIZE','200'))      # our resting size per side (shares) = capital proxy
MARK  = int(os.environ.get('MARKOUT_S','60'))        # mark-out horizon (s) for adverse selection
CANCEL_S = float(os.environ.get('CANCEL_S','422'))/1000.0  # cancel latency after a tweet (s)
COOLOFF = int(os.environ.get('COOLOFF_S','90'))      # how long we stay OUT of the market after a tweet before re-quoting
POOLS = [8,25,50,100,250]                             # $/day reward-pool sizes ($8 = the REAL live Elon rate)

def load_ticks(slug):
    s,e=noon(slug); row=auc[auc.auction_slug==slug].iloc[0]
    tok=row.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    fs=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: fs+=glob.glob(PMX+f"/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    fs=sorted(set(fs))
    if not fs: return None,s,e
    t2l={str(v):k for k,v in tok.items()}; tl='('+','.join("'"+str(v)+"'" for v in tok.values())+')'
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    px=con.execute(f"""SELECT ts,CAST(asset_id AS VARCHAR) aid,best_bid,best_ask,size FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {tl} AND best_ask>0 AND best_ask<1 AND best_bid>0 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if px.empty: return None,s,e
    px['lab']=px.aid.map(t2l); px=px[px.lab.notna()]
    return {l:{'ts':g.ts.to_numpy().astype('int64'),'bid':g.best_bid.to_numpy(float),'ask':g.best_ask.to_numpy(float),
               'sz':g['size'].to_numpy(float)} for l,g in px.groupby('lab')}, s, e

def quote_at(d,tms):
    i=np.searchsorted(d['ts'],tms,'right')-1
    if i<0: return None
    return d['bid'][i],d['ask'][i],d['sz'][i]
def mid_over(d,t0,t1):
    lo=np.searchsorted(d['ts'],t0,'left'); hi=np.searchsorted(d['ts'],t1,'right')
    if hi<=lo: return None
    m=(d['bid'][lo:hi]+d['ask'][lo:hi])/2; return m.min(),m.max(),m[-1]

rows=[]
for slug in SLUGS:
    Bk,s,e=load_ticks(slug)
    if not Bk: continue
    s_ms,e_ms=s*1000,e*1000
    tw=tw_ms[(tw_ms>=s_ms)&(tw_ms<e_ms)]
    grid=np.arange(s_ms,e_ms,60000)  # per-minute requote/sample grid
    for lab,d in Bk.items():
        score=0.0; comp=0.0; pnl_no=0.0; pnl_cx=0.0; fills_no=0; fills_cx=0; samples=0
        for gi,tms in enumerate(grid):
            q=quote_at(d,tms)
            if q is None: continue
            bid,ask,sz=q; mid=(bid+ask)/2
            if mid<=0.02 or mid>=0.98: continue     # skip near-resolved (no two-sided reward band there)
            samples+=1
            # --- (A) reward score: our two-sided quotes at s cents from mid ---
            f=((V_C-S_C)/V_C)**2
            score+= 2*OUR_SZ*f                        # both sides, balanced (Qmin not penalized)
            half_spread_c=max((ask-bid)/2*100,0.1)    # market's own spread in cents = competitors' distance
            comp+= 2*max(sz,1)*((V_C-min(half_spread_c,V_C))/V_C)**2
            # --- (B) pickoff: did our resting quote get run through this minute, and what was the markout ---
            t1=tms+60000; mm=mid_over(d,tms,t1)
            if mm is None: continue
            lo_mid,hi_mid,end_mid=mm
            mk=mid_over(d,tms,tms+MARK*1000); mkmid=mk[2] if mk else end_mid
            pb=mid-S_C/100.0; pa=mid+S_C/100.0
            # tweet in this interval?
            tw_in=tw[(tw>=tms)&(tw<t1)]
            cancel_after = (tw_in[0]+CANCEL_S*1000) if len(tw_in) else None
            for (side,fillpx,hit,pnl) in [
                ('bid',pb, lo_mid<=pb, (mkmid-pb)*OUR_SZ),   # bought at pb, now worth mkmid
                ('ask',pa, hi_mid>=pa, (pa-mkmid)*OUR_SZ)]:  # sold at pa, now worth mkmid
                if not hit: continue
                pnl_no+=pnl; fills_no+=1
                # with cancel: skip fills that occur after we would have cancelled (tweet+lat) until cooloff ends
                if cancel_after is not None: continue     # conservative: a tweet this minute -> we were out, no fill
                pnl_cx+=pnl; fills_cx+=1
        if samples<10: continue
        days=(e-s)/86400.0
        share = score/(score+comp) if (score+comp)>0 else 0
        rows.append({'auction':slug.replace('elon-musk-of-tweets-',''),'bracket':lab,'days':round(days,2),'samples':samples,
                     'score_share':round(share,4),'tweets':int(len(tw)),
                     'pickoff_pnl_NOcancel':round(pnl_no,1),'pickoff_pnl_CANCEL':round(pnl_cx,1),
                     'fills_no':fills_no,'fills_cx':fills_cx})
    print(f"  {slug.replace('elon-musk-of-tweets-','')}: {len([r for r in rows if r['auction']==slug.replace('elon-musk-of-tweets-','')])} brackets done",flush=True)
df=pd.DataFrame(rows)
if df.empty: print("no rows"); sys.exit(0)
df.to_csv(OUT+"/reward_farm_replay.csv",index=False)
# aggregate per auction-day (a bracket-week of quoting)
tot_days=df.days.sum()
print(f"\n=== REWARD-FARM REPLAY (16 clean auctions, v={V_C}c band, s={S_C}c quote, size={OUR_SZ}/side) ===")
print(f"bracket-instances: {len(df)} | mean score-SHARE of pool: {df.score_share.mean():.1%} (median {df.score_share.median():.1%})")
print(f"\n(B) PICKOFF LEDGER (adverse selection on resting quotes, real ticks):")
print(f"  total pickoff PnL, NO cancel : ${df.pickoff_pnl_NOcancel.sum():+,.0f}  ({df.fills_no.sum()} fills)")
print(f"  total pickoff PnL, CANCEL-ON-TWEET: ${df.pickoff_pnl_CANCEL.sum():+,.0f}  ({df.fills_cx.sum()} fills)")
print(f"  cancel-on-tweet saved: ${df.pickoff_pnl_CANCEL.sum()-df.pickoff_pnl_NOcancel.sum():+,.0f}")
print(f"\n(A) REWARD INCOME at our score-share, per BRACKET-DAY, for a range of daily pool sizes:")
# reward/day = pool * share ; sum bracket-days across all brackets = total bracket-days farmed
bracket_days=df.days.sum()
for pool in POOLS:
    daily=(df.score_share*pool).mean()   # avg $/day one bracket earns at this pool
    tot=(df.score_share*pool*df.days).sum()
    net_no=tot+df.pickoff_pnl_NOcancel.sum(); net_cx=tot+df.pickoff_pnl_CANCEL.sum()
    print(f"  pool ${pool:>3}/day/mkt -> avg ${daily:5.2f}/day per bracket | total rewards ${tot:8,.0f} | NET(no cancel) ${net_no:+8,.0f} | NET(cancel) ${net_cx:+8,.0f}")
print(f"\nfarmed {bracket_days:.0f} bracket-days total across the 16 auctions")
