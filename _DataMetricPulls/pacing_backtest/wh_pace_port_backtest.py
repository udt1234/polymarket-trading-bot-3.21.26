# -*- coding: utf-8 -*-
"""wh_pace_port_backtest.py — Does the LOCKED pace engine (imported from api.modules.shared.
locked_pace, never re-derived) produce a tradeable resting post-only MAKER edge on the White
House #-posts weekly markets (11-23c wide book), where the IDENTICAL model provably cannot beat
the Elon #-tweets market (documented efficient, ~1c wide)? Elon is the CONTROL — same model,
same fill code path, same config.

SCOPE: maker-resting claims-P&L test, both sides, n = resolved AUCTIONS.

Obeys BACKTEST_RULES.md + .claude/agents/backtest-auditor.md construction rules:

  THE WALL      — decision inputs at time T use ONLY tweet counts observed <= T (obs(s,T) from
                  the X-API backfill parquet) and walk-forward priors (daily-anchored windows
                  of the SAME duration that ENDED before this auction started). The Gamma-
                  resolved `winner` is used for SCORING ONLY, never as a decision input.
  LOCKED MODEL  — imports cap15_projection / calib_sigma / bracket_fair straight from
                  api.modules.shared.locked_pace (MODEL_VERSION stamped in RUN_META). Not
                  re-derived here.
  EVENT-DRIVEN  — replays every recorded SELL print (last_trade_price) in true time order;
                  decision timestamps are real trade-print spacing, never a bar grid.
  DATA SOURCE   — L2 via api.modules.shared.l2_history.read_l2(source='recorder'), the tweet-
                  recorder's own 24/7 capture (2026-06-23+), for BOTH families — a single
                  source avoids the documented pmxt+recorder Jun23+ double-count trap. Token
                  discovery uses l2_history._files() (canonical file list) + one slug-filtered
                  duckdb query, because read_l2() has no slug filter and WH/Elon weekly markets
                  OVERLAP in real time (next week's book opens before the prior week resolves) —
                  a tokens+ts-only filter without first discovering the slug-specific token ids
                  would silently mix in a neighbouring week's prints under the same bucket label.

  *** FILL-MODEL FIX (load-bearing — read this before trusting any number from this family of
  scripts) ***
  The existing reference phase_wh_maker.py (cited in .claude/agents/backtest-auditor.md as the
  exemplar for "strict through-fill p<b") checks `hit = (pn < bid)` where `bid` is the AMBIENT
  best_bid at the CURRENT print's own causal snapshot — NOT the price our resting quote is
  actually sitting at (`cur['b']`). Because the events list only contains SELL PRINTS (book
  re-pricing between two consecutive prints is invisible to the loop), whenever the ambient
  book rallies between two prints without an intervening print, our resting quote goes stale
  at its old (lower) price while the loop's `bid` variable keeps climbing with the ambient
  book. The next print then satisfies `pn < bid` (the NEW, higher ambient bid) while `pn` may
  still sit well ABOVE our actual stale resting price `cur['b']` — the code credits a fill at
  our old cheap price for a trade that never came anywhere near it. This is exactly the
  "market/hold baseline shows profit in-sim -> STOP, that's a fill bug" trap BACKTEST_RULES
  warns about: it is the reason phase_wh_maker.py's own printed strict-fill headline shows the
  Elon CONTROL at +124.6% ROI (408 fills) — a documented-efficient book should not maker-profit
  like that. Re-run 2026-07-24, phase_wh_maker.py output reproduced:
      WH:   net=$-49.0  ROI=-100.0%  fills=24   (3 of 5 auctions: ZERO fills)
      ELON: net=$+4236.8 ROI=+124.6% fills=408  95% boot CI=[+175.7,+7589.2]
  This script fixes the comparison to `pn < cur['b']` STRICT (our own resting price is "the
  level" the rule refers to) and `pn <= cur['b']` optimistic. No other fill mechanic changed.

  SETTLEMENT    — winner = Gamma's OFFICIALLY RESOLVED bracket (gamma-api events?slug=,
                  outcomePrices matched PER TOKEN ID against clobTokenIds — never by array
                  position or by parsing question text, so a favorite that is outcome[1]
                  still settles correctly). Cross-checked against the backfill-derived
                  obs(s,e) bucket; auctions where the two DISAGREE are EXCLUDED (both from
                  decisioning and scoring) because a same-window own-count/resolution mismatch
                  means the decision-input data for that auction is not trustworthy, not just
                  the final label.

  *** DATA INTEGRITY FINDING (separate from the headline, flag to Sir) ***
  elon_backfill_ext_to_2026-07-10.parquet's own tweet count MISMATCHES Gamma's officially
  resolved winner for 2 of the first 5 Elon weekly auctions:
      elon-musk-of-tweets-june-19-june-26: backfill obs=218 -> bucket 200-219, Gamma says 240-259
      elon-musk-of-tweets-june-23-june-30: backfill obs=263 -> bucket 260-279, Gamma says 240-259
  The other 3 Elon auctions and all 5 WH auctions match Gamma cleanly. phase_wh_maker.py had
  ZERO gamma cross-check for Elon (`gamma_win={}` in its FAM config) and would have settled
  those two auctions against its own WRONG self-computed winner. This script excludes them
  instead: n_elon = 3, not 5. The backfill file likely needs a clean X-API re-pull for that
  2-week span (see memory: canonical/OSINT scrapes undercount ~2x vs X-API).

  MAKER-ONLY    — rest a post-only bid at best_bid+tick, STRICTLY inside the spread
                  (`qb < ask`), so the sim can never cross -> taker fee is N/A (never paid,
                  never should be). Maker fee = 0. Maker rebate defaulted to 0 (discretionary
                  daily pool, not a guaranteed per-fill credit).
  ZERO-EDGE BASELINE — an "always-quote" control with NO model opinion (quotes whenever
                  post-only-feasible, fixed nominal stake, same fill mechanics) runs alongside
                  the real strategy on both sides. If it shows in-sim profit, that is itself
                  the fill-bug red flag from BACKTEST_RULES Pass D.
  HONEST STATS  — n = resolved AUCTIONS. Per-auction block bootstrap CI (5000 resamples,
                  seeded, reproducible). Single-outlier jackknife (drop the single best
                  auction, check whether the sign flips).
  TICK/PROVENANCE — TICK=0.001 (Polymarket's dynamic thin-book tick). Deterministic (seeded
                  RNG). Per-fill ledger + per-auction summary CSVs written to audit_out3/.
                  RUN_META emitted at the end.
"""
import glob, os, json, math, sys
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, duckdb, httpx
sys.stdout.reconfigure(encoding='utf-8')

