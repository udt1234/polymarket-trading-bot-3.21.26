"""
SHADOW FORETEST harness — 2-day Elon, mid-auction, calibrated pace model.
NO capital, NO orders. Logs model-vs-market at the halfway mark, scores on resolution.

This is the forward (out-of-sample) test of the ONE edge that survived backtesting:
on 2-DAY Elon markets, at ~50% of the window, the calibrated pace model called the
winning bracket 77% vs the market's 55% (see noovd_backtest_findings memory).

Live data sources (both already exist in this repo):
  - tweet count : Twitter/X API, same locked rule as backfill_elon.py
                  (default reads the local X-API parquet; --pull does a small,
                  cost-guarded incremental fetch for the open window, ~$0.005/tweet)
  - bracket px  : the Railway tweet-recorder 'elon-tweets-48h' stream, pulled via
                  scripts/recorder/pull_and_merge.py into recordings_pulled/

Model artifact: the dispersion is LEARNED from realized 2-day projection errors
(historical auctions). winning_bucket is used ONLY to fit dispersion + to score.

Commands:
  python scripts/recorder/shadow_foretest.py --list          # recorded 2-day markets + window/elapsed
  python scripts/recorder/shadow_foretest.py --snapshot SLUG  # log one shadow snapshot (dry count)
  python scripts/recorder/shadow_foretest.py --snapshot SLUG --pull   # + live X-API count (~$1)
  python scripts/recorder/shadow_foretest.py --score          # running model-vs-market tally
"""
import sys, io, os, re, json, argparse, time, urllib.request, urllib.parse, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd, numpy as np
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT/"_DataMetricPulls/canonical"
XAPI = ROOT/"_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"
RECORDER = ROOT/"_DataMetricPulls/recordings_pulled/elon-tweets-48h.parquet"
FORE = ROOT/"_DataMetricPulls/foretest"; FORE.mkdir(exist_ok=True)
LOG = FORE/"shadow_log.parquet"
ET = ZoneInfo("America/New_York")
ELON_ID = "44196397"
ENTRY_FRAC = 0.50
# IFTTT-pushed live tweet sheet (validated 1.00 vs X-API on Jun13-20 overlap; ts are ET)
SHEET_ID = "185B2fntZVC1UUQtGvXdZ8OrbVQLs4pn6609GJKZ3aXc"
SA_KEY = os.path.expanduser("~/.claude/google-service-account.json")
MONTHS = {m: i for i, m in enumerate(
    ["january","february","march","april","may","june","july","august",
     "september","october","november","december"], 1)}


def pbk(b):
    b = str(b).strip()
    if b.startswith("<"): return (0, int(re.findall(r"\d+", b)[0]) - 1)
    if b.endswith("+"):   return (int(re.findall(r"\d+", b)[0]), 10**9)
    n = re.findall(r"\d+", b)
    return (int(n[0]), int(n[1])) if len(n) >= 2 else (None, None)


def pw(slug, ry):
    seq = []
    for t in slug.lower().split("-"):
        if t in MONTHS: seq.append(("m", MONTHS[t]))
        elif t.isdigit(): seq.append(("d", int(t)))
    md, cm = [], None
    for k, v in seq:
        if k == "m": cm = v
        elif cm and 1 <= v <= 31: md.append((cm, v))
    if len(md) < 2: return None
    (m1, d1), (m2, d2) = md[0], md[-1]; y2 = ry + 1 if m2 < m1 else ry
    try:
        s = datetime(ry, m1, d1, 12, tzinfo=ET); e = datetime(y2, m2, d2, 12, tzinfo=ET)
    except ValueError:
        return None
    return (pd.Timestamp(s).tz_convert("UTC"), pd.Timestamp(e).tz_convert("UTC")) if e > s else None


