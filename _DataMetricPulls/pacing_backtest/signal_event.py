# -*- coding: utf-8 -*-
"""EVENT-DRIVEN divergence strategy on ONE auction (april-16-april-18). NOT 10-min bars.
Processes EVERY tweet (recompute our center) and EVERY price_change tick (update the market's center),
in true time order, exactly like the live bot would. ~800k events. Signals only, no P&L claim beyond
the conservative maker fills. Locked pace = Ens+CAP1.5. Gate hour 24+."""
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
def share_wf(dh,bt):
    n0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=n0; cv=[]
    while d.timestamp()+dh*3600<=bt:
        ss=int(d.timestamp()); ee=ss+dh*3600; f=obs(ss,ee)
        if f>=5: cv.append(np.array([obs(ss,ss+h*3600) for h in range(1,dh+1)],float)/f)
        d=d+pd.Timedelta(days=1)
    return np.clip(np.median(np.vstack(cv),axis=0),1e-3,1.0) if cv else None
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs

SLUG='elon-musk-of-tweets-april-16-april-18'; CAPMULT=1.5; ENTER=5.0; EXIT=2.0; STOP=0.06; HAIRCUT=0.01; GATE_H=24.0; BANK=5394.0; STAKE=0.02*BANK
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
row=auc[auc.auction_slug==SLUG].iloc[0]; yr=row['start_utc'].year
s=int(pd.Timestamp(datetime(yr,4,16,12,tzinfo=ET)).timestamp()); e=int(pd.Timestamp(datetime(yr,4,18,12,tzinfo=ET)).timestamp()); total=(e-s)/3600
t2b={t:l for l,t in json.loads(row.bracket_yes_token_ids).items() if isinstance(t,str) and t.isdigit() and len(t)>18 and pbk(l)}
W=str(row.winning_bucket); FINAL=obs(s,e)
brks=sorted(set(t2b.values())); bidx={b:i for i,b in enumerate(brks)}; nbr=len(brks)
cen=np.array([center(*pbk(b)) for b in brks])
# priors (all 2-day before s)
prior=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day': continue
    tk=a.auction_slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y=a['start_utc'].year; y2=y+(1 if mo2<mo1 else 0)
        ws=int(pd.Timestamp(datetime(y,mo1,d1,12,tzinfo=ET)).timestamp()); we=int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp())
    except: continue
    if we>=s or we<=ws: continue
    prior.append(obs(ws,we)/((we-ws)/3600))
rmean=float(np.mean(prior)); Pk=np.var(prior)+.01; Kk=(Pk+.01)/(Pk+.01+max(.1,Pk*.5)); share=share_wf(48,s)
print(f"{SLUG} | winner {W} | final {FINAL} | baseline {rmean:.2f}/h | {len(prior)} priors")

files=l2files(s,e); arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in t2b)+")"
px=q(f"""SELECT ts, asset_id, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""")
px['bi']=px.asset_id.astype(str).map(lambda t:bidx.get(t2b.get(t))).astype('Int64')
px=px.dropna(subset=['bi'])
bk=q(f'SELECT asset_id,CAST("data" AS VARCHAR) AS "data" FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type=\'book\'')
bk['b']=bk.asset_id.astype(str).map(lambda t:t2b.get(t)); depth={}
for b in brks:
    ds=[]
    for d in bk[bk.b==b].data.dropna():
        try: aa=json.loads(d)['asks'][:2]; ds.append(sum(float(x['price'])*float(x['size']) for x in aa))
        except: pass
    depth[bidx[b]]=float(np.median(ds)) if ds else 30.0
