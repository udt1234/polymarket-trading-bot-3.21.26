"""Run one recurring Polymarket job on the HP Laptop, log it, DM Sir on failure.

Usage: run_job.py recorder-pull | foretest
Installed by deploy.py to /srv/polymarket/run_job.py and fired by systemd user timers.
"""
import datetime
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path("/srv/polymarket")
BOT = ROOT / "PolyMarket_Bot"
PY = str(ROOT / "venv/bin/python")
PULL = str(ROOT / "polymarket-tweet-recorder/pull_and_merge.py")
THIN = "https://tweet-recorder-thin-production.up.railway.app"
JOBS = {
    "recorder-pull": [
        ("main_pull", [PULL, "--prune"], 14400),
        ("thin_pull", [PULL, "--url", THIN, "--name", "thin", "--prune"], 14400),
    ],
    "foretest": [("shadow_foretest", [str(BOT / "scripts/foretest/shadow_foretest.py"), "--auto"], 3600)],
}
SENTINEL = ("elon-tweets", "elon-tweets-48h")


def slack(text):
    tok = os.environ["SLACK_BOT_TOKEN"]

    def call(method, body):
        req = urllib.request.Request(
            "https://slack.com/api/" + method, json.dumps(body).encode(),
            {"Authorization": "Bearer " + tok, "Content-Type": "application/json; charset=utf-8"})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        if not r.get("ok"):
            raise RuntimeError(r.get("error"))
        return r

    ch = call("conversations.open", {"users": os.environ["SLACK_DM_USER"]})["channel"]["id"]
    call("chat.postMessage", {"channel": ch, "text": text, "unfurl_links": False})


def sentinel():
    import pyarrow.parquet as pq
    day = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y%m%d")
    bad = []
    for s in SENTINEL:
        f = BOT / "_DataMetricPulls/recordings_pulled" / f"{s}.parquet" / f"{day}.parquet"
        try:
            ok = f.exists() and pq.ParquetFile(f).metadata.num_rows > 0
        except Exception:
            ok = False
        if not ok:
            bad.append(s)
    return f"no {day} rows for {', '.join(bad)}" if bad else None


def main():
    job = sys.argv[1]
    (ROOT / "logs").mkdir(exist_ok=True)
    lock = open(ROOT / ".job.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    fails = []
    with open(ROOT / "logs" / f"{job}.log", "a") as log:
        log.write(f"\n==== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} {job} ====\n")
        for name, argv, timeout in JOBS[job]:
            log.write(f"-- {name}\n")
            log.flush()
            t0 = time.time()
            try:
                code = subprocess.run([PY, "-u", "-W", "ignore"] + argv, cwd=BOT, stdout=log,
                                      stderr=subprocess.STDOUT, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
            log.write(f"[{'ok' if code == 0 else 'FAIL'}] {name} exit={code} {int(time.time() - t0)}s\n")
            if code != 0:
                fails.append(f"{name} (exit {code})")
        if job == "recorder-pull":
            miss = sentinel()
            if miss:
                fails.append(miss)
                log.write(f"[FAIL] sentinel: {miss}\n")
        log.write(f"==== done, failed: {', '.join(fails) or 'none'} ====\n")
        if fails:
            try:
                slack(f"HP Laptop polymarket `{job}` failed: {'; '.join(fails)}. Log: {log.name}")
                log.write("slack delivered=true\n")
            except Exception as e:
                log.write(f"slack delivered=false {e!r}\n")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