def xapi_counts():
    d = pd.read_parquet(XAPI)
    counted = d.type.isin(["original", "quote", "repost"]) | ((d.type == "reply") & (d.self_reply == True))
    return pd.to_datetime(d[counted].ts_utc, utc=True, format="ISO8601").sort_values().values


# ---------- model: learn 2-day dispersion from history ----------
def fit_ratios(frac=ENTRY_FRAC):
    cts = xapi_counts(); lo, hi = cts.min(), cts.max()
    a = pd.concat([pd.read_parquet(x) for x in (CANON/"auctions/elonmusk").glob("*.parquet")]).drop_duplicates("auction_slug")
    a = a[(a.confidence == "high") & (a.resolution_status == "resolved_yes") & (a.duration_type == "2-day")]
    ratios = []
    for _, r in a.iterrows():
        if str(r.auction_slug).startswith("arch-"): continue
        w = pw(r.auction_slug, pd.to_datetime(r.start_et).year)
        if not w: continue
        ws, we = w
        if np.datetime64(ws) < lo or np.datetime64(we) > hi: continue
        t = ws + (we - ws) * frac
        c = int(((cts >= np.datetime64(ws)) & (cts < np.datetime64(t))).sum())
        act = int(((cts >= np.datetime64(ws)) & (cts < np.datetime64(we))).sum())
        if c > 0: ratios.append(act / (c / frac))
    return np.array(ratios)


def model_probs(proj, brackets, ratios):
    samples = proj * ratios
    out = {}
    for b in brackets:
        lo, hi = pbk(b)
        out[b] = float(((samples >= lo) & (samples <= hi)).mean()) if lo is not None else np.nan
    return out


# ---------- live-ish data getters ----------
def recorder_prices(slug, at_time):
    """Per-bracket YES mid from recorder BUY-side rows as-of at_time (else latest)."""
    if not RECORDER.exists(): return {}, None
    d = pd.read_parquet(RECORDER)
    # YES book only (each bucket has YES+NO outcomes; we price the YES share)
    d = d[(d.slug == slug) & (d.event_type == "price_change")
          & (d.outcome == "YES") & (d.side == "BUY")].copy()
    if not len(d): return {}, None
    d["t"] = pd.to_datetime(d.ts, unit="ms", utc=True)
    asof = pd.Timestamp(at_time)
    le = d[d.t <= asof]
    use = le if len(le) else d
    snap_t = use.t.max()
    out = {}
    for b, g in use.groupby("bucket"):
        row = g.sort_values("t").iloc[-1]
        bid, ask = row.best_bid, row.best_ask
        out[b] = float((bid + ask) / 2) if pd.notna(bid) and pd.notna(ask) else float(row.price)
    return out, snap_t


def refresh_recorder():
    """Best-effort: pull the latest recorder chunks before snapshotting, so prices/token
    maps are current. Token from ~/.credentials/shared.env. Silent no-op on any failure."""
    import subprocess
    try:
        cred = os.path.expanduser("~/.credentials/shared.env")
        tok = next((l.split("=", 1)[1].strip().strip('"') for l in open(cred, encoding="utf-8")
                    if l.startswith("RECORDER_TOKEN=")), "")
        if not tok:
            return
        subprocess.run([sys.executable, "-W", "ignore",
                        str(ROOT/"scripts/recorder/pull_and_merge.py"),
                        "--url", "https://tweet-recorder-production.up.railway.app",
                        "--token", tok], timeout=120, capture_output=True)
        print("  recorder refreshed")
    except Exception as e:
        print(f"  recorder refresh skipped: {e}")


def yes_token_map(slug):
    """bucket -> YES token_id, discovered from the recorder parquet (tokens are stable)."""
    if not RECORDER.exists(): return {}
    d = pd.read_parquet(RECORDER)
    d = d[(d.slug == slug) & (d.outcome == "YES")]
    return {b: str(g.asset_id.iloc[0]) for b, g in d.groupby("bucket") if g.asset_id.notna().any()}