ROOT = "C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
PB = ROOT + "/_DataMetricPulls/pacing_backtest"
OUT = PB + "/audit_out3"
os.makedirs(OUT, exist_ok=True)
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if PB not in sys.path: sys.path.insert(0, PB)

from api.modules.shared.locked_pace import cap15_projection, calib_sigma, bracket_fair, MODEL_VERSION  # LOCKED — import, never re-derive
from api.modules.shared.l2_history import read_l2, _files
from run_meta import emit_run_meta

con = duckdb.connect()
ET = ZoneInfo('America/New_York')
GAMMA = "https://gamma-api.polymarket.com"
MON = {m.lower(): i for i, m in enumerate(['', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'])}
SEED = 20260724
TICK = 0.001
GATE_S = 48 * 3600           # 7-day markets: only quote inside the final 48h (Sir's locked gate, same as phase_wh_maker)
BANK = 5000.0; KMULT = 0.25; MAXBET = 0.10
BASELINE_STAKE = 50.0        # zero-edge control: fixed nominal stake per quote, no Kelly (no model opinion to size off)

def pbk(l):
    l = str(l).strip()
    if l.startswith('<'): return (0, int(l[1:]) - 1)
    if l.endswith('+'): return (int(l[:-1]), 10 ** 9)
    if '-' in l:
        a, b = l.split('-'); return (int(a), int(b))
    return (int(l), int(l))

def noon(slug, prefix):
    """ET noon-to-noon window parsed from the market slug (never trade-derived start/end).
    Handles WH (trailing -2026) and Elon (no year in slug)."""
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

FAM = {
 'WH': dict(prefix='white-house-of-tweets-', series='whitehouse-daily-tweets',
    bf=PB + '/wh_backfill_2026-06_to_07.parquet',
    slugs=['white-house-of-tweets-june-19-june-26-2026', 'white-house-of-tweets-june-23-june-30-2026',
           'white-house-of-tweets-june-26-july-3-2026', 'white-house-of-tweets-june-30-july-7-2026',
           'white-house-of-tweets-july-3-july-10-2026']),
 'ELON': dict(prefix='elon-musk-of-tweets-', series='elon-tweets',
    bf=PB + '/elon_backfill_ext_to_2026-07-10.parquet',
    slugs=['elon-musk-of-tweets-june-19-june-26', 'elon-musk-of-tweets-june-23-june-30',
           'elon-musk-of-tweets-june-26-july-3', 'elon-musk-of-tweets-june-30-july-7',
           'elon-musk-of-tweets-july-3-july-10']),
}

# ---------- Gamma settlement truth (per-token match, never array position / question text) ----------
def gamma_winning_tokens(slug):
    """Set of token ids that Gamma resolved to $1 (outcomePrices>=0.999) for this slug's event.
    Returns None on any fetch/parse failure (caller must not silently treat that as 'no winner')."""
    try:
        r = httpx.get(f"{GAMMA}/events", params={"slug": slug}, timeout=20)
        r.raise_for_status()
        ev = r.json()
        markets = ev[0]['markets'] if isinstance(ev, list) and ev else (ev.get('markets') if isinstance(ev, dict) else [])
    except Exception:
        return None
    won = set()
    for m in markets or []:
        if not m.get('closed'):
            continue
        try:
            toks = json.loads(m['clobTokenIds']) if isinstance(m.get('clobTokenIds'), str) else m.get('clobTokenIds')
            prices = json.loads(m['outcomePrices']) if isinstance(m.get('outcomePrices'), str) else m.get('outcomePrices')
        except Exception:
            continue
        if not toks or not prices or len(toks) != len(prices):
            continue
        for tok, px in zip(toks, prices):
            try:
                if float(px) >= 0.999: won.add(str(tok))
            except (TypeError, ValueError):
                continue
    return won

# ---------- walk-forward priors (windows that ENDED before `before`) ----------
def build_priors(pts, before, dur_h):
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
    """Returns (meta, events). events: time-sorted normalized YES-space SELL prints, each
    pre-tagged with the causal top-of-book and the LOCKED per-bracket fair value at that
    instant (obs(s,t) with t<=print-time only -> THE WALL). meta.winner is Gamma-resolved,
    used for SCORING ONLY."""
    cfg = FAM[fam]; s, e = noon(slug, cfg['prefix']); total = (e - s) / 3600

    # token discovery: MUST filter by slug (weekly windows overlap in real time), so this is a
    # raw duckdb query over the canonical recorder file list (read_l2 has no slug filter).
    files = _files('recorder')
    arr = '[' + ','.join("'" + f.replace(os.sep, '/') + "'" for f in files) + ']'
    tk = con.execute(f"SELECT DISTINCT bucket,outcome,CAST(asset_id AS VARCHAR) aid FROM read_parquet({arr},union_by_name=true) WHERE slug='{slug}'").df()
    if tk.empty:
        return dict(s=s, e=e, skip=True, reason='no_l2_tokens'), []
    tok = {}
    for _, x in tk.iterrows(): tok.setdefault(x['bucket'], {})[x['outcome']] = x['aid']
    ranges = {b: pbk(b) for b in tok}
    yes_ids = [v['YES'] for v in tok.values() if 'YES' in v]
    all_ids = [i for v in tok.values() for i in v.values()]
    yid2b = {v['YES']: b for b, v in tok.items() if 'YES' in v}
    nid2b = {v['NO']: b for b, v in tok.items() if 'NO' in v}

    # own-count observed engine (THE WALL: obs(a,b) only ever called with b<=decision time)
    bf = pd.read_parquet(cfg['bf']); bf = bf[bf.counts_main_feed]; pts = np.sort((bf.ms.to_numpy() // 1000).astype('int64'))
    def obs(a_, b_): return int(np.searchsorted(pts, b_) - np.searchsorted(pts, a_))
    actual_bf = obs(s, e)
    winner_bf = next((b for b, (lo, hi) in ranges.items() if lo <= actual_bf <= hi), None)

    # settlement truth: Gamma-resolved, matched PER TOKEN ID (not array position / question text)
    won_tokens = gamma_winning_tokens(slug)
    if won_tokens is None:
        return dict(s=s, e=e, skip=True, reason='gamma_fetch_failed'), []
    winner_gamma = next((b for b, v in tok.items() if v.get('YES') in won_tokens), None)
    if winner_gamma is None:
        return dict(s=s, e=e, skip=True, reason='gamma_no_resolved_winner'), []
    if winner_bf != winner_gamma:
        # DATA INTEGRITY: own-count backfill disagrees with the official resolution for this
        # window -> the decision-input data (not just the final label) is not trustworthy here.
        return dict(s=s, e=e, skip=True, reason=f'backfill_gamma_mismatch(bf={winner_bf},gamma={winner_gamma})',
                    actual_bf=actual_bf, winner_bf=winner_bf, winner_gamma=winner_gamma), []

    pri = build_priors(pts, s, total)
    if pri is None:
        return dict(s=s, e=e, skip=True, reason='no_priors'), []
    rmean, Kk, share = pri

    # price_change top-of-book: the Elon recorder file alone is 30-50M+ rows of price_change
    # across all slugs; even after tokens+ts filtering that's still millions of rows per
    # 7-day window, and read_l2()'s single-level SELECT wrapper can't filter on a window-
    # function's own output (no WHERE-after-LAG in one query level), so materializing the
    # full un-collapsed set through read_l2()+pandas OOMs. Collapse consecutive-identical
    # (best_bid,best_ask) states INSIDE duckdb (matching phase_wh_maker.py's validated
    # pattern) via the SAME canonical file list l2_history._files() uses, cutting millions
    # of ticks down to genuinely-distinct book states before it ever reaches pandas.
    yidl = '(' + ','.join("'" + t + "'" for t in yes_ids) + ')'
    pxdf = con.execute(f"""
      WITH t AS (SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask,
          LAG(best_bid) OVER (PARTITION BY asset_id ORDER BY ts) pb,
          LAG(best_ask) OVER (PARTITION BY asset_id ORDER BY ts) pa
        FROM read_parquet({arr},union_by_name=true)
        WHERE series='{cfg['series']}' AND event_type='price_change' AND asset_id IN {yidl}
          AND best_ask>0 AND ts>={s*1000} AND ts<{e*1000})
      SELECT ts, aid, best_bid, best_ask FROM t WHERE pb IS NULL OR best_bid<>pb OR best_ask<>pa ORDER BY aid, ts""").df()
    if pxdf is None or pxdf.empty:
        return dict(s=s, e=e, skip=True, reason='no_price_change_rows'), []
    book = {}
    for b, v in tok.items():
        yid = v.get('YES')
        if yid is None: continue
        g = pxdf[pxdf.aid == yid]
        if g.empty: continue
        book[b] = (g.ts.to_numpy().astype('int64'), g.best_bid.to_numpy(float), g.best_ask.to_numpy(float))

    # trade prints -> normalized YES-space SELL prints
    trdf = read_l2(tokens=all_ids, since_ms=s * 1000, until_ms=e * 1000, event_types=['last_trade_price'],
                    series=[cfg['series']], source='recorder',
                    cols="ts, CAST(asset_id AS VARCHAR) AS aid, price, size, side")
    n_trades = 0 if trdf is None else len(trdf)
    sells = []
    if trdf is not None and not trdf.empty:
        for _, x in trdf.sort_values('ts').iterrows():
            aid = x['aid']; tsec = int(x['ts']) / 1000.0; side = x['side']; p = float(x['price']); sz = float(x['size'])
            if sz <= 0: continue
            if aid in yid2b and side == 'SELL':
                sells.append((tsec, yid2b[aid], p, sz))
            elif aid in nid2b and side == 'BUY':
                sells.append((tsec, nid2b[aid], 1.0 - p, sz))
    sells.sort(key=lambda r: r[0])

    # pre-tag each SELL print with the CAUSAL book + LOCKED (imported) fair value at that instant
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
        o = obs(s, t)                                   # THE WALL: only tweets with ts<=t
        cp = eh / total
        idx = min(len(share) - 1, max(0, int(eh) - 1))
        c = cap15_projection(o, eh, rh, rmean, Kk, share[idx], cp)   # LOCKED, imported
        sd = calib_sigma(rh)                                        # LOCKED, imported
        raw = {l: bracket_fair(lo, hi, c, sd) for l, (lo, hi) in ranges.items()}   # LOCKED, imported
        tot = sum(raw.values()) or 1.0
        fair = raw[b] / tot
        events.append((tsec, b, pn, sz, bid, ask, fair))
    meta = dict(s=s, e=e, total=total, winner=winner_gamma, winner_bf=winner_bf, actual_bf=actual_bf,
                ranges=ranges, n_buckets=len(tok), n_trades=n_trades, n_sell=len(sells), skip=False)
    return meta, events

def run_config(events, meta, strict, margin, clip, gate, use_model_edge=True):
    """Realistic resting post-only maker. One live bid per bucket. A quote must be armed at a
    STRICTLY EARLIER event than the fill. STRICT fill requires the print to trade BELOW **our
    own resting price** (the FIX — see module docstring), so a stale quote left behind by an
    ambient book rally cannot be phantom-filled. Holds filled shares to Gamma-resolved
    settlement. use_model_edge=False runs the zero-informational-edge baseline control (quotes
    unconditionally whenever post-only-feasible, fixed nominal stake, no pace-model opinion)."""
    s, e, winner = meta['s'], meta['e'], meta['winner']
    live = {}; shares_on = {}; cost = 0.0; nf = 0; dep_b = {}
    ledger = []
    for i, (tsec, b, pn, sz, bid, ask, fair) in enumerate(events):
        t = tsec
        if gate and (e - t) > GATE_S: continue
        if dep_b.get(b, 0.0) >= clip: continue
        cur = live.get(b)
        if cur and cur['idx'] < i and cur['sh'] > 0:
            hit = (pn < cur['b']) if strict else (pn <= cur['b'])   # FIX: our own resting price, not the ambient bid
            if hit:
                room = max(0.0, clip - dep_b.get(b, 0.0))
                fsh = min(cur['sh'], sz, room / cur['b'] if cur['b'] > 0 else 0.0)
                if fsh > 0:
                    cost += fsh * cur['b']; shares_on[b] = shares_on.get(b, 0.0) + fsh; nf += 1
                    dep_b[b] = dep_b.get(b, 0.0) + fsh * cur['b']
                    ledger.append(dict(t=t, bucket=b, fill_price=cur['b'], shares=fsh, print_price=pn,
                                        model_fair=fair, book_bid=bid, book_ask=ask))
                    cur['sh'] -= fsh
                    if cur['sh'] <= 1e-9: live[b] = None; cur = None
        qb = round(bid + TICK, 4)
        if use_model_edge:
            want = (qb < ask) and (0.05 < fair < 0.95) and (fair > ask + margin)
        else:
            want = (qb < ask) and (0.05 < ask < 0.95)   # zero-edge control: no model opinion, just post-only feasibility
        if want:
            c2 = live.get(b)
            if c2 is None or abs(c2['b'] - qb) > 1e-9:
                if use_model_edge:
                    f = (fair - qb) / (1 - qb)
                    stake = min(clip, min(max(f, 0.0) * KMULT, MAXBET) * BANK)
                else:
                    stake = min(clip, BASELINE_STAKE)
                live[b] = {'b': qb, 'sh': (stake / qb) if qb > 0 else 0.0, 'idx': i}
        else:
            live[b] = None
    payout = sum(sh * (1.0 if b == winner else 0.0) for b, sh in shares_on.items())
    net = payout - cost
    for row in ledger:
        row['won'] = (row['bucket'] == winner)
    return net, cost, nf, shares_on, ledger

def boot_ci(per_au, n=5000, seed=SEED):
    if not per_au: return (0.0, 0.0)
    a = np.array(per_au)
    idx = np.random.RandomState(seed).randint(0, len(a), (n, len(a)))
    tot = a[idx].sum(1)
    return float(np.percentile(tot, 2.5)), float(np.percentile(tot, 97.5))

def jackknife(per_au):
    if len(per_au) < 2: return dict(applicable=False)
    total = float(sum(per_au)); i = int(np.argmax(per_au))
    without_best = float(total - per_au[i])
    return dict(applicable=True, total=total, best_auction_net=float(per_au[i]),
                total_without_best_auction=without_best, sign_flip=bool((total > 0) != (without_best > 0)))

def main():
    HL = dict(strict=True, margin=0.03, clip=250, gate=True)   # PRE-REGISTERED headline config (matches phase_wh_maker's own choice) — not swept/cherry-picked
    print("=" * 100)
    print("wh_pace_port_backtest — LOCKED pace engine (imported) as resting post-only MAKER: WH vs ELON control")
    print(f"model_version={MODEL_VERSION} | fill FIX applied (pn<own resting price, not ambient bid) | gamma-verified settlement")
    print("=" * 100)

    slug_cache = {}; per_slug_meta = {}; excluded = []
    for fam in ['WH', 'ELON']:
        print(f"\n########## {fam} ##########")
        for slug in FAM[fam]['slugs']:
            meta, events = precompute_slug(fam, slug)
            slug_cache[(fam, slug)] = (meta, events); per_slug_meta[(fam, slug)] = meta
            if meta.get('skip'):
                print(f"  {slug:<46} SKIP ({meta.get('reason')})")
                excluded.append(dict(fam=fam, slug=slug, reason=meta.get('reason')))
                continue
            print(f"  {slug:<46} winner(gamma)={meta['winner']:<8} bf_obs={meta['actual_bf']:>4} "
                  f"buckets={meta['n_buckets']} trades={meta['n_trades']} sellprints={meta['n_sell']} events={len(slug_cache[(fam,slug)][1])}")

    def run_family(fam, strict, margin, clip, gate, use_model_edge):
        tot_net = tot_dep = 0.0; tot_nf = 0; per_au = []; ledger_all = []; n_used = 0
        for slug in FAM[fam]['slugs']:
            meta, events = slug_cache[(fam, slug)]
            if meta.get('skip') or not events: continue
            net, dep, nf, _, ledger = run_config(events, meta, strict, margin, clip, gate, use_model_edge)
            for row in ledger: row['slug'] = slug; row['fam'] = fam
            ledger_all.extend(ledger)
            tot_net += net; tot_dep += dep; tot_nf += nf; per_au.append(net); n_used += 1
        roi = 100 * tot_net / tot_dep if tot_dep > 0 else 0.0
        return dict(net=tot_net, dep=tot_dep, nf=int(tot_nf), roi=roi, per_au=per_au, n=n_used, ledger=ledger_all)

    # ---- diagnostic sensitivity grid (transparency only — NOT the headline claim) ----
    print("\n----- diagnostic sensitivity grid (strict vs optimistic fill x gate on/off), margin=0.03 clip=250 -----")
    print(f"{'fam':>5} {'strict':>7} {'gate':>5} | {'net':>9} {'ROI':>8} {'nf':>5} {'n_au':>5}")
    for fam in ['WH', 'ELON']:
        for strict in [True, False]:
            for gate in [True, False]:
                r = run_family(fam, strict, 0.03, 250, gate, True)
                print(f"{fam:>5} {str(strict):>7} {str(gate):>5} | {r['net']:>9.1f} {r['roi']:>7.1f}% {r['nf']:>5} {r['n']:>5}")

    # ---- HEADLINE: single pre-registered config, both sides identical, no cherry-picking ----
    wh = run_family('WH', **HL, use_model_edge=True)
    el = run_family('ELON', **HL, use_model_edge=True)
    wh_base = run_family('WH', **HL, use_model_edge=False)
    el_base = run_family('ELON', **HL, use_model_edge=False)

    wlo, whi = boot_ci(wh['per_au']); elo, ehi = boot_ci(el['per_au'])
    wjk = jackknife(wh['per_au']); ejk = jackknife(el['per_au'])
    wblo, wbhi = boot_ci(wh_base['per_au']); eblo, ebhi = boot_ci(el_base['per_au'])

    print("\n" + "=" * 100)
    print(f"HEADLINE  strict={HL['strict']} gate={HL['gate']}(final48h) margin={HL['margin']} clip=${HL['clip']} rebate=0 maker_fee=0")
    print(f"  WH    : n_auctions={wh['n']}  net=${wh['net']:+.1f}  deployed=${wh['dep']:.0f}  ROI={wh['roi']:+.1f}%  fills={wh['nf']}")
    print(f"          per-auction net = {[round(x,1) for x in wh['per_au']]}")
    print(f"          95% block-bootstrap-by-auction total-net CI = [{wlo:+.1f}, {whi:+.1f}]")
    print(f"          jackknife (drop best auction): {wjk}")
    print(f"  ELON  : n_auctions={el['n']}  net=${el['net']:+.1f}  deployed=${el['dep']:.0f}  ROI={el['roi']:+.1f}%  fills={el['nf']}")
    print(f"          per-auction net = {[round(x,1) for x in el['per_au']]}")
    print(f"          95% block-bootstrap-by-auction total-net CI = [{elo:+.1f}, {ehi:+.1f}]")
    print(f"          jackknife (drop best auction): {ejk}")
    print(f"  WH-minus-ELON ROI gap = {wh['roi']-el['roi']:+.1f}%")
    print(f"\n  ZERO-EDGE BASELINE (no model opinion, fixed ${BASELINE_STAKE:.0f} stake, same fill mechanics):")
    print(f"  WH-baseline  : net=${wh_base['net']:+.1f}  fills={wh_base['nf']}  95% CI=[{wblo:+.1f},{wbhi:+.1f}]")
    print(f"  ELON-baseline: net=${el_base['net']:+.1f}  fills={el_base['nf']}  95% CI=[{eblo:+.1f},{ebhi:+.1f}]")
    baseline_red_flag = (wh_base['net'] > 0 and wblo > 0) or (el_base['net'] > 0 and eblo > 0)
    print(f"  baseline_shows_in_sim_profit (RED FLAG if True) = {baseline_red_flag}")

    beats = (wh['net'] > 0 and wlo > 0 and (wh['roi'] - el['roi']) >= 5.0 and not baseline_red_flag)
    print(f"\n  wh_beats_control (WH net>0 & bootstrap-LB>0 & ROI gap>=5% & baseline clean) = {beats}")
    print(f"  excluded auctions (data-integrity or missing-data skips): {excluded}")
    print("=" * 100)

    # ---- ledger + summary CSVs ----
    all_ledger = pd.DataFrame(wh['ledger'] + el['ledger'])
    all_ledger.to_csv(f"{OUT}/wh_pace_port_ledger.csv", index=False)
    summary_rows = []
    for fam, res in [('WH', wh), ('ELON', el)]:
        for i, slug in enumerate([s for s in FAM[fam]['slugs'] if not slug_cache[(fam, s)][0].get('skip')]):
            summary_rows.append(dict(fam=fam, slug=slug, net=res['per_au'][i], winner=per_slug_meta[(fam, slug)]['winner']))
    pd.DataFrame(summary_rows).to_csv(f"{OUT}/wh_pace_port_auction_summary.csv", index=False)

    print("\nRESULT_JSON=" + json.dumps(dict(
        wh_n_auctions=wh['n'], wh_net=round(wh['net'], 2), wh_roi_pct=round(wh['roi'], 2), wh_fills=wh['nf'],
        wh_boot_ci=[round(wlo, 1), round(whi, 1)], wh_jackknife=wjk,
        elon_n_auctions=el['n'], elon_net=round(el['net'], 2), elon_roi_pct=round(el['roi'], 2), elon_fills=el['nf'],
        elon_boot_ci=[round(elo, 1), round(ehi, 1)], elon_jackknife=ejk,
        wh_baseline_net=round(wh_base['net'], 2), elon_baseline_net=round(el_base['net'], 2),
        baseline_red_flag=bool(baseline_red_flag), wh_beats_control=bool(beats),
        excluded=excluded)))

    emit_run_meta(
        script=__file__,
        headline={"wh_net": round(wh['net'], 2), "wh_roi_pct": round(wh['roi'], 2), "wh_n_auctions": wh['n'],
                   "elon_net": round(el['net'], 2), "elon_roi_pct": round(el['roi'], 2), "elon_n_auctions": el['n'],
                   "n_auctions": wh['n'] + el['n'], "wh_beats_control": bool(beats),
                   "baseline_red_flag": bool(baseline_red_flag)},
        data_paths=[PB + "/wh_backfill_2026-06_to_07.parquet", PB + "/elon_backfill_ext_to_2026-07-10.parquet",
                    "_DataMetricPulls/recordings_pulled (l2_history source=recorder)",
                    "gamma-api.polymarket.com/events (live, settlement truth)"],
        window_basis="noon-ET parsed from slug (noon() helper)",
        fills="maker post-only resting-bid, strict through-fill pn<own_resting_price (FIXED vs phase_wh_maker.py's ambient-bid bug), "
              "depth-capped by real trade-print size, maker_fee=0, taker_fee=N/A (never crosses spread), rebate=0",
        trial_count=1,
        scope="claims-pnl maker-resting, WH vs Elon-control, single pre-registered config",
        notes=f"diagnostic sensitivity grid printed (strict/optimistic x gate, 8 configs) for transparency, NOT the headline claim. "
              f"excluded={excluded}. zero-edge baseline control included per BACKTEST_RULES Pass D.",
    )

if __name__ == '__main__':
    main()
