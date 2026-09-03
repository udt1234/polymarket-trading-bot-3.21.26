# -*- coding: utf-8 -*-
"""phase_wh_maker.py — Does the LOCKED pace engine, run as a RESTING POST-ONLY MAKER on the thin
White House #-tweets weekly markets, net POSITIVE maker P&L where the IDENTICAL sim on the
(documented-efficient) Elon #-tweets markets nets ~ZERO?

Obeys BACKTEST_RULES.md:
  * EVENT-DRIVEN ONLY  — the fill engine processes every recorded trade print (last_trade_price)
    and reconstructs top-of-book from every distinct price_change state. NO time bars. (Consecutive
    IDENTICAL top-of-book states are collapsed in SQL — a no-op dedupe, every distinct state kept.)
  * THE WALL           — at each decision T the pace fair value uses ONLY tweets with ts<=T
    (obs(s,T)) and walk-forward priors (windows that ENDED before this auction started). The winning
    bucket is used for SCORING ONLY, never as an input or a filter.
  * MAKER-ONLY         — we REST a post-only bid at best_bid+tick (inside the spread, never crossing).
    A quote fills ONLY when a real trade prints THROUGH our level (a normalized SELL at p<b, STRICT).
    Maker rebate is a parameter (default 0). Taker fee = 0 (we never take).
  * REAL RESOLUTION    — payout scored vs the actual winning bucket (self-count in the noon-ET window;
    for WH this is cross-checked to equal the Gamma-resolved winner).
  * WINDOWS            — ET noon-to-noon parsed from the market slug (not trade-derived).

Data (LOCAL): recorder tick L2 at _DataMetricPulls/recordings_pulled/{whitehouse-daily-tweets,
elon-tweets}.parquet (read via the same globbing api.modules.shared.l2_history uses). WH tweet counts
from wh_backfill_2026-06_to_07.parquet (X-API full-archive pull, locked WH counting rule); Elon from
elon_backfill_ext_to_2026-07-10.parquet (existing Sept-2025 backfill extended through Jul 10).
"""
import glob, os, json, math, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
sys.stdout.reconfigure(encoding='utf-8')
con = duckdb.connect()
ROOT = "C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
PB = ROOT + "/_DataMetricPulls/pacing_backtest"
REC = ROOT + "/_DataMetricPulls/recordings_pulled"
ET = ZoneInfo('America/New_York')
MON = {m.lower(): i for i, m in enumerate(['', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'])}

# ---------- LOCKED pace engine (Ensemble+CAP1.5) + calibrated per-bracket fair value ----------
SQRT2 = math.sqrt(2)
_SIG_RH = [1, 4, 8, 12, 18, 24, 32, 40, 48]; _SIG_SD = [5.0, 7.8, 10.8, 15.5, 16.8, 18.9, 31.4, 38.2, 42.0]
def calib_sigma(rh): return max(float(np.interp(rh, _SIG_RH, _SIG_SD)), 1.0)
def _Phi(x, mu, sd): return 0.5 * (1 + math.erf((x - mu) / (sd * SQRT2)))
def _fair(lo, hi, c, sd):
    return max(1e-6, min(1 - 1e-6, ((_Phi(hi + 0.5, c, sd) if hi < 1e8 else 1.0) - _Phi(lo - 0.5, c, sd))))
def cap15(o, eh, rh, rmean, Kk, share, cp):
    kal = o + (rmean + Kk * (o / eh - rmean)) * rh
    acc = o / share[min(len(share) - 1, max(0, int(eh) - 1))]
    ens = (1 - cp) * kal + cp * acc
    return o + min((ens - o) / max(rh, .1), 1.5 * rmean) * rh   # LOCKED Ensemble+CAP1.5

def pbk(l):
    l = str(l).strip()
    if l.startswith('<'): return (0, int(l[1:]) - 1)
    if l.endswith('+'): return (int(l[:-1]), 10 ** 9)
    if '-' in l:
        a, b = l.split('-'); return (int(a), int(b))
    return (int(l), int(l))

def noon(slug, prefix):
    """ET noon-to-noon from the slug. Handles WH (trailing -2026) and Elon (no year)."""
    tk = slug.replace(prefix, '').split('-')
    mo1 = MON[tk[0].lower()]; d1 = int(tk[1])
    if len(tk) >= 4 and tk[2].lower() in MON:
        mo2 = MON[tk[2].lower()]; d2 = int(tk[3])
    else:
        mo2 = mo1; d2 = int(tk[2])
    yr = 2026
    for t in tk:
        if t.isdigit() and len(t) == 4: yr = int(t)
    y2 = yr + (1 if mo2 < mo1 else 0)
    return (int(pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET)).timestamp()),
            int(pd.Timestamp(datetime(y2, mo2, d2, 12, tzinfo=ET)).timestamp()))

# ---------- family configs ----------
FAM = {
 'WH': dict(prefix='white-house-of-tweets-',
    rec=REC + '/whitehouse-daily-tweets.parquet',
    bf=PB + '/wh_backfill_2026-06_to_07.parquet',
    slugs=['white-house-of-tweets-june-19-june-26-2026', 'white-house-of-tweets-june-23-june-30-2026',
           'white-house-of-tweets-june-26-july-3-2026', 'white-house-of-tweets-june-30-july-7-2026',
           'white-house-of-tweets-july-3-july-10-2026'],
    gamma_win={'white-house-of-tweets-june-19-june-26-2026': '180-199',
               'white-house-of-tweets-june-23-june-30-2026': '180-199',
               'white-house-of-tweets-june-26-july-3-2026': '200+',
               'white-house-of-tweets-june-30-july-7-2026': '200+',
               'white-house-of-tweets-july-3-july-10-2026': '200+'}),
 'ELON': dict(prefix='elon-musk-of-tweets-',
    rec=REC + '/elon-tweets.parquet',
    bf=PB + '/elon_backfill_ext_to_2026-07-10.parquet',
    slugs=['elon-musk-of-tweets-june-19-june-26', 'elon-musk-of-tweets-june-23-june-30',
           'elon-musk-of-tweets-june-26-july-3', 'elon-musk-of-tweets-june-30-july-7',
           'elon-musk-of-tweets-july-3-july-10'],
    gamma_win={}),
}

def rec_files(d):
    fs = glob.glob(d + '/*.parquet') + ([d] if os.path.isfile(d) else [])
    return [f for f in fs if os.path.isfile(f)]
def arr(fs): return '[' + ','.join("'" + f.replace(os.sep, '/') + "'" for f in fs) + ']'

TICK = 0.001
GATE_S = 48 * 3600           # 7-day markets: only quote inside the final 48h (Sir's locked gate)
BANK = 5000.0; KMULT = 0.25; MAXBET = 0.10

def build_priors(pts, before, dur_h):
    """Walk-forward priors from daily-anchored (noon ET) windows of length dur_h that END <= before.
    Returns rmean (tweets/hr), Kk (Kalman gain), share (median cumulative-accrual curve len=int(dur_h))."""
    if len(pts) == 0: return None
    def obs(a, b): return int(np.searchsorted(pts, b) - np.searchsorted(pts, a))
    Dh = int(round(dur_h)); dur_s = Dh * 3600
    d0 = pd.Timestamp(datetime.fromtimestamp(int(pts[0]), ET).date(), tz=ET) + pd.Timedelta(hours=12)
    rates = []; curves = []; d = d0
    while d.timestamp() + dur_s <= before:
        ss = int(d.timestamp()); f = obs(ss, ss + dur_s)
        if f >= 5:
            rates.append(f / dur_h)
            curves.append(np.array([obs(ss, ss + h * 3600) for h in range(1, Dh + 1)], float) / f)
        d = d + pd.Timedelta(days=1)
    if len(rates) < 4: return None
    rmean = float(np.mean(rates)); Pk = float(np.var(rates)) + .01
    Kk = (Pk + .01) / (Pk + .01 + max(.1, Pk * .5))
    share = np.clip(np.median(np.vstack(curves), axis=0), 1e-3, 1.0)
    return rmean, Kk, share

def precompute_slug(fam, slug):
    """Return (meta, events) where events is a time-sorted list of normalized YES-space SELL prints,
    each pre-tagged with the causal top-of-book and the LOCKED per-bracket fair value at that instant.
    events: (t_sec, bucket, p_norm, size, bid, ask, fair_bucket).  meta has s,e,winner,priors,ranges."""
    cfg = FAM[fam]; fs = rec_files(cfg['rec']); a = arr(fs)
    s, e = noon(slug, cfg['prefix']); total = (e - s) / 3600
    # tokens per bucket
    tk = con.execute(f"SELECT DISTINCT bucket,outcome,CAST(asset_id AS VARCHAR) aid FROM read_parquet({a},union_by_name=true) WHERE slug='{slug}'").df()
    tok = {}
    for _, x in tk.iterrows(): tok.setdefault(x['bucket'], {})[x['outcome']] = x['aid']
    ranges = {b: pbk(b) for b in tok}
    yes_ids = [v['YES'] for v in tok.values() if 'YES' in v]
    all_ids = [i for v in tok.values() for i in v.values()]
    yid2b = {v['YES']: b for b, v in tok.items() if 'YES' in v}
    nid2b = {v['NO']: b for b, v in tok.items() if 'NO' in v}
    # observed count engine (WALL) + winner (SCORING ONLY)
    bf = pd.read_parquet(cfg['bf']); bf = bf[bf.counts_main_feed]; pts = np.sort((bf.ms.to_numpy() // 1000).astype('int64'))
    def obs(a_, b_): return int(np.searchsorted(pts, b_) - np.searchsorted(pts, a_))
    actual = obs(s, e); winner = next((b for b, (lo, hi) in ranges.items() if lo <= actual <= hi), None)
    pri = build_priors(pts, s, total)
    if pri is None or winner is None: return dict(s=s, e=e, skip=True, reason='no_priors_or_winner'), []
    rmean, Kk, share = pri
    # top-of-book: collapse consecutive identical (best_bid,best_ask) per YES token in SQL (no-op dedupe)
    ytl = '(' + ','.join("'" + t + "'" for t in yes_ids) + ')'
    bqk = con.execute(f"""
      WITH t AS (SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid bb, best_ask ba,
          LAG(best_bid) OVER (PARTITION BY asset_id ORDER BY ts) pb,
          LAG(best_ask) OVER (PARTITION BY asset_id ORDER BY ts) pa
        FROM read_parquet({a},union_by_name=true)
        WHERE slug='{slug}' AND event_type='price_change' AND best_ask>0 AND ts>={s*1000} AND ts<{e*1000})
      SELECT ts, aid, bb, ba FROM t WHERE pb IS NULL OR bb<>pb OR ba<>pa ORDER BY ts""").df()
    book = {}
    for b in tok:
        yid = tok[b].get('YES')
        g = bqk[bqk.aid == yid]
        if len(g): book[b] = (g.ts.to_numpy().astype('int64'), g.bb.to_numpy(float), g.ba.to_numpy(float))
    # trade prints -> normalized YES-space SELL prints
    atl = '(' + ','.join("'" + t + "'" for t in all_ids) + ')'
    tr = con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, price, size, side FROM read_parquet({a},union_by_name=true)
        WHERE slug='{slug}' AND event_type='last_trade_price' AND ts>={s*1000} AND ts<{e*1000} AND size>0 ORDER BY ts""").df()
    sells = []   # (t_sec, bucket, p_norm, size)
    for _, x in tr.iterrows():
        aid = x['aid']; ms = int(x['ts']); tsec = ms / 1000.0; side = x['side']; p = float(x['price']); sz = float(x['size'])
        if aid in yid2b and side == 'SELL':                 # seller crossed DOWN into YES bid
            sells.append((tsec, yid2b[aid], p, sz))
        elif aid in nid2b and side == 'BUY':                # BUY NO@q == SELL YES@(1-q)
            sells.append((tsec, nid2b[aid], 1.0 - p, sz))
    sells.sort(key=lambda r: r[0])
    # pre-tag each SELL print with causal book + LOCKED fair value at t
    events = []
    for (tsec, b, pn, sz) in sells:
        if b not in book: continue
        t = int(tsec)
        if t < s + 3600 or t >= e: continue
        eh = (t - s) / 3600.0; rh = (e - t) / 3600.0
        if eh < 1 or rh < 0.5: continue
        bts, bb, ba = book[b]
        i = np.searchsorted(bts, int(tsec * 1000), 'right') - 1
        if i < 0: continue
        bid = bb[i]; ask = ba[i]
        if not (0 < bid < ask < 1): continue
        o = obs(s, t); cp = eh / total
        c = cap15(o, eh, rh, rmean, Kk, share, cp); sd = calib_sigma(rh)
        raw = {l: _fair(lo, hi, c, sd) for l, (lo, hi) in ranges.items()}
        tot = sum(raw.values()) or 1.0
        fair = raw[b] / tot
        events.append((tsec, b, pn, sz, bid, ask, fair))
    meta = dict(s=s, e=e, total=total, winner=winner, actual=actual, ranges=ranges,
                n_buckets=len(tok), n_trades=len(tr), n_sell=len(sells), skip=False,
                gamma_win=cfg['gamma_win'].get(slug))
    return meta, events

def run_config(events, meta, strict, margin, clip, gate):
    """Realistic resting post-only maker. One live bid per bucket. A quote must be RESTING (armed at a
    STRICTLY EARLIER event than the fill — no seeing-the-seller-then-repricing). STRICT fill requires a
    trade to print BELOW the pre-existing best_bid (the level beneath our improve is swept -> FIFO fills
    us), so we do NOT queue-jump the touch. We fill at our resting price and HOLD to resolution.
    Returns (net, deployed, nfills, per_bucket_shares)."""
    s, e, winner = meta['s'], meta['e'], meta['winner']
    live = {}                # bucket -> {'b':price,'sh':shares_left,'idx':place_event_index}
    shares_on = {}; cost = 0.0; nf = 0; dep_b = {}   # dep_b = filled notional per bucket (budget cap)
    for i, (tsec, b, pn, sz, bid, ask, fair) in enumerate(events):
        t = tsec
        if gate and (e - t) > GATE_S: continue
        if dep_b.get(b, 0.0) >= clip: continue        # per-bracket budget exhausted: a real maker with a
                                                       # $clip budget per bracket cannot accumulate forever
        # (1) FILL first, against a quote armed at an EARLIER event
        cur = live.get(b)
        if cur and cur['idx'] < i and cur['sh'] > 0:
            hit = (pn < bid) if strict else (pn <= bid)   # trade swept BELOW the pre-existing top-of-book
            if hit:
                room = max(0.0, clip - dep_b.get(b, 0.0))
                fsh = min(cur['sh'], sz, room / cur['b'] if cur['b'] > 0 else 0.0)
                if fsh > 0:
                    cost += fsh * cur['b']; shares_on[b] = shares_on.get(b, 0.0) + fsh; nf += 1
                    dep_b[b] = dep_b.get(b, 0.0) + fsh * cur['b']
                    cur['sh'] -= fsh
                    if cur['sh'] <= 1e-9: live[b] = None; cur = None
        # (2) (re)arm the quote for FUTURE events
        qb = round(bid + TICK, 4)
        want = (qb < ask) and (0.05 < fair < 0.95) and (fair > ask + margin)
        if want:
            c2 = live.get(b)
            if c2 is None or abs(c2['b'] - qb) > 1e-9:
                f = (fair - qb) / (1 - qb)
                stake = min(clip, min(max(f, 0.0) * KMULT, MAXBET) * BANK)
                live[b] = {'b': qb, 'sh': (stake / qb) if qb > 0 else 0.0, 'idx': i}
        else:
            live[b] = None
    payout = sum(sh * (1.0 if b == winner else 0.0) for b, sh in shares_on.items())
    net = payout - cost
    return net, cost, nf, shares_on

def main():
    REBATE_BPS = 0.0    # Polymarket maker rebate ~0 today; edge must survive at 0
    MARGINS = [0.02, 0.03, 0.04]; CLIPS = [100, 250, 500]
    print("=" * 96)
    print("phase_wh_maker — resting post-only MAKER on White House #-tweets markets, Elon = control")
    print("LOCKED pace engine (Ens+CAP1.5) + calibrated sigma | event-driven | WALL | maker-only | real resolution")
    print("=" * 96)
    slug_cache = {}; per_slug = {}
    for fam in ['WH', 'ELON']:
        print(f"\n########## {fam} ##########")
        for slug in FAM[fam]['slugs']:
            meta, events = precompute_slug(fam, slug)
            slug_cache[(fam, slug)] = (meta, events); per_slug[(fam, slug)] = meta
            if meta.get('skip'):
                print(f"  {slug:<46} SKIP ({meta.get('reason')})"); continue
            xw = f"gamma={meta['gamma_win']}" if meta['gamma_win'] else ''
            flag = 'OK' if (not meta['gamma_win'] or meta['gamma_win'] == meta['winner']) else 'MISMATCH!'
            print(f"  {slug:<46} count={meta['actual']:>4} winner={meta['winner']:<8} {xw:<14} {flag}  "
                  f"buckets={meta['n_buckets']} trades={meta['n_trades']} sellprints={meta['n_sell']} events={len(events)}")

    # headline config used for the structured summary
    HL = dict(strict=True, margin=0.03, clip=250, gate=True)
    results = {}
    for gate in [True, False]:
        for strict in [True, False]:
            for margin in MARGINS:
                for clip in CLIPS:
                    for fam in ['WH', 'ELON']:
                        tot_net = tot_dep = tot_nf = 0.0; per_au = []; nev = 0
                        for slug in FAM[fam]['slugs']:
                            meta, events = slug_cache[(fam, slug)]
                            if meta.get('skip') or not events: continue
                            net, dep, nf, _ = run_config(events, meta, strict, margin, clip, gate)
                            reb = REBATE_BPS / 10000.0 * dep
                            net += reb
                            tot_net += net; tot_dep += dep; tot_nf += nf; per_au.append(net); nev += 1
                        roi = 100 * tot_net / tot_dep if tot_dep > 0 else 0.0
                        results[(gate, strict, margin, clip, fam)] = dict(net=tot_net, dep=tot_dep, nf=int(tot_nf), roi=roi, per_au=per_au, nev=nev)

    def show(gate, strict):
        tag = f"gate={'ON(final48h)' if gate else 'OFF'} | fill={'STRICT(p<b)' if strict else 'OPTIMISTIC(p<=b)'}"
        print(f"\n----- {tag} | rebate={REBATE_BPS}bps -----")
        print(f"{'margin':>6} {'clip':>5} | {'WH net':>9} {'WH ROI':>8} {'WH nf':>6} | {'ELON net':>9} {'ELON ROI':>8} {'ELON nf':>7} | {'WH-ELON ROI':>11}")
        for margin in MARGINS:
            for clip in CLIPS:
                w = results[(gate, strict, margin, clip, 'WH')]; el = results[(gate, strict, margin, clip, 'ELON')]
                gap = w['roi'] - el['roi']
                print(f"{margin:>6.2f} {clip:>5} | {w['net']:>9.1f} {w['roi']:>7.1f}% {w['nf']:>6} | {el['net']:>9.1f} {el['roi']:>7.1f}% {el['nf']:>7} | {gap:>+10.1f}%")

    for gate in [True, False]:
        for strict in [True, False]:
            show(gate, strict)

    # headline
    w = results[(HL['gate'], HL['strict'], HL['margin'], HL['clip'], 'WH')]
    el = results[(HL['gate'], HL['strict'], HL['margin'], HL['clip'], 'ELON')]
    def boot(per_au, n=5000):
        if not per_au: return (0.0, 0.0)
        a = np.array(per_au); idx = np.random.RandomState(0).randint(0, len(a), (n, len(a)))
        tot = a[idx].sum(1)
        return float(np.percentile(tot, 2.5)), float(np.percentile(tot, 97.5))
    wlo, whi = boot(w['per_au']); ello, elhi = boot(el['per_au'])
    print("\n" + "=" * 96)
    print(f"HEADLINE  strict fill, final-48h gate, margin=0.03, clip=$250, rebate=0")
    print(f"  WH  : events={w['nev']}  net=${w['net']:+.1f}  deployed=${w['dep']:.0f}  ROI={w['roi']:+.1f}%  fills={w['nf']}  per-auction={[round(x,1) for x in w['per_au']]}")
    print(f"        95% per-auction bootstrap total-net CI = [{wlo:+.1f}, {whi:+.1f}]")
    print(f"  ELON: events={el['nev']}  net=${el['net']:+.1f}  deployed=${el['dep']:.0f}  ROI={el['roi']:+.1f}%  fills={el['nf']}  per-auction={[round(x,1) for x in el['per_au']]}")
    print(f"        95% per-auction bootstrap total-net CI = [{ello:+.1f}, {elhi:+.1f}]")
    print(f"  WH-minus-ELON ROI gap = {w['roi']-el['roi']:+.1f}%")
    beats = (w['net'] > 0 and wlo > 0 and (w['roi'] - el['roi']) >= 5.0 and abs(el['roi']) <= 2.0)
    print(f"  wh_beats_control (net>0 & bootstrap-LB>0 & gap>=5% & |elon ROI|<=2%) = {beats}")
    print("=" * 96)

    # emit machine-readable line for the harness
    print("\nRESULT_JSON=" + json.dumps(dict(
        wh_events=w['nev'], wh_maker_pnl=round(w['net'], 2), wh_roi_pct=round(w['roi'], 2), wh_fills=w['nf'],
        elon_events=el['nev'], elon_maker_pnl=round(el['net'], 2), elon_roi_pct=round(el['roi'], 2), elon_fills=el['nf'],
        wh_beats_control=bool(beats), wh_boot_ci=[round(wlo, 1), round(whi, 1)], elon_boot_ci=[round(ello, 1), round(elhi, 1)])))

if __name__ == '__main__':
    main()