def clob_mid(token_id):
    try:
        req = urllib.request.Request(f"https://clob.polymarket.com/book?token_id={token_id}",
                                     headers={"User-Agent": "curl/8"})
        b = json.loads(urllib.request.urlopen(req, timeout=20).read())
        bids, asks = b.get("bids", []), b.get("asks", [])
        bid = float(bids[-1]["price"]) if bids else None
        ask = float(asks[-1]["price"]) if asks else None
        if bid is not None and ask is not None: return (bid + ask) / 2
        return float(b.get("last_trade_price")) if b.get("last_trade_price") else None
    except Exception:
        return None


def live_book_prices(slug):
    """Per-bracket YES mid from the LIVE Polymarket CLOB order book (real-time, free)."""
    toks = yes_token_map(slug)
    out = {}
    for b, tid in toks.items():
        m = clob_mid(tid)
        if m is not None: out[b] = m
    return out, pd.Timestamp.now(tz="UTC")


def pull_live_count(ws, end):
    """Small cost-guarded X-API fetch of Elon tweets in [ws, end]; returns counted total."""
    bearer = next(l.split("=", 1)[1].strip() for l in open(ROOT/".env", encoding="utf-8")
                  if l.startswith("X_BEARER_TOKEN="))
    start_s = pd.Timestamp(ws).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_s = pd.Timestamp(end).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, token, pages = [], None, 0
    while True:
        p = {"query": f"from:{ELON_ID}", "start_time": start_s, "end_time": end_s, "max_results": "500",
             "tweet.fields": "created_at,referenced_tweets,in_reply_to_user_id"}
        if token: p["next_token"] = token
        req = urllib.request.Request("https://api.x.com/2/tweets/search/all?" + urllib.parse.urlencode(p),
                                     headers={"Authorization": f"Bearer {bearer}"})
        try:
            with urllib.request.urlopen(req) as r: body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(8); continue
            print("  X-API error", e.code, e.read().decode()[:200]); break
        rows += body.get("data", []); pages += 1
        token = body.get("meta", {}).get("next_token")
        if not token or pages > 12: break
        time.sleep(1.1)
    cnt = 0
    for t in rows:
        refs = [r["type"] for r in t.get("referenced_tweets", [])]
        ty = "repost" if "retweeted" in refs else "quote" if "quoted" in refs else "reply" if "replied_to" in refs else "original"
        self_reply = (ty == "reply" and str(t.get("in_reply_to_user_id")) == ELON_ID)
        if ty in ("original", "quote", "repost") or self_reply: cnt += 1
    print(f"  X-API pulled {len(rows)} tweets (~${len(rows)*0.005:.2f}) -> {cnt} counted in window")
    return cnt


def local_count(ws, t):
    cts = xapi_counts()
    return int(((cts >= np.datetime64(pd.Timestamp(ws))) & (cts < np.datetime64(pd.Timestamp(t)))).sum())


