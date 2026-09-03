# -*- coding: utf-8 -*-
"""Split the pulled weather L2 recording into one parquet per market slug (YES side only).

The raw pull is ~10.5k chunk files -> ~150M rows; the replay needs random access by market.
One DuckDB pass per capture-day writes slug-partitioned parquet so the replay can load a
single market at a time (bounded memory, per the day-split parquet lesson).

Keeps: ts, recv_ts, event_type, price, size, side, best_bid, best_ask, and `data` (the full
L2 bids/asks JSON) only on `book` rows.

Usage: python weather_partition_by_slug.py
"""
import sys, glob, os
from pathlib import Path
import duckdb

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path("C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot")
SRC = ROOT / "_DataMetricPulls/weather_recordings/weather-temperature.parquet"
DST = ROOT / "_DataMetricPulls/weather_recordings/by_slug"
DST.mkdir(parents=True, exist_ok=True)

con = duckdb.connect()
con.execute("SET preserve_insertion_order=false")
con.execute("SET memory_limit='6GB'")
con.execute(f"SET temp_directory='{(ROOT / '_DataMetricPulls/weather_recordings/_duckdb_tmp').as_posix()}'")

days = sorted(p.name for p in SRC.iterdir() if p.is_dir())
print("days:", days, flush=True)

for day in days:
    files = sorted(glob.glob(str(SRC / day / "part_*.parquet")))
    if not files:
        continue
    arr = "[" + ",".join("'" + f.replace(os.sep, "/") + "'" for f in files) + "]"
    con.execute(f"""
        COPY (
          SELECT slug, ts, recv_ts, event_type, price, size, side, best_bid, best_ask,
                 CASE WHEN event_type='book' THEN data ELSE '' END AS data
          FROM read_parquet({arr}, union_by_name=true)
          WHERE outcome='YES' AND slug <> ''
        ) TO '{DST.as_posix()}'
        (FORMAT PARQUET, PARTITION_BY (slug), OVERWRITE_OR_IGNORE,
         FILENAME_PATTERN '{day}_{{i}}', COMPRESSION zstd)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet({arr}, union_by_name=true) WHERE outcome='YES'").fetchone()[0]
    print(f"  {day}: {n:,} YES rows -> partitioned", flush=True)

parts = list(DST.glob("slug=*"))
print(f"slugs written: {len(parts)}", flush=True)
