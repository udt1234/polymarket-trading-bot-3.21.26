"""Unified reader for our Polymarket L2 order-book history repository.

TWO redundant sources, ONE normalized schema (verified 100% match 2026-07-02):
  - 'pmxt'    : free archive.pmxt.dev backfill + forward, COMPLETE tick-level L2 for every market,
                2026-04-13 -> now. Dirs: _DataMetricPulls/l2_history/pmxt + _DataMetricPulls/pmxt_pulled.
                This is the COMPLETE history -> default source for backtests.
  - 'recorder': OUR OWN 24/7 Railway recorder (`tweet-recorder`), 2026-06-23 -> now, at
                _DataMetricPulls/recordings_pulled. Redundant copy so we never depend on a 3rd party.

Schema (both): recv_ts(sec float), ts(ms UTC int), event_type(book|price_change|last_trade_price|
tick_size_change), series, slug, bucket, outcome(YES|NO), asset_id, market(0x conditionId), price,
size, side, best_bid, best_ask, data(book depth JSON {"bids":[{price,size}],"asks":[...]}).
"""
import glob
from pathlib import Path
import duckdb
ROOT = Path(__file__).resolve().parents[3]
DM = ROOT / '_DataMetricPulls'
SRC = {'pmxt': [DM/'l2_history'/'pmxt', DM/'pmxt_pulled'], 'recorder': [DM/'recordings_pulled']}

def _files(source):
    dirs = SRC['pmxt'] + SRC['recorder'] if source == 'both' else SRC[source]
    return [f for d in dirs for f in glob.glob(str(d/'*.parquet'))]

def read_l2(tokens=None, since_ms=None, until_ms=None, event_types=None, series=None, source='pmxt', cols='*'):
    """Filtered read across the L2 repository. ALWAYS pass tokens and/or a time range; the files
    are huge. Returns a pandas DataFrame (or None if the repo is empty)."""
    files = _files(source)
    if not files:
        return None
    arr = '[' + ','.join("'" + f.replace('\\', '/') + "'" for f in files) + ']'
    w = []
    if tokens: w.append("asset_id IN (" + ','.join("'" + str(t) + "'" for t in tokens) + ")")
    if since_ms is not None: w.append(f"ts >= {int(since_ms)}")
    if until_ms is not None: w.append(f"ts < {int(until_ms)}")
    if event_types: w.append("event_type IN (" + ','.join("'" + e + "'" for e in event_types) + ")")
    if series: w.append("series IN (" + ','.join("'" + s + "'" for s in series) + ")")
    where = ' AND '.join(w) or 'TRUE'
    return duckdb.connect().execute(f"SELECT {cols} FROM read_parquet({arr}) WHERE {where}").df()

def coverage(source='both'):
    """{source: {files, rows, min_ts, max_ts}} so we always know what the repository holds."""
    out = {}
    for src in (['pmxt', 'recorder'] if source == 'both' else [source]):
        files = _files(src)
        if not files:
            out[src] = {'files': 0}; continue
        arr = '[' + ','.join("'" + f.replace('\\', '/') + "'" for f in files) + ']'
        r = duckdb.connect().execute(f"SELECT count(*) n, min(ts) mn, max(ts) mx FROM read_parquet({arr})").fetchone()
        out[src] = {'files': len(files), 'rows': int(r[0]), 'min_ts': r[1], 'max_ts': r[2]}
    return out
