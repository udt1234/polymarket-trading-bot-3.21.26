"""Keep the pmxt L2 archive current for FUTURE auctions. Finds the latest hour already archived
(across l2_history/pmxt + pmxt_pulled), then pulls every complete hour since then up to (now - 2h)
into l2_history/pmxt. Idempotent. Scheduled daily; runs ALONGSIDE our own recorder."""
import subprocess, sys, glob, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT = ROOT/'_DataMetricPulls'/'l2_history'/'pmxt'
DIRS = [OUT, ROOT/'_DataMetricPulls'/'pmxt_pulled']

def latest_hour():
    hrs = []
    for d in DIRS:
        for f in glob.glob(str(d/'pmxt_tweets_*.parquet')):
            m = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2})', f)
            if m: hrs.append(m.group(1))
    return max(hrs) if hrs else None

def main():
    dry = '--dry' in sys.argv
    lh = latest_hour()
    end = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    start = (datetime.strptime(lh, '%Y-%m-%dT%H').replace(tzinfo=timezone.utc) + timedelta(hours=1)) if lh else end - timedelta(hours=48)
    print(f"latest archived hour: {lh}  -> forward pull {start:%Y-%m-%dT%H} .. {end:%Y-%m-%dT%H} ({int((end-start).total_seconds()//3600)+1} hours)")
    if start > end:
        print("archive current, nothing to pull"); return
    if dry:
        print("(dry run, not pulling)"); return
    subprocess.run([sys.executable, '-u', str(ROOT/'scripts'/'pmxt'/'pull_pmxt_l2.py'),
                    '--start', start.strftime('%Y-%m-%dT%H'), '--end', end.strftime('%Y-%m-%dT%H'),
                    '--out', str(OUT)], cwd=str(ROOT))

if __name__ == '__main__':
    main()