def sheet_count(ws, t):
    """Live Elon count from the IFTTT sheet (free). Count rule: keep original/quote/
    repost/self-reply, drop pure replies to others. Timestamps are ET. -> count in [ws,t)."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        SA_KEY, scopes=["https://www.googleapis.com/auth/spreadsheets"], subject="darwin@xagency.com")
    sh = build("sheets", "v4", credentials=creds)
    v = sh.spreadsheets().values().get(spreadsheetId=SHEET_ID, range="Sheet1!A1:D5000").execute().get("values", [])
    rows = [r + [""]*(4-len(r)) for r in v]
    df = pd.DataFrame(rows, columns=["handle", "ts", "text", "url"])
    e = df[df.handle.str.strip().str.lower() == "@elonmusk"].copy()

    def counts(tx):
        tx = tx.strip()
        if tx.startswith("RT @"): return True                       # repost
        m = re.match(r"^@(\w+)", tx)
        if m: return m.group(1).lower() == "elonmusk"               # self-reply yes, reply-to-others no
        return True                                                 # original / quote

    def to_utc(s):
        try:
            return pd.Timestamp(datetime.strptime(s.strip(), "%B %d, %Y at %I:%M%p"), tz=ET).tz_convert("UTC")
        except Exception:
            return pd.NaT
    e["utc"] = e.ts.apply(to_utc); e["ok"] = e.text.apply(counts)
    m = e[e.ok & (e.utc >= pd.Timestamp(ws)) & (e.utc < pd.Timestamp(t))]
    return int(len(m)), str(e.utc.max())


# ---------- commands ----------
def list_markets():
    if not RECORDER.exists(): print("no recorder data yet."); return
    d = pd.read_parquet(RECORDER)
    now = pd.Timestamp.now(tz="UTC")
    print(f"now = {now}   (entry target = 50% of window)")
    for slug in sorted(d.slug.unique()):
        w = pw(slug, 2026)
        if not w: print(f"  {slug}: window unparseable"); continue
        ws, we = w
        elapsed = (now - ws) / (we - ws)
        state = "PRE" if now < ws else ("LIVE" if now < we else "DONE")
        nb = d[d.slug == slug].bucket.nunique()
        print(f"  {slug:42s} {state:4s} | {ws.date()}->{we.date()} | elapsed {elapsed:5.0%} | {nb} brackets")


def snapshot(slug, do_pull):
    w = pw(slug, pd.Timestamp.now().year)
    if not w: print("window unparseable"); return
    refresh_recorder()                       # freshen token map + recorder book first
    ws, we = w
    now = pd.Timestamp.now(tz="UTC")
    t = ws + (we - ws) * ENTRY_FRAC
    asof = min(now, t) if now >= ws else t           # snapshot at halfway (or now if past it)
    prices, snap_t = live_book_prices(slug); price_src = "clob-live"   # real-time order book
    if not prices:
        prices, snap_t = recorder_prices(slug, asof if now >= t else now); price_src = "recorder-stale"
    if not prices: print(f"no prices for {slug}"); return
    brackets = list(prices.keys())
    end = min(now, t)
    sheet_latest = None
    if do_pull:
        cnt = pull_live_count(ws, end); count_src = "xapi-live"
    else:
        try:
            cnt, sheet_latest = sheet_count(ws, end); count_src = "ifttt-sheet"
        except Exception as ex:
            cnt = local_count(ws, end); count_src = f"xapi-parquet(sheet failed: {ex})"
    proj = cnt / ENTRY_FRAC if cnt > 0 else 0.0
    ratios = fit_ratios()
    probs = model_probs(proj, brackets, ratios) if cnt > 0 else {b: np.nan for b in brackets}
    tot = sum(prices.values())
    rowlist = []
    for b in brackets:
        rowlist.append(dict(logged_utc=now.isoformat(), slug=slug, window_start=ws.isoformat(),
                            window_end=we.isoformat(), entry_frac=ENTRY_FRAC, count_so_far=cnt,
                            proj=round(proj, 1), count_src=count_src, bucket=b,
                            price=round(prices[b], 4), mkt_impl=round(prices[b]/tot, 4) if tot else np.nan,
                            model=round(probs[b], 4) if probs[b] == probs[b] else np.nan,
                            n_ratios=len(ratios), price_src=price_src, snap_px_utc=str(snap_t)))
    df = pd.DataFrame(rowlist)
    if LOG.exists():
        df = pd.concat([pd.read_parquet(LOG)[lambda x: ~((x.slug == slug) & (x.logged_utc == now.isoformat()))], df], ignore_index=True)
    df.to_parquet(LOG, index=False)
    # report
    cur = df[(df.slug == slug) & (df.logged_utc == now.isoformat())].copy()
    print(f"\n{slug} | count={cnt} ({count_src}) proj={proj:.0f} | {len(ratios)} ratios | prices {price_src} @ {snap_t}")
    if cnt > 0:
        cur["edge"] = cur.model / cur.price
        m_arg = cur.loc[cur.model.idxmax(), "bucket"]; k_arg = cur.loc[cur.mkt_impl.idxmax(), "bucket"]
        print(f"  MODEL argmax: {m_arg}   |   MARKET argmax: {k_arg}   |   {'AGREE' if m_arg==k_arg else 'DISAGREE'}")
        print(cur[["bucket", "price", "mkt_impl", "model", "edge"]].sort_values("model", ascending=False).head(6).to_string(index=False))
        bets = cur[(cur.model >= cur.price * 2.0)]
        print(f"  disagreement bets (model>=2x price): {list(bets.bucket)}")
    print(f"  logged -> {LOG}")


def auto(lo=0.40, hi=0.70):
    """Hands-free: snapshot every LIVE 2-day market currently near its halfway mark
    that we haven't already logged in the last 18h. (Recorder file = 48h markets only.)"""
    if not RECORDER.exists(): print("no recorder data yet."); return
    slugs = sorted(pd.read_parquet(RECORDER).slug.unique())
    now = pd.Timestamp.now(tz="UTC")
    logged = pd.read_parquet(LOG) if LOG.exists() else pd.DataFrame(columns=["slug", "logged_utc"])
    recent = set()
    if len(logged):
        lg = logged.copy(); lg["lts"] = pd.to_datetime(lg.logged_utc, utc=True)
        recent = set(lg[lg["lts"] > now - pd.Timedelta(hours=18)].slug)
    did = 0
    for slug in slugs:
        w = pw(slug, now.year)
        if not w: continue
        ws, we = w
        if not (ws <= now < we): continue
        el = (now - ws) / (we - ws)
        if not (lo <= el <= hi): continue
        if slug in recent:
            print(f"  skip {slug} (already logged <18h ago)"); continue
        print(f"  snapshotting {slug} (elapsed {el:.0%})")
        snapshot(slug, do_pull=False); did += 1
    print(f"\nauto done: {did} market(s) snapshotted.")