# merge price ticks + tweets into one time-ordered event stream
ts_p=(px.ts.to_numpy()//1000).astype('int64'); bi_p=px.bi.to_numpy().astype(int); bid_p=px.best_bid.to_numpy(float); ask_p=px.best_ask.to_numpy(float)
tw=pts[(pts>=s)&(pts<e)]
ts_all=np.concatenate([ts_p,tw]); typ=np.concatenate([np.zeros(len(ts_p),int),np.ones(len(tw),int)])
order=np.argsort(ts_all,kind='stable'); ts_all=ts_all[order]; typ=typ[order]
bi_all=np.concatenate([bi_p,-np.ones(len(tw),int)])[order]; bid_all=np.concatenate([bid_p,np.zeros(len(tw))])[order]; ask_all=np.concatenate([ask_p,np.zeros(len(tw))])[order]
print(f"event stream: {len(ts_all):,} events ({len(ts_p):,} price ticks + {len(tw)} tweets)")

book_bid=np.zeros(nbr); book_ask=np.zeros(nbr); o=0
pos=None; pend_bid=None; pend_ask=None; pnl=0.0; cap=0.0; nb=0
TR=[]; TL=[]; last_o=-1
def ets(t): return datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M:%S')
for i in range(len(ts_all)):
    t=ts_all[i]
    if typ[i]==1: o+=1
    else: book_bid[bi_all[i]]=bid_all[i]; book_ask[bi_all[i]]=ask_all[i]
    eh=(t-s)/3600.0; rh=total-eh
    if eh<2 or rh<0.15: continue
    mask=book_ask>0; tot=book_ask[mask].sum()
    if tot<=0: continue
    mkt=float((cen[mask]*book_ask[mask]).sum()/tot)
    kal=o+(rmean+Kk*(o/eh-rmean))*rh; acc=o/share[min(len(share)-1,max(0,int(eh)-1))]
    ens=(1-eh/total)*kal+(eh/total)*acc; our=o+min((ens-o)/max(rh,.1),CAPMULT*rmean)*rh
    div=our-mkt; tgt=next((k for k in range(nbr) if pbk(brks[k])[0]<=round(our)<=pbk(brks[k])[1]),None)
    # ---- maker fills ----
    if pend_bid is not None:
        b,bp=pend_bid
        if book_ask[b]>0 and book_ask[b]<=bp+1e-12:
            sh=min(STAKE,depth[b])/bp; pos={'b':b,'px':bp,'sh':sh}; cap+=min(STAKE,depth[b]); nb+=1; pend_bid=None
            TR.append({'et':ets(t),'hrs':round(eh,2),'action':'BUY','bracket':brks[b],'won':'WINNER' if brks[b]==W else 'loser','fill':round(bp,4),'shares':round(sh,1),'tweets':o,'our':round(our,1),'mkt':round(mkt,1),'div':round(div,1),'why':f'maker bid filled (ask crossed to {bp:.3f})'})
    if pos is not None and pend_ask is not None:
        if book_bid[pos['b']]>=pend_ask-1e-12:
            pxx=max(0.0,pend_ask-HAIRCUT); pnl+=pos['sh']*(pxx-pos['px'])
            TR.append({'et':ets(t),'hrs':round(eh,2),'action':'SELL','bracket':brks[pos['b']],'won':'WINNER' if brks[pos['b']]==W else 'loser','fill':round(pxx,4),'shares':round(pos['sh'],1),'tweets':o,'our':round(our,1),'mkt':round(mkt,1),'div':round(div,1),'why':'maker ask filled (bid crossed up)'})
            pos=None; pend_ask=None
    # ---- decision (gate hour 24+) ----
    if eh>=GATE_H:
        if pos is None:
            want=(abs(div)>=ENTER and tgt is not None and book_ask[tgt]>0 and book_bid[tgt]>0)
            if pend_bid is not None and (not want or pend_bid[0]!=tgt): pend_bid=None
            if want and pend_bid is None: pend_bid=(tgt,float(book_bid[tgt]))
        else:
            b=pos['b']
            if book_bid[b]>0 and book_bid[b]<=pos['px']-STOP:
                pxx=max(0.0,book_bid[b]-HAIRCUT); pnl+=pos['sh']*(pxx-pos['px'])
                TR.append({'et':ets(t),'hrs':round(eh,2),'action':'SELL','bracket':brks[b],'won':'WINNER' if brks[b]==W else 'loser','fill':round(pxx,4),'shares':round(pos['sh'],1),'tweets':o,'our':round(our,1),'mkt':round(mkt,1),'div':round(div,1),'why':'stop loss'})
                pos=None; pend_ask=None
            else:
                ex=(abs(div)<=EXIT or (tgt is not None and tgt!=b))
                if ex and pend_ask is None and book_ask[b]>0: pend_ask=float(book_ask[b])
                if not ex and pend_ask is not None: pend_ask=None
    # ---- timeline: log on every TWEET (shows per-tweet reaction) ----
    if typ[i]==1 and o!=last_o:
        TL.append({'et':ets(t),'hrs_in':round(eh,2),'tweet_no':o,'our_center':round(our,1),'d_center_per_tweet':round(our-(TL[-1]['our_center'] if TL else our),1),
            'market_center':round(mkt,1),'divergence':round(div,1),'our_bracket':brks[tgt] if tgt is not None else '','holding':brks[pos['b']] if pos else ''})
        last_o=o
if pos is not None:
    b=pos['b']; pxx=max(0.0,book_bid[b]-HAIRCUT); pnl+=pos['sh']*(pxx-pos['px'])
    TR.append({'et':ets(ts_all[-1]),'hrs':round(total,2),'action':'SELL','bracket':brks[b],'won':'WINNER' if brks[b]==W else 'loser','fill':round(pxx,4),'shares':round(pos['sh'],1),'tweets':o,'our':None,'mkt':None,'div':None,'why':'flatten at close'})
tr=pd.DataFrame(TR); tl=pd.DataFrame(TL)
tr.to_csv(f"{OUT}/event_trades.csv",index=False); tl.to_csv(f"{OUT}/event_timeline.csv",index=False)
buys=tr[tr.action=='BUY']
print(f"\nEVENT-DRIVEN RESULT (gate hour 24+):")
print(f"  {len(tr)} orders ({len(buys)} BUY, {len(tr)-len(buys)} SELL)  vs the old 10-min-bar run's ~14")
print(f"  deployed ${cap:,.0f} | P&L ${pnl:+,.0f} | ROI {100*pnl/cap if cap else 0:+.1f}%")
if len(buys): print(f"  BUYs on eventual winner: {(buys.won=='WINNER').sum()}/{len(buys)}")
print(f"  per-tweet center reaction logged for all {len(tl)} tweets (see event_timeline.csv)")
if len(tl): print(f"  biggest single-tweet center move: {tl.d_center_per_tweet.abs().max():.1f} tweets")
