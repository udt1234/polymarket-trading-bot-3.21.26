"""Pull Polymarket L2 order-book HISTORY for OUR tweet markets from the free pmxt archive
(https://r2v2.pmxt.dev, one parquet per UTC hour), filtered to our condition IDs, and normalize
it to the SAME schema our recorder writes (scripts/recorder/tweet_market_recorder.py) so any
backtest can read pmxt and recorder data interchangeably.

pmxt schema -> recorder schema mapping:
  timestamp_received (ts[ms,UTC]) -> recv_ts (Unix SECONDS, float)
  timestamp          (ts[ms,UTC]) -> ts       (Unix MILLISECONDS, int)  [same clock as recorder]
  market (0x conditionId)         -> market
  asset_id (decimal str)          -> asset_id
  event_type/price/size/side/best_bid/best_ask -> same
  bids/asks JSON [["p","s"],..]   -> data = {"bids":[{"price":p,"size":s},..],"asks":[..]}  (book events only)
  series/slug/bucket/outcome      -> enriched from the recorder tokenmap by asset_id

Usage: python -u scripts/pmxt/pull_pmxt_l2.py --start 2026-06-29T18 --end 2026-06-29T20
"""
import sys, os, json, argparse, glob
from datetime import datetime, timedelta, timezone
from pathlib import Path
import duckdb, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
REC=ROOT/'_DataMetricPulls'/'recordings_pulled'
CANON=ROOT/'_DataMetricPulls'/'canonical'
OUT=ROOT/'_DataMetricPulls'/'l2_history'/'pmxt'; OUT.mkdir(parents=True, exist_ok=True)
BASE='https://r2v2.pmxt.dev/polymarket_orderbook_{hour}.parquet'
REC_COLS=['recv_ts','ts','event_type','series','slug','bucket','outcome','asset_id','market','price','size','side','best_bid','best_ask','data']

def load_cond_and_meta():
    con=duckdb.connect()
    recfiles=[str(p).replace(os.sep,'/') for p in REC.glob('*.parquet')]
    cond=set(); meta={}
    if recfiles:
        arr='['+','.join("'"+f+"'" for f in recfiles)+']'
        d=con.execute(f"SELECT DISTINCT asset_id, market, series, slug, bucket, outcome FROM read_parquet({arr})").fetchdf()
        for _,r in d.iterrows():
            if isinstance(r['market'],str) and r['market'].startswith('0x'): cond.add(r['market'])
            meta[str(r['asset_id'])]={'series':r['series'],'slug':r['slug'],'bucket':r['bucket'],'outcome':r['outcome']}
    # historical condition IDs from canonical (covers pre-recorder Apr-Jun)
    for f in glob.glob(str(CANON/'auctions'/'elonmusk'/'2026-0[4-7].parquet')):
        try:
            a=pd.read_parquet(f)
            for col in ['bracket_condition_ids','winner_condition_id']:
                if col not in a.columns: continue
                for v in a[col].dropna():
                    if isinstance(v,str) and v.startswith('{'):
                        try: cond.update(x for x in json.loads(v).values() if isinstance(x,str) and x.startswith('0x'))
                        except: pass
                    elif isinstance(v,str) and v.startswith('0x'): cond.add(v)
        except Exception as e: print('canon skip',f,e)
    return cond, meta

def cast_ok(con,url):
    try:
        v=con.execute(f"SELECT CAST(market AS VARCHAR) FROM read_parquet('{url}') LIMIT 1").fetchone()[0]
        return isinstance(v,str) and v.startswith('0x')
    except Exception: return False

def to_recorder_data(bids,asks):
    def conv(j):
        try: arr=json.loads(j) if j else []
        except: arr=[]
        return [{'price':p,'size':s} for p,s in arr]
    return json.dumps({'bids':conv(bids),'asks':conv(asks)})

def pull_hour(con, hour, cond, meta, use_market):
    url=BASE.format(hour=hour)
    outp=OUT/f'pmxt_tweets_{hour}.parquet'
    if outp.exists(): print(f'  {hour}: exists, skip'); return None
    if use_market:
        idl=','.join("'"+c+"'" for c in cond)
        where=f"CAST(market AS VARCHAR) IN ({idl})"
    else:
        toks=list(meta.keys()); idl=','.join("'"+t+"'" for t in toks)
        where=f"asset_id IN ({idl})"
    q=f"""SELECT epoch_ms(timestamp_received)/1000.0 AS recv_ts, epoch_ms("timestamp") AS ts,
        event_type, CAST(market AS VARCHAR) AS market, asset_id,
        CAST(price AS DOUBLE) AS price, CAST(size AS DOUBLE) AS size, side,
        CAST(best_bid AS DOUBLE) AS best_bid, CAST(best_ask AS DOUBLE) AS best_ask, bids, asks
        FROM read_parquet('{url}') WHERE {where}"""
    try:
        df=con.execute(q).fetchdf()
    except Exception as e:
        print(f'  {hour}: ERROR/missing ({str(e)[:80]})'); return None
    if not len(df): print(f'  {hour}: 0 rows'); return outp
    df['series']=df['asset_id'].map(lambda a:(meta.get(str(a)) or {}).get('series'))
    df['slug']=df['asset_id'].map(lambda a:(meta.get(str(a)) or {}).get('slug'))
    df['bucket']=df['asset_id'].map(lambda a:(meta.get(str(a)) or {}).get('bucket'))
    df['outcome']=df['asset_id'].map(lambda a:(meta.get(str(a)) or {}).get('outcome'))
    isbook=df['event_type']=='book'
    df['data']=None
    df.loc[isbook,'data']=[to_recorder_data(b,a) for b,a in zip(df.loc[isbook,'bids'],df.loc[isbook,'asks'])]
    df=df[REC_COLS]
    df.to_parquet(outp,index=False)
    print(f'  {hour}: {len(df):,} rows -> {outp.name}  ({df.event_type.value_counts().to_dict()})')
    return outp

def main():
    global OUT
    ap=argparse.ArgumentParser(); ap.add_argument('--start',required=True); ap.add_argument('--end',required=True)
    ap.add_argument('--out',default=str(OUT))
    a=ap.parse_args()
    OUT=Path(a.out); OUT.mkdir(parents=True,exist_ok=True)
    cond,meta=load_cond_and_meta()
    print(f'condition IDs: {len(cond)} | token->meta entries: {len(meta)}')
    con=duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
    t0=datetime.strptime(a.start,'%Y-%m-%dT%H').replace(tzinfo=timezone.utc)
    t1=datetime.strptime(a.end,'%Y-%m-%dT%H').replace(tzinfo=timezone.utc)
    um=cast_ok(con, BASE.format(hour=a.start))
    print(f'market-cast pushdown available: {um} (else asset_id filter)')
    h=t0
    while h<=t1:
        pull_hour(con, h.strftime('%Y-%m-%dT%H'), cond, meta, um)
        h+=timedelta(hours=1)

if __name__=='__main__': main()