def score():
    if not LOG.exists(): print("no shadow log yet."); return
    log = pd.read_parquet(LOG)
    a = pd.concat([pd.read_parquet(x) for x in (CANON/"auctions/elonmusk").glob("*.parquet")]).drop_duplicates("auction_slug")
    win = dict(zip(a.auction_slug, a.winning_bucket))
    res = []
    for (slug, lg), g in log.groupby(["slug", "logged_utc"]):
        wb = win.get(slug)
        if not wb or g.model.isna().all(): continue
        m_arg = g.loc[g.model.idxmax(), "bucket"]; k_arg = g.loc[g.mkt_impl.idxmax(), "bucket"]
        res.append(dict(slug=slug, logged=lg[:16], winner=wb,
                        model_pick=m_arg, market_pick=k_arg,
                        model_hit=int(m_arg == wb), market_hit=int(k_arg == wb)))
    if not res:
        print("snapshots logged but none resolved yet — re-run --score after the markets settle.")
        print(f"  pending: {log.slug.nunique()} market(s) logged.")
        return
    r = pd.DataFrame(res)
    print(r.to_string(index=False))
    print(f"\nResolved snapshots: {len(r)}")
    print(f"  MODEL  argmax-picks-winner: {r.model_hit.mean():.0%}")
    print(f"  MARKET argmax-picks-winner: {r.market_hit.mean():.0%}")
    print(f"  (target: model holds its 77% vs market 55% backtest edge over ~15-20 markets)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--snapshot", metavar="SLUG")
    ap.add_argument("--pull", action="store_true", help="live X-API count (small paid fetch)")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--auto", action="store_true", help="snapshot all live 2-day markets near halfway")
    a = ap.parse_args()
    if a.list: list_markets()
    elif a.snapshot: snapshot(a.snapshot, a.pull)
    elif a.score: score()
    elif a.auto: auto()
    else: ap.print_help()
