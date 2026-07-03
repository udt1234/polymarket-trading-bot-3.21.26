"""
Step 1 of the model-driven noovd backtest: VALIDATE the counting window + post data.

The Poisson model is only as good as (a) the official noon-ET counting window and
(b) the completeness of counts_for_auction posts inside it. Before trusting any
model probability, prove that counting posts in our parsed window lands in the
KNOWN winning_bucket. winning_bucket is used here ONLY to score the parser/data,
never as a model input.
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

CANON = Path("_DataMetricPulls/canonical")
ET = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}


def parse_bucket(b):
    b = str(b).strip()
    if b.startswith("<"):
        return (0, int(re.findall(r"\d+", b)[0]) - 1)
    if b.endswith("+"):
        return (int(re.findall(r"\d+", b)[0]), 10**9)
    nums = re.findall(r"\d+", b)
    return (int(nums[0]), int(nums[1])) if len(nums) >= 2 else (None, None)


def parse_window(slug, ref_year):
    """Return (start_utc, end_utc) noon-ET, or None. ref_year from trade-derived start."""
    toks = slug.lower().replace("_", "-").split("-")
    # collect (month, day) pairs in order
    pairs, i = [], 0
    months_seen = []
    nums = []
    seq = []
    for t in toks:
        if t in MONTHS:
            seq.append(("m", MONTHS[t]))
        elif t.isdigit():
            seq.append(("d", int(t)))
    # monthly market: single month token, no day → skip (handled separately)
    md = []
    cur_month = None
    for kind, val in seq:
        if kind == "m":
            cur_month = val
        else:  # day
            if cur_month is not None and 1 <= val <= 31:
                md.append((cur_month, val))
    if len(md) < 2:
        return None  # need start and end day
    (m1, d1), (m2, d2) = md[0], md[-1]
    y1 = ref_year
    y2 = ref_year + 1 if m2 < m1 else ref_year  # dec->jan rollover
    try:
        s = datetime(y1, m1, d1, 12, 0, tzinfo=ET)
        e = datetime(y2, m2, d2, 12, 0, tzinfo=ET)
    except ValueError:
        return None
    if e <= s:
        return None
    return (pd.Timestamp(s).tz_convert("UTC"), pd.Timestamp(e).tz_convert("UTC"))


def main():
    for h in ["elonmusk", "realDonaldTrump"]:
        a = pd.concat([pd.read_parquet(x) for x in (CANON/"auctions"/h).glob("*.parquet")]).drop_duplicates("auction_slug")
        a = a[(a.confidence == "high") & (a.resolution_status == "resolved_yes")]
        p = pd.concat([pd.read_parquet(x) for x in (CANON/"posts"/h).glob("*.parquet")])
        p = p[p.counts_for_auction == True].sort_values("ts_utc")
        ts = pd.to_datetime(p.ts_utc, utc=True)

        hit = miss = noparse = 0
        rows = []
        for _, r in a.iterrows():
            ref_year = pd.to_datetime(r.start_et).year
            w = parse_window(r.auction_slug, ref_year)
            if w is None:
                noparse += 1
                continue
            s, e = w
            cnt = int(((ts >= s) & (ts < e)).sum())
            lo, hi = parse_bucket(r.winning_bucket)
            if lo is None:
                continue
            ok = lo <= cnt <= hi
            hit += ok
            miss += (not ok)
            rows.append(dict(slug=r.auction_slug, dur=r.duration_type,
                             days=round((e - s).total_seconds()/86400, 1),
                             counted=cnt, win=r.winning_bucket, ok=ok))
        df = pd.DataFrame(rows)
        n = hit + miss
        print("=" * 70)
        print(f"{h}: parsed {n}/{len(a)} auctions ({noparse} unparseable)")
        print(f"  window+data validates to winning_bucket: {hit}/{n} = {hit/n:.0%}" if n else "  none")
        if len(df):
            print("  misses (counted post-total NOT in winning bucket):")
            print(df[~df.ok].head(15).to_string(index=False))
            print("  sample hits:")
            print(df[df.ok].head(5).to_string(index=False))
            df.to_csv(CANON/"_backtests"/f"noovd_window_validate_{h}.csv", index=False)


if __name__ == "__main__":
    main()
