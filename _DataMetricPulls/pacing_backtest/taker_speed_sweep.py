# -*- coding: utf-8 -*-
"""TAKER SPEED SWEEP — is SPEED (not maker-vs-taker) the real gate on the Elon tweet edge?

REVEALED PRO RULE (memory, 99.9% conf, 545 events/8 auctions): on a counting tweet the count ticks
up, so the pros SELL the -1 bracket (below the modal favorite) and BUY the +1 bracket (above). Onset
sub-250ms, move ~-2.4c(-1)/+1.6c(+1), extends to 60s with NO fade. Their edge = TAKING the STALE
resting liquidity in the first tens of ms before the book reprices. The FAST taker who hits the stale
quote gets the full move; the SLOW taker gets only the ~+0.24c left after 250ms.

This script simulates the PRO TAKER play at a LATENCY SWEEP and finds the speed threshold where it is
+EV. For each counting tweet T and each latency L, at T+L we TAKE the stale liquidity in the pro
direction by WALKING THE REAL DEPTH LADDER (the 'data' column of the pmxt L2 book events):
  BUY  the +1 bracket by lifting the ask ladder as it stands at T+L,
  SHORT the -1 bracket by hitting the bid ladder as it stands at T+L,
walking real depth for a $CLIP, paying the Polymarket taker fee. Exit at T+30/60s marking against the
real book (secondary: hold-to-resolution vs official Gamma winner). Because the ladder REPRICES after
the tweet, a small L fills at STALE (favorable) prices and a large L does not — that IS the speed edge.

HONESTY / no look-ahead (THE WALL):
- Decisions use only data <= action time. Winner (Gamma) used for scoring hold-to-resolution only.
- Fill price at every ladder level is FLOORED (buys) / CAPPED (shorts) at the DENSE price_change
  best quote at our action time. A stale book snapshot can NOT hand us a pre-jump price: at small L the
  fresh top-of-book is still the pre-tweet quote (edge); at large L it has already repriced (no edge).
- Depth (size per level) comes from the nearest book snapshot <= action time (book events are sparse);
  the fill price is tied to the fresh price_change best. Large clips test whether the edge survives depth.
- We trade EVERY counting tweet (eventfulness is only known ex-post; filtering on it would be look-ahead).

Data: pmxt L2 (api.modules.shared.l2_history), embedded bucket labels + depth ladder. Tweet times:
elon_backfill_2025-09_to_now.parquet (counts_main_feed, ms UTC = same clock as L2.ts). Window: noon-ET
parsed from the slug. Regime A = clean-slug Elon auctions June23 -> July8.
Fee (verified Polymarket formula): taker fee = shares * FEE_RATE * p * (1-p), makers $0. Sports rate =
0.05. We report BOTH FEE_RATE=0.05 (realistic/worst) and 0.0 (zero-fee), because the fee is the crux.
"""
import sys, os, glob, json, math, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.stdout.reconfigure(encoding='utf-8')
from api.modules.shared import l2_history as L

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = os.path.join(ROOT, '_DataMetricPulls', 'pacing_backtest', 'audit_out3'); os.makedirs(OUT, exist_ok=True)
ET = ZoneInfo('America/New_York')
MONTHS = {m.lower(): i for i, m in enumerate(['', 'January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December'])}

# ---- sweep parameters ----
LATS   = [0, 50, 100, 150, 250, 400, 500, 750]      # ms after the tweet we manage to fire (our real path ~52ms)
CLIPS  = [50, 100, 250]                               # $ notional per bracket leg
EXITS  = [30, 60]                                     # seconds to hold before marking against the real book
FEE_RATES = [0.05, 0.0]                               # taker fee rate: 0.05 = verified sports/worst; 0.0 = zero-fee
FRESH_MS = 5000                                       # price_change quote must be <= this old at action time
STALE_BOOK_MS = 300_000                               # ladder shape may be this old (book events are sparse); price still tied to fresh best
PRE_STALE_MS = 300_000                                # pre-tweet mid staleness for picking the modal bracket

SLUGS = [
    'elon-musk-of-tweets-june-23-june-30', 'elon-musk-of-tweets-june-26-july-3',
    'elon-musk-of-tweets-june-29-july-1', 'elon-musk-of-tweets-june-30-july-7',
    'elon-musk-of-tweets-july-2-july-4', 'elon-musk-of-tweets-july-3-july-10',
    'elon-musk-of-tweets-july-4-july-6', 'elon-musk-of-tweets-july-6-july-8',
]

