# -*- coding: utf-8 -*-
"""Minute-by-minute order-book + signal logger for an Elon tweet-count market.

Per bracket, every --secs (default 60): YES bid/ask, derived NO bid/ask, spread,
volume, take_both (lift both asks now), make_both (both resting bids fill = seesaw
target; <1 = locked margin), full-set sums.

Per cycle it also carries the SIGNAL columns (the decision context):
  window_count     running tweet count in the noon-ET window (X API, locked count rule)
  silence_min      minutes since his last counted post
  p_done           P(done | silent) = 1/(1+exp(-(-2.649+0.761*ln s)))  -> burst-flip risk
  count_age_sec    how stale the X count is (we poll X every --count-secs to limit cost)

COST NOTE: X API is pay-per-use. Count is polled every --count-secs (default 300s).
Book is polled every --secs (free, no auth). Use --no-count to log book only.

Usage:
  python scripts/elon_book_logger.py --slug <slug> [--secs 60] [--count-secs 300] [--minutes 0]
  python scripts/elon_book_logger.py --discover
Output: _DataMetricPulls/elon_schedule_analysis/book_log_<slug>.csv  (append, crash-safe)
"""
import argparse, csv, json, math, os, re, time, sys, datetime as dt
from collections import deque, defaultdict
from pathlib import Path
import httpx

GAMMA = "https://gamma-api.polymarket.com"
XAPI = "https://api.x.com/2"
ELON_ID = "44196397"
ROOT = Path(__file__).resolve().parents[1]
OUTDIR = ROOT / "_DataMetricPulls" / "elon_schedule_analysis"

def load_bearer():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\s*X_BEARER_TOKEN\s*=\s*(.+)\s*$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return os.environ.get("X_BEARER_TOKEN")

def p_done(silence_min):
    s = max(float(silence_min), 1.0)
    return round(1 / (1 + math.exp(-(-2.649 + 0.761 * math.log(s)))), 3)

def bucket_lohi(lbl):
    lbl = (lbl or "").strip()
    if lbl.startswith("<"):
        return (0, int(re.sub(r"\D", "", lbl)) - 1)
    if lbl.endswith("+"):
        return (int(re.sub(r"\D", "", lbl)), 10**9)
    if "-" in lbl:
        a, b = re.findall(r"\d+", lbl)[:2]
        return (int(a), int(b))
    return None

DEAD_THRESH = 0.45      # p_done above this = confirmed dead cluster
DECAY_MIN = 0.01        # yes_mid drop over the trailing window to call it "decaying"

def counts_for_auction(tw):
    """Locked rule: count originals + quotes + reposts + self-replies; drop pure replies."""
    refs = tw.get("referenced_tweets") or []
    types = {r.get("type") for r in refs}
    if "retweeted" in types or "quoted" in types:
        return True
    if "replied_to" in types:
        return tw.get("in_reply_to_user_id") == ELON_ID  # self-reply counts
    return True  # original

MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}

def count_window_start(slug, end_dt):
    """Counting window start = noon ET of the FIRST date in the slug. end_dt (the Gamma
    close, authoritative) supplies the year and handles Dec->Jan rollover."""
    toks = re.findall(r"(january|february|march|april|may|june|july|august|september|october|november|december)-(\d+)", slug.lower())
    if not toks:
        return None
    mon_name, day = toks[0]
    mon, day = MONTHS[mon_name], int(day)
    yr = end_dt.year - 1 if mon > end_dt.month else end_dt.year
    try:
        import zoneinfo
        return dt.datetime(yr, mon, day, 12, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")).astimezone(dt.timezone.utc)
    except Exception:
        return None

def x_window_count(window_start_dt, bearer, max_pages=6):
    """Return (count, last_counted_post_utc) for Elon's counted posts since window start."""
    headers = {"Authorization": f"Bearer {bearer}"}
    start_iso = window_start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"max_results": 100, "start_time": start_iso,
              "tweet.fields": "created_at,referenced_tweets,in_reply_to_user_id"}
    count, last_ts, token = 0, None, None
    with httpx.Client(timeout=25) as c:
        for _ in range(max_pages):
            if token:
                params["pagination_token"] = token
            r = c.get(f"{XAPI}/users/{ELON_ID}/tweets", params=params, headers=headers)
            if r.status_code != 200:
                raise RuntimeError(f"X API {r.status_code}: {r.text[:120]}")
            body = r.json()
            for tw in body.get("data", []):
                if counts_for_auction(tw):
                    count += 1
                    ts = tw.get("created_at")
                    if ts and (last_ts is None or ts > last_ts):
                        last_ts = ts
            token = body.get("meta", {}).get("next_token")
            if not token:
                break
    return count, last_ts