def pbk(l):
    l = str(l).strip()
    try:
        if l.startswith('<'): return (0, int(l[1:]) - 1)
        if l.endswith('+'):   return (int(l[:-1]), 10**9)
        if '-' in l: a, b = l.split('-'); return (int(a), int(b))
        return (int(l), int(l))
    except Exception: return None

def bmid(l):
    r = pbk(l);  lo, hi = r
    return lo + 12.0 if hi >= 10**9 else ((hi + 1) / 2.0 if lo == 0 else (lo + hi) / 2.0)

def noon(slug):
    tk = str(slug).replace('elon-musk-of-tweets-', '').split('-'); mo1 = MONTHS[tk[0].lower()]; d1 = int(tk[1])
    if len(tk) >= 4 and tk[2].lower() in MONTHS: mo2 = MONTHS[tk[2].lower()]; d2 = int(tk[3])
    else: mo2 = mo1; d2 = int(tk[2])
    s = int(pd.Timestamp(datetime(2026, mo1, d1, 12, tzinfo=ET)).timestamp())
    e = int(pd.Timestamp(datetime(2026, mo2, d2, 12, tzinfo=ET)).timestamp())
    return s, e

# ---- tweet stream (same clock as L2.ts) ----
bf = pd.read_parquet(os.path.join(ROOT, '_DataMetricPulls', 'pacing_backtest', 'elon_backfill_ext_to_2026-07-10.parquet'))
bf = bf[bf.counts_main_feed].sort_values('ms'); bfms = bf.ms.to_numpy().astype('int64')

# ---- official Gamma winners (hold-to-resolution scoring only) ----
def gamma_winner(slug):
    try:
        import requests
        r = requests.get('https://gamma-api.polymarket.com/events', params={'slug': slug}, timeout=20)
        j = r.json()
        if not j: return None
        for m in j[0].get('markets', []):
            op = m.get('outcomePrices')
            if isinstance(op, str): op = json.loads(op)
            if op and str(op[0]) == '1':      # outcomes are [YES, NO]; YES==1 -> this bracket won
                return m.get('groupItemTitle')
    except Exception as e:
        print('  [gamma winner fetch failed]', slug, repr(e))
    return None

FILES = L._files('pmxt'); BS = chr(92)
ARR = '[' + ','.join("'" + f.replace(BS, '/') + "'" for f in FILES) + ']'