def discover():
    with httpx.Client(timeout=25) as c:
        seen = set()
        for off in range(0, 2500, 500):
            r = c.get(f"{GAMMA}/events", params={"active": "true", "closed": "false",
                      "limit": 500, "offset": off, "order": "volume24hr", "ascending": "false"})
            if r.status_code != 200:
                break
            ev = r.json()
            if not ev:
                break
            for e in ev:
                t = (e.get("title", "") + " " + e.get("slug", "")).lower()
                if "elon" in t and ("tweet" in t or "post" in t) and e.get("slug") not in seen:
                    seen.add(e.get("slug"))
                    print(f"{e.get('slug',''):50s} end={e.get('endDate','?')}  markets={len(e.get('markets',[]))}")
            if len(ev) < 500:
                break

def snapshot(slug):
    with httpx.Client(timeout=20) as c:
        r = c.get(f"{GAMMA}/events", params={"slug": slug})
        r.raise_for_status()
        ev = r.json()
    if not isinstance(ev, list) or not ev:
        return None, None, None
    end_date = ev[0].get("endDate")
    start_date = ev[0].get("startDate")
    rows = []
    for m in ev[0].get("markets", []):
        bracket = (m.get("groupItemTitle") or m.get("question") or "").strip()
        yb = float(m.get("bestBid") or 0)
        ya = float(m.get("bestAsk") or 1)
        no_bid = round(1 - ya, 4)
        no_ask = round(1 - yb, 4)
        op = m.get("outcomePrices", "[]")
        if isinstance(op, str):
            op = json.loads(op or "[]")
        yes_mid = float(op[0]) if op else round((yb + ya) / 2, 4)
        rows.append({"bracket": bracket, "yes_bid": yb, "yes_ask": ya, "no_bid": no_bid,
                     "no_ask": no_ask, "yes_mid": yes_mid, "spread": round(ya - yb, 4),
                     "take_both": round(ya + no_ask, 4), "make_both": round(yb + no_bid, 4),
                     "volume": float(m.get("volume", m.get("volumeNum", 0)) or 0)})
    return rows, start_date, end_date

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--secs", type=int, default=60)
    ap.add_argument("--count-secs", type=int, default=300)
    ap.add_argument("--minutes", type=int, default=0, help="0 = run until killed")
    ap.add_argument("--no-count", action="store_true")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--track", nargs="*", default=[],
                    help="positions you hold, e.g. --track 90-114:no@0.79 65-89:yes@0.66 . "
                         "Adds arb_ceiling + ARBABLE flag (you can complete the pair under $1 now).")
    a = ap.parse_args()
    if a.discover:
        discover(); return
    if not a.slug:
        print("need --slug (or --discover)"); sys.exit(1)

    bearer = None if a.no_count else load_bearer()
    if not a.no_count and not bearer:
        print("WARN: no X_BEARER_TOKEN found, logging book only (no count/p_done)")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"book_log_{a.slug}.csv"
    new = not out.exists()
    # parse tracked positions: {bracket: (side, cost)}
    tracked = {}
    for spec in a.track:
        m = re.match(r"(.+?):(yes|no)@([0-9.]+)", spec.strip(), re.I)
        if m:
            tracked[m.group(1).strip()] = (m.group(2).lower(), float(m.group(3)))
    if tracked:
        print("tracking:", {k: f"{v[0]}@{v[1]}" for k, v in tracked.items()})

    cols = ["ts_utc", "hours_to_close", "window_count", "silence_min", "p_done", "count_age_sec",
            "bracket", "position", "yes_bid", "yes_ask", "no_bid", "no_ask", "yes_mid", "spread",
            "take_both", "make_both", "dead_drift", "arb_ceiling", "arbable",
            "volume", "setsum_yes_ask", "setsum_yes_bid", "n_brackets"]
    deadline = time.time() + a.minutes * 60 if a.minutes else None
    cyc = 0
    win_count, last_post_ts, last_count_poll = None, None, 0.0
    mid_hist = defaultdict(lambda: deque(maxlen=20))   # bracket -> (epoch, yes_mid), ~20 min
    with open(out, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        while True:
            now = dt.datetime.now(dt.timezone.utc)
            try:
                rows, start_date, end_date = snapshot(a.slug)
            except Exception as e:
                print(f"{now:%H:%M:%S} book fetch error: {e}"); rows = None
            if rows:
                end_dt = None
                if end_date:
                    try:
                        end_dt = dt.datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                    except Exception:
                        pass
                # refresh X count on its own cadence (window start parsed from slug)
                if bearer and end_dt and (time.time() - last_count_poll) >= a.count_secs:
                    cstart = count_window_start(a.slug, end_dt)
                    if cstart:
                        try:
                            win_count, last_post_ts = x_window_count(cstart, bearer)
                            last_count_poll = time.time()
                        except Exception as e:
                            print(f"{now:%H:%M:%S} X count error: {e}")
                silence_min, pdone = "", ""
                if last_post_ts:
                    lp = dt.datetime.fromisoformat(last_post_ts.replace("Z", "+00:00"))
                    silence_min = round((now - lp).total_seconds() / 60, 1)
                    pdone = p_done(silence_min)
                count_age = round(time.time() - last_count_poll) if last_count_poll else ""
                htc = ""
                if end_date:
                    try:
                        ed = dt.datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        htc = round((ed - now).total_seconds() / 3600, 2)
                    except Exception:
                        pass
                ssa = round(sum(r["yes_ask"] for r in rows), 4)
                ssb = round(sum(r["yes_bid"] for r in rows), 4)
                ep = time.time()
                alerts = []
                for r in rows:
                    b = r["bracket"]
                    mid_hist[b].append((ep, r["yes_mid"]))
                    # position relative to running count
                    lh = bucket_lohi(b)
                    position = ""
                    if lh and win_count is not None:
                        lo, hi = lh
                        position = "future" if win_count < lo else ("current" if win_count <= hi else "past")
                    # decaying = yes_mid dropped over the trailing window
                    hist = mid_hist[b]
                    decaying = len(hist) >= 3 and (hist[0][1] - hist[-1][1]) >= DECAY_MIN
                    dead_drift = bool(position == "future" and pdone != "" and pdone >= DEAD_THRESH and decaying)
                    # arb ceiling for a tracked position: complete the pair under $1
                    arb_ceiling, arbable = "", ""
                    if b in tracked:
                        side, cost = tracked[b]
                        arb_ceiling = round(1 - cost, 4)
                        need_ask = r["no_ask"] if side == "yes" else r["yes_ask"]  # buy the OTHER side
                        arbable = bool(need_ask < arb_ceiling)
                    if dead_drift:
                        alerts.append(f"DEAD-DRIFT {b} yes_mid={r['yes_mid']}")
                    if arbable:
                        alerts.append(f"ARBABLE {b}: buy other side {need_ask} < ceiling {arb_ceiling}")
                    w.writerow({"ts_utc": now.isoformat(), "hours_to_close": htc,
                                "window_count": win_count if win_count is not None else "",
                                "silence_min": silence_min, "p_done": pdone, "count_age_sec": count_age,
                                "position": position, "dead_drift": dead_drift,
                                "arb_ceiling": arb_ceiling, "arbable": arbable,
                                "setsum_yes_ask": ssa, "setsum_yes_bid": ssb, "n_brackets": len(rows), **r})
                f.flush()
                best = min(rows, key=lambda r: r["make_both"])
                tag = ("  ** " + " | ".join(alerts)) if alerts else ""
                print(f"{now:%H:%M:%S} htc={htc} cnt={win_count} sil={silence_min}m pdone={pdone} | "
                      f"tightest make_both: {best['bracket']} {best['make_both']}{tag}")
            cyc += 1
            if deadline and time.time() >= deadline:
                break
            time.sleep(a.secs)
    print(f"done, {cyc} cycles -> {out}")

if __name__ == "__main__":
    main()