def load_slug(slug, s, e):
    con = duckdb.connect()
    # sparse full-depth book ladder (small): load all YES book rows in-window
    bk = con.execute(f"""SELECT ts, bucket, CAST(data AS VARCHAR) d FROM read_parquet({ARR})
        WHERE slug='{slug}' AND event_type='book' AND outcome='YES' AND data IS NOT NULL
        AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
    tw = bfms[(bfms >= s * 1000) & (bfms < e * 1000)]
    if len(tw) == 0 or len(bk) == 0:
        con.close(); return None, None, tw
    # dense price_change best quotes, but ONLY inside small windows around each tweet (memory-safe)
    wins = []
    for T in tw:
        wins.append((int(T) - 6000, int(T) + int(max(LATS)) + max(EXITS) * 1000 + 6000))
    wins.sort(); merged = [list(wins[0])]
    for a, b in wins[1:]:
        if a <= merged[-1][1]: merged[-1][1] = max(merged[-1][1], b)
        else: merged.append([a, b])
    con.execute('CREATE TEMP TABLE win(t0 BIGINT, t1 BIGINT)')
    con.executemany('INSERT INTO win VALUES (?,?)', merged)
    pc = con.execute(f"""SELECT p.ts, p.bucket, p.best_bid, p.best_ask FROM read_parquet({ARR}) p, win w
        WHERE p.slug='{slug}' AND p.event_type='price_change' AND p.outcome='YES'
        AND p.best_ask>0 AND p.best_ask<1 AND p.best_bid>=0 AND p.ts>=w.t0 AND p.ts<w.t1
        ORDER BY p.ts""").df()
    con.close()
    return bk, pc, tw

def build_books(bk):
    BK = {}
    for l, sub in bk.groupby('bucket'):
        tss, asks, bids = [], [], []
        for _, r in sub.iterrows():
            try: j = json.loads(r.d)
            except Exception: continue
            a = sorted(((float(x['price']), float(x['size'])) for x in j.get('asks', [])), key=lambda z: z[0])
            b = sorted(((float(x['price']), float(x['size'])) for x in j.get('bids', [])), key=lambda z: -z[0])
            if a or b: tss.append(int(r.ts)); asks.append(a); bids.append(b)
        if tss:
            o = np.argsort(tss); tss = np.array(tss)[o]
            BK[l] = {'ts': tss, 'asks': [asks[i] for i in o], 'bids': [bids[i] for i in o]}
    return BK

def build_pc(pc):
    PC = {}
    for l, sub in pc.groupby('bucket'):
        ts = sub.ts.to_numpy().astype('int64')
        PC[l] = {'ts': ts, 'bid': sub.best_bid.to_numpy(float), 'ask': sub.best_ask.to_numpy(float)}
    return PC

def pc_at(PC, l, t, side, maxstale=FRESH_MS):
    d = PC.get(l)
    if not d: return None
    i = np.searchsorted(d['ts'], t, side='right') - 1
    if i >= 0 and (t - d['ts'][i]) <= maxstale:
        v = d[side][i]
        return float(v) if v and v > 0 else None
    return None

def book_at(BK, l, t, maxstale=STALE_BOOK_MS):
    d = BK.get(l)
    if not d: return None
    i = np.searchsorted(d['ts'], t, side='right') - 1
    if i >= 0 and (t - d['ts'][i]) <= maxstale:
        return d['asks'][i], d['bids'][i]
    return None

def book_mid_at(BK, l, t, maxstale=PRE_STALE_MS):
    q = book_at(BK, l, t, maxstale)
    if not q: return None
    asks, bids = q
    ba = asks[0][0] if asks else None; bb = bids[0][0] if bids else None
    if ba and bb: return (ba + bb) / 2.0
    if ba: return ba
    if bb: return bb
    return None

def walk_buy(asks, floor_px, dollars):
    """Lift the ask ladder for up to `dollars`; each level priced no lower than floor_px (fresh best ask)."""
    spent = 0.0; shares = 0.0
    for p, sz in asks:
        pp = max(p, floor_px); avail = pp * sz; take = min(dollars - spent, avail)
        if take <= 1e-9: continue
        shares += take / pp; spent += take
        if spent >= dollars - 1e-9: break
    return shares, spent

def walk_sell(bids, cap_px, dollars):
    """Hit the bid ladder for up to `dollars` proceeds; each level priced no higher than cap_px (fresh best bid)."""
    got = 0.0; shares = 0.0
    for p, sz in bids:
        pp = min(p, cap_px); avail = pp * sz; take = min(dollars - got, avail)
        if take <= 1e-9 or pp <= 0: continue
        shares += take / pp; got += take
        if got >= dollars - 1e-9: break
    return shares, got

def sell_shares(bids, cap_px, shares):
    got = 0.0; sold = 0.0
    for p, sz in bids:
        pp = min(p, cap_px); take = min(shares - sold, sz)
        if take <= 1e-9: continue
        got += take * pp; sold += take
        if sold >= shares - 1e-9: break
    return got, sold

def buy_shares(asks, floor_px, shares):
    cost = 0.0; bought = 0.0
    for p, sz in asks:
        pp = max(p, floor_px); take = min(shares - bought, sz)
        if take <= 1e-9: continue
        cost += take * pp; bought += take
        if bought >= shares - 1e-9: break
    return cost, bought

def fee(shares, p, rate):
    return shares * rate * p * (1.0 - p)

# ---------------- main sweep ----------------
records = []      # one row per (slug, tweet, latency, clip, direction) at exit; fee applied later per FEE_RATE
hold_records = []
used = []
for slug in SLUGS:
    s, e = noon(slug)
    bk, pc, tw = load_slug(slug, s, e)
    if bk is None or pc is None or len(pc) == 0:
        print(f"skip {slug} (no data)"); continue
    BK = build_books(bk); PC = build_pc(pc)
    order = sorted([l for l in BK.keys() if pbk(l)], key=lambda l: pbk(l)[0])
    idxof = {l: i for i, l in enumerate(order)}
    win = gamma_winner(slug)
    ntw = 0
    for T in tw:
        # pre-tweet modal favorite from book mids (staleness tolerated; decision uses data <= T)
        mids = {}
        for l in order:
            m = book_mid_at(BK, l, int(T))
            if m is not None and 0.0 < m < 1.0: mids[l] = m
        if len(mids) < 3: continue
        modal = max(mids, key=lambda l: mids[l])
        mi = idxof[modal]
        if mi + 1 >= len(order) or mi - 1 < 0: continue
        p1 = order[mi + 1]      # +1  -> BUY (count ticks up)
        m1 = order[mi - 1]      # -1  -> SHORT
        ntw += 1
        hrs_left = (e - T / 1000) / 3600.0
        for L_ms in LATS:
            tb = int(T) + L_ms
            # ---- +1 LONG: lift the ask ladder ----
            fa = pc_at(PC, p1, tb, 'ask'); q = book_at(BK, p1, tb)
            long_ok = fa is not None and q is not None
            # ---- -1 SHORT: hit the bid ladder ----
            fb = pc_at(PC, m1, tb, 'bid'); q2 = book_at(BK, m1, tb)
            short_ok = fb is not None and q2 is not None and fb > 0
            for clip in CLIPS:
                # long entry: FIXED share count n = clip / fresh best ask (a real taker sizes by notional,
                # not by chasing $-target into the ask wall). Walk the real ask ladder for n shares.
                if long_ok:
                    n_l = clip / fa
                    spent_l, sh_l = buy_shares(q[0], fa, n_l)
                    l_entry_vwap = spent_l / sh_l if sh_l > 1e-9 else None
                else:
                    sh_l = 0.0; spent_l = 0.0; l_entry_vwap = None
                # short entry: FIXED share count n = clip / fresh best bid. Walk the real bid ladder for n
                # shares (sizing by $-proceeds would dump into the 0.001 penny bids -> phantom size).
                if short_ok:
                    n_s = clip / fb
                    got_s, sh_s = sell_shares(q2[1], fb, n_s)
                    s_entry_vwap = got_s / sh_s if sh_s > 1e-9 else None
                else:
                    sh_s = 0.0; got_s = 0.0; s_entry_vwap = None
                for exit_s in EXITS:
                    te = tb + exit_s * 1000
                    # long exit: sell +1 at bids
                    if sh_l > 1e-9:
                        fbx = pc_at(PC, p1, te, 'bid'); qx = book_at(BK, p1, te)
                        if fbx is not None and fbx > 0:
                            bids_x = qx[1] if qx else [(fbx, 10**9)]
                            got_lx, sold = sell_shares(bids_x, fbx, sh_l)
                            got_lx += (sh_l - sold) * fbx      # remainder marked at fresh best bid
                            l_exit_vwap = got_lx / sh_l
                            # gross mid-to-mid (isolates the tweet SIGNAL from the bid-ask spread cost)
                            bin_ = pc_at(PC, p1, tb, 'bid'); axo = pc_at(PC, p1, te, 'ask')
                            mid_in = (fa + bin_) / 2 if bin_ else fa; mid_out = (fbx + axo) / 2 if axo else fbx
                            records.append({'slug': slug, 'T': int(T), 'hrs_left': hrs_left, 'dir': 'long', 'lat': L_ms,
                                            'clip': clip, 'exit_s': exit_s, 'shares': sh_l,
                                            'cash': got_lx - spent_l, 'entry_vwap': l_entry_vwap, 'exit_vwap': l_exit_vwap,
                                            'notional': spent_l, 'gross_mid': sh_l * (mid_out - mid_in)})
                    # short exit: buy back -1 at asks
                    if sh_s > 1e-9:
                        fax = pc_at(PC, m1, te, 'ask'); qx = book_at(BK, m1, te)
                        if fax is not None:
                            asks_x = qx[0] if qx else [(fax, 10**9)]
                            cost_sx, bought = buy_shares(asks_x, fax, sh_s)
                            cost_sx += (sh_s - bought) * fax   # remainder covered at fresh best ask
                            s_exit_vwap = cost_sx / sh_s
                            axi = pc_at(PC, m1, tb, 'ask'); bxo = pc_at(PC, m1, te, 'bid')
                            mid_in = (fb + axi) / 2 if axi else fb; mid_out = (fax + bxo) / 2 if bxo else fax
                            records.append({'slug': slug, 'T': int(T), 'hrs_left': hrs_left, 'dir': 'short', 'lat': L_ms,
                                            'clip': clip, 'exit_s': exit_s, 'shares': sh_s,
                                            'cash': got_s - cost_sx, 'entry_vwap': s_entry_vwap, 'exit_vwap': s_exit_vwap,
                                            'notional': got_s, 'gross_mid': sh_s * (mid_in - mid_out)})
                # hold-to-resolution (secondary), clip fixed to first EXIT's entry; score vs Gamma winner
                if win is not None:
                    if sh_l > 1e-9:
                        payoff = sh_l * (1.0 if p1 == win else 0.0)
                        hold_records.append({'slug': slug, 'dir': 'long', 'lat': L_ms, 'clip': clip,
                                             'shares': sh_l, 'cash': payoff - spent_l, 'vwap': l_entry_vwap,
                                             'notional': spent_l})
                    if sh_s > 1e-9:
                        liab = sh_s * (1.0 if m1 == win else 0.0)
                        hold_records.append({'slug': slug, 'dir': 'short', 'lat': L_ms, 'clip': clip,
                                             'shares': sh_s, 'cash': got_s - liab, 'vwap': s_entry_vwap,
                                             'notional': got_s})
    used.append({'slug': slug.replace('elon-musk-of-tweets-', ''), 'tweets': ntw, 'brackets': len(order),
                 'winner': win, 'window': f"{datetime.fromtimestamp(s, ET):%m-%d}->{datetime.fromtimestamp(e, ET):%m-%d}"})
    print(f"done {slug}: {ntw} tweets, {len(order)} brackets, winner={win}")

R = pd.DataFrame(records)
if R.empty:
    print('NO TRADES — aborting'); sys.exit(1)
R.to_csv(os.path.join(OUT, 'taker_speed_trades.csv'), index=False)

def apply_fee(df, rate):
    ef = fee(df['shares'].values, df['entry_vwap'].fillna(0.5).values, rate)
    xf = fee(df['shares'].values, df['exit_vwap'].fillna(0.5).values, rate)
    return df['cash'].values - ef - xf

print('\n' + '=' * 78)
print('AUCTIONS USED (Regime A, clean-slug Elon, June23->July8):')
print(pd.DataFrame(used).to_string(index=False))

lab = {0: '0ms', 50: '50', 100: '100', 150: '150', 250: '250', 400: '400', 500: '500', 750: '750'}
summ = []
for rate in FEE_RATES:
    R2 = R.copy(); R2['net'] = apply_fee(R2, rate)
    for exit_s in EXITS:
        for combo, sub0 in [('combined', R2[R2.exit_s == exit_s]),
                            ('long', R2[(R2.exit_s == exit_s) & (R2.dir == 'long')]),
                            ('short', R2[(R2.exit_s == exit_s) & (R2.dir == 'short')])]:
            for clip in CLIPS:
                sub = sub0[sub0['clip'] == clip]
                if sub.empty: continue
                for L_ms in LATS:
                    s2 = sub[sub.lat == L_ms]
                    if s2.empty: continue
                    net = s2['net'].sum(); notl = s2['notional'].sum(); n = len(s2)
                    summ.append({'fee': rate, 'exit_s': exit_s, 'play': combo, 'clip': clip, 'lat_ms': L_ms,
                                 'n': n, 'net_$': round(net, 2), 'roi_per_100': round(100 * net / notl, 3) if notl else 0,
                                 'mean_$/clip': round(net / n, 4) if n else 0,
                                 'win_%': round(100 * (s2['net'] > 0).mean(), 1)})
S = pd.DataFrame(summ); S.to_csv(os.path.join(OUT, 'taker_speed_sweep.csv'), index=False)

def curve(fee_rate, exit_s, play, clip):
    d = S[(S.fee == fee_rate) & (S.exit_s == exit_s) & (S.play == play) & (S['clip'] == clip)].sort_values('lat_ms')
    return d

print('\n' + '=' * 78)
print('P&L vs LATENCY  —  ROI per $100 notional, net of taker fee  (the decision curve)')
for rate in FEE_RATES:
    print(f"\n########## FEE_RATE = {rate}  (taker fee = shares*{rate}*p*(1-p) per leg) ##########")
    for exit_s in EXITS:
        for play in ['combined', 'long', 'short']:
            print(f"\n--- exit T+{exit_s}s | {play} | ROI per $100 by latency (clip=$100) ---")
            d = curve(rate, exit_s, play, 100)
            if d.empty: print('  (no rows)'); continue
            print('  ' + '  '.join(f"{lab[int(r.lat_ms)]}:{r.roi_per_100:+.2f}" for _, r in d.iterrows()))
            pos = d[d.roi_per_100 > 0]
            be = int(pos.lat_ms.max()) if not pos.empty else None
            print(f"  break-even latency (largest L still +EV): {be if be is not None else 'NONE (never +EV)'}")

# best config by net_$ (combined, over both exits/clips) per fee
print('\n' + '=' * 78)
print('BEST CONFIG by total net $ (combined play):')
for rate in FEE_RATES:
    d = S[(S.fee == rate) & (S.play == 'combined')]
    if d.empty: continue
    b = d.sort_values('net_$', ascending=False).iloc[0]
    print(f"  fee={rate}: lat={int(b.lat_ms)}ms clip=${int(b['clip'])} exit=T+{int(b.exit_s)}s -> "
          f"net ${b['net_$']:+.2f} over n={int(b.n)} | ROI/$100 {b['roi_per_100']:+.3f} | win {b['win_%']}%")

# depth survival: does ROI/$100 hold as clip grows (combined, exit60, best fee case each)?
print('\n' + '=' * 78)
print('DEPTH SURVIVAL — ROI per $100 by clip size (combined, exit T+60s, lat=50ms our real path):')
for rate in FEE_RATES:
    row = []
    for clip in CLIPS:
        d = S[(S.fee == rate) & (S.exit_s == 60) & (S.play == 'combined') & (S['clip'] == clip) & (S.lat_ms == 50)]
        if not d.empty: row.append(f"${clip}:{d.iloc[0].roi_per_100:+.2f}")
    print(f"  fee={rate}: " + '  '.join(row))

# GROSS mid-to-mid (isolates the tweet SIGNAL from the bid-ask spread that the taker must cross)
print('\n' + '=' * 78)
print('SIGNAL vs SPREAD — GROSS mid-to-mid ROI per $100 by latency (combined, clip=$100, no fee).')
print('If gross is +ve but net-taker is -ve, the signal is real but the SPREAD kills the taker (=> maker-only).')
for exit_s in EXITS:
    d = R[(R.exit_s == exit_s) & (R['clip'] == 100)]
    print(f"\n--- exit T+{exit_s}s | combined gross-mid ROI/$100 by latency ---")
    line = []
    for L_ms in LATS:
        s2 = d[d.lat == L_ms]
        if s2.empty: continue
        notl = s2['notional'].sum()
        line.append(f"{lab[L_ms]}:{100*s2['gross_mid'].sum()/notl:+.2f}")
    print('  ' + '  '.join(line))

# LATE-WINDOW slice — the pro edge should concentrate near resolution (a tweet moves brackets more)
print('\n' + '=' * 78)
print('LATE-WINDOW — net-taker (fee 0.05) & gross-mid ROI/$100, combined, clip=$100, exit T+60s, by hrs_left:')
Rf = R.copy(); Rf['net05'] = apply_fee(Rf, 0.05)
for lab_w, lo, hi in [('all', 0, 1e9), ('<=6h', 0, 6), ('<=2h', 0, 2)]:
    d = Rf[(Rf.exit_s == 60) & (Rf['clip'] == 100) & (Rf.hrs_left > lo) & (Rf.hrs_left <= hi)]
    if d.empty: print(f"  {lab_w}: (no rows)"); continue
    print(f"\n  hrs_left {lab_w} (n_tweets-legs={len(d)//len(LATS)} approx):")
    for L_ms in [0, 50, 250, 500]:
        s2 = d[d.lat == L_ms]
        if s2.empty: continue
        notl = s2['notional'].sum()
        print(f"    lat={L_ms:3d}ms: net-taker {100*s2['net05'].sum()/notl:+.2f} | gross-mid "
              f"{100*s2['gross_mid'].sum()/notl:+.2f} | ROI/$100 (n={len(s2)})")

# hold-to-resolution (secondary)
if hold_records:
    H = pd.DataFrame(hold_records)
    print('\n' + '=' * 78)
    print('SECONDARY — HOLD-TO-RESOLUTION vs official Gamma winner (entry taker fee 0.05, no exit fee):')
    H['net'] = H['cash'].values - fee(H['shares'].values, H['vwap'].fillna(0.5).values, 0.05)
    for play in ['combined', 'long', 'short']:
        for L_ms in [0, 50, 250, 500]:
            sub = H[H.lat == L_ms] if play == 'combined' else H[(H.lat == L_ms) & (H.dir == play)]
            sub = sub[sub['clip'] == 100]
            if sub.empty: continue
            notl = sub['notional'].sum()
            print(f"  {play:8s} lat={L_ms:3d}ms clip=$100 -> net ${sub['net'].sum():+.2f} | ROI/$100 "
                  f"{100*sub['net'].sum()/notl:+.2f} | n={len(sub)}")
        print()

print(f"WROTE {os.path.join(OUT, 'taker_speed_sweep.csv')}")
print(f"WROTE {os.path.join(OUT, 'taker_speed_trades.csv')}")
