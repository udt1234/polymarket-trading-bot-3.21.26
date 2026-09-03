# -*- coding: utf-8 -*-
"""REWARD-FARMING MAKER replay on REAL recorded WEATHER-market L2, with causal cancel
defenses. Weather variant of reward_farm_replay.py (Elon).

Same two measurements as the Elon replay, but on FULL-DEPTH L2 we recorded ourselves
(2026-07-22 -> 2026-07-26) instead of top-of-book pmxt proxies.

(A) REWARD ACCRUAL - Polymarket's published spec (docs.polymarket.com/market-makers/
    liquidity-rewards). Score is sampled EVERY MINUTE:
        S(v,s) = ((v-s)/v)^2 * b   v = rewards_max_spread (cents), s = distance from the
                                   size-cutoff-adjusted midpoint, b = order size
        Qone = sum(S) over bids, Qtwo = sum(S) over asks
        mid in [0.10,0.90]: Q = max( min(Qone,Qtwo), max(Qone/3, Qtwo/3) )   (c = 3)
        mid outside:        Q = min(Qone, Qtwo)             (two-sided REQUIRED)
    Our share of the pool = Q_ours / (Q_ours + Q_observed_book); $ = rate/1440 per minute at
    the market's REAL rewardsDailyRate from Gamma (RATE_FLOOR for markets Gamma has zeroed
    since they closed - verified per-BRACKET, ~$100/day, not per event).
    The adjusted midpoint is recomputed INCLUDING our own orders (self-consistent) and only
    levels >= min_size set the adjusted best bid/ask. Reconstruction fidelity vs the
    exchange-reported best bid/ask: 98.0% of sampled ticks.

(B) PICKOFF LEDGER - event-driven on real ticks and real trade prints. Our quotes are pegged
    to the mid with a re-peg latency (LATENCY_MS), so a fast move leaves a stale quote that
    gets run through. Trade side semantics verified against the data: BUY prints at the ask
    (lifts our ask), SELL prints at the bid (hits our bid). Fill size is CONSERVATIVE: a print
    that would have crossed our quote fills our whole resting size (a taker willing to pay
    through us would have taken all of it); a print exactly AT our price fills min(size, print).
    THREE mark-outs, because a 60-second MID mark-out is not an achievable exit in a book whose
    median spread is 25 cents - you cannot sell at the mid:
        markout_60s   - mid at +MARKOUT_S (the standard, OPTIMISTIC adverse-selection measure)
        markout_touch - the price we could actually TRADE at +MARKOUT_S: exit a long into the
                        bid, a short into the ask. The realistic flatten cost.
        markout_res   - the market's actual resolution (YES -> 0 or 1): the cost of inventory
                        you never exit. The pessimistic bound.
    markout_touch is the honest one and the GO/NO-GO uses it; 60s and res bracket it.

(C) DEFENSES - all CAUSAL / ex-ante (no look-ahead; THE WALL):
        base            quote whenever the book is two-sided and the mid is in the band
        schedW          stop quoting W minutes before the market's PUBLISHED end time
        jumpJ           pull quotes for COOLOFF_S after the mid moves >= J cents inside
                        JUMP_WIN_S (the weather analogue of cancel-on-tweet)
        sched+jump      both
    SPREAD GATE (also causal): only quote when the market's own spread is <= gate cents, i.e.
    only rent books that already have a real two-sided market to lean on.
    Everything is bounded to ts <= published end: a rational farmer has no reward incentive to
    quote past a market's end, so neither rewards nor bleed are counted there.

NO bar resampling: the book is rebuilt tick-by-tick from each `book` snapshot plus every
`price_change` level delta. The one-minute grid is Polymarket's own reward sampling cadence.

Usage: python weather_reward_farm_replay.py [--limit N] [--out DIR] [--by-slug DIR]
"""
import argparse, json, sys, glob
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path("C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot")
SCRATCH = Path("C:/Users/darwi/AppData/Local/Temp/claude/"
               "C--Users-darwi-OneDrive-Desktop-Claude-Code-Personal-PolyMarket-Bot/"
               "bb872879-e724-4d89-b4e2-0266d6d833e5/scratchpad")

# ---------------- knobs (env-overridable for sensitivity runs) ----------------
import os
_l = lambda k, d: [float(x) for x in os.environ[k].split(",")] if os.environ.get(k) else d
S_LIST = _l("S_LIST", [1.0, 2.0, 2.5, 3.0, 4.0])   # quote distance from mid, CENTS
SIZE_LIST = _l("SIZE_LIST", [100, 500, 2500])      # resting size per side, SHARES (>= min_size)
GATES = [None if g < 0 else g for g in _l("GATES", [-1, 10.0, 5.0])]  # quote only if spread <= gate
LATENCY_MS = 500        # re-peg latency: how stale our quote can be when a trade arrives
MARKOUT_S = 60          # mid mark-out horizon
COOLOFF_S = 120         # how long we stay out after a jump trigger
JUMP_WIN_S = 60         # lookback window for the jump trigger
TICK = 0.01
RATE_FLOOR = 100.0      # the recorder only subscribed to markets with rewardsDailyRate >= 100/day;
                        # Gamma zeroes the rate once a market closes, so closed markets fall back
                        # to this CAPTURE FLOOR (a conservative lower bound on their real pool).

DEFENSES = [
    ("base",           None,  None),
    ("sched120",        120,  None),
    ("sched240",        240,  None),
    ("jump2",          None,  2.0),
    ("sched120+jump2",  120,  2.0),
]


def combine_q(qone, qtwo, mid):
    """Polymarket Qmin combination rule (c = 3)."""
    if 0.10 <= mid <= 0.90:
        return max(min(qone, qtwo), max(qone / 3.0, qtwo / 3.0))
    return min(qone, qtwo)


def load_meta():
    m = json.load(open(SCRATCH / "gamma_weather_meta.json"))
    out = {}
    for r in m:
        end_ms = np.nan
        if r.get("end"):
            try:
                end_ms = int(datetime.fromisoformat(r["end"].replace("Z", "+00:00")).timestamp() * 1000)
            except Exception:
                pass
        rate = float(r.get("rate") or 0)
        res = np.nan
        if r.get("closed") and r.get("prices"):
            try:
                p = json.loads(r["prices"])
                v0 = float(p[0])
                if v0 in (0.0, 1.0):
                    res = v0
            except Exception:
                pass
        out[r["slug"]] = dict(
            rate=rate if rate > 0 else RATE_FLOOR, rate_is_observed=rate > 0,
            v=float(r.get("maxspread") or 4.5), minsize=float(r.get("minsize") or 100),
            end_ms=end_ms, closed=bool(r.get("closed")), res_yes=res,
            liq=r.get("liq"), vol=r.get("vol"),
        )
    return out


def book_segments(df):
    """(t0, t1, seed_bids, seed_asks, deltas) segments between full book snapshots."""
    bk = df[df.event_type == "book"]
    if bk.empty:
        return []
    pc = df[df.event_type == "price_change"]
    last_ts = int(df.ts.max())
    bts = bk.ts.to_numpy().astype("int64")
    keep = np.concatenate([bts[1:] != bts[:-1], [True]])   # collapse same-ts snapshots, keep last
    bk = bk[keep]
    bts = bk.ts.to_numpy().astype("int64")
    segs = []
    for i in range(len(bk)):
        t0 = int(bts[i])
        t1 = int(bts[i + 1]) if i + 1 < len(bts) else last_ts + 1
        if t1 - t0 < 60_000:
            continue
        try:
            d = json.loads(bk.iloc[i].data)
        except Exception:
            continue
        seed_b = {round(float(x["price"]), 2): float(x["size"]) for x in d.get("bids", [])}
        seed_a = {round(float(x["price"]), 2): float(x["size"]) for x in d.get("asks", [])}
        segs.append((t0, t1, seed_b, seed_a, pc[(pc.ts >= t0) & (pc.ts < t1)]))
    return segs


def level_matrix(seed, deltas, grid, mask):
    """(len(grid) x n_levels) size matrix + price array from a seeded per-level step function."""
    d = deltas[mask]
    dpx = np.round(d.price.to_numpy(float), 2)
    prices = sorted(set(seed) | set(dpx.tolist()))
    if not prices:
        return np.zeros((len(grid), 0)), np.zeros(0)
    M = np.zeros((len(grid), len(prices)))
    dts = d.ts.to_numpy().astype("int64")
    dsz = d["size"].to_numpy(float)
    for j, p in enumerate(prices):
        sel = dpx == p
        if not sel.any():
            M[:, j] = seed.get(p, 0.0)
            continue
        ts_a = np.concatenate([[grid[0] - 1], dts[sel]])
        sz_a = np.concatenate([[seed.get(p, 0.0)], dsz[sel]])
        idx = np.searchsorted(ts_a, grid, "right") - 1
        idx[idx < 0] = 0
        M[:, j] = sz_a[idx]
    return M, np.array(prices)


def tick_floor(x):
    return np.floor(x / TICK + 1e-9) * TICK


def tick_ceil(x):
    return np.ceil(x / TICK - 1e-9) * TICK


def jump_blocked_series(q_ts, q_mid, jump_c):
    """Causal 'we are out of the market' step function: running max of (trigger_ts + COOLOFF)."""
    ref = np.searchsorted(q_ts, q_ts - JUMP_WIN_S * 1000, "right") - 1
    ref[ref < 0] = 0
    trig = np.abs(q_mid - q_mid[ref]) * 100.0 >= jump_c
    return np.maximum.accumulate(np.where(trig, q_ts + COOLOFF_S * 1000, -1))


def replay_slug(slug, files, meta):
    md = meta.get(slug)
    if md is None:
        return []
    v, minsize = md["v"], md["minsize"]
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df[df.ts > 0].sort_values(["ts", "recv_ts"], kind="mergesort")
    if df.empty:
        return []

    pcq = df[(df.event_type == "price_change") & (df.best_bid > 0) & (df.best_ask > 0)
             & (df.best_ask < 1.0) & (df.best_ask > df.best_bid)]
    if len(pcq) < 50:
        return []
    q_ts = pcq.ts.to_numpy().astype("int64")
    q_bid = pcq.best_bid.to_numpy(float)
    q_ask = pcq.best_ask.to_numpy(float)
    q_mid = (q_bid + q_ask) / 2.0
    ch = np.concatenate([[True], (q_mid[1:] != q_mid[:-1]) | (q_bid[1:] != q_bid[:-1])])
    q_ts, q_mid, q_bid, q_ask = q_ts[ch], q_mid[ch], q_bid[ch], q_ask[ch]

    end_ms = int(md["end_ms"]) if np.isfinite(md["end_ms"]) else int(df.ts.max())
    jump_cs = sorted({j for _, _, j in DEFENSES if j is not None})
    blocked = {j: jump_blocked_series(q_ts, q_mid, j) for j in jump_cs}
    res_yes = md["res_yes"]

    nD, nS, nZ, nG = len(DEFENSES), len(S_LIST), len(SIZE_LIST), len(GATES)
    shp = (nD, nS, nZ, nG)
    rew = np.zeros(shp); shr = np.zeros(shp); cap = np.zeros(shp); mins = np.zeros(shp)
    mk60 = np.zeros(shp); mkres = np.zeros(shp); mktch = np.zeros(shp); edge = np.zeros(shp)
    fills = np.zeros(shp, dtype=int); fsz = np.zeros(shp)
    inband_min = tot_min = 0
    comp_depth_sum = comp_q_sum = spread_sum = 0.0

    # ================= (A) reward accrual, 1-minute reward grid =================
    for (t0, t1, seed_b, seed_a, seg) in book_segments(df):
        grid = np.arange(((t0 // 60000) + 1) * 60000, min(t1, end_ms + 1), 60000)
        if len(grid) == 0:
            continue
        bmask = (seg.side == "BUY").to_numpy()
        Mb, Pb = level_matrix(seed_b, seg, grid, bmask)
        Ma, Pa = level_matrix(seed_a, seg, grid, ~bmask)
        if Pb.size == 0 or Pa.size == 0:
            continue
        blk = {j: blocked[j][np.clip(np.searchsorted(q_ts, grid, "right") - 1, 0, None)] > grid
               for j in jump_cs}
        for gi in range(len(grid)):
            tot_min += 1
            szb, sza = Mb[gi], Ma[gi]
            okb, oka = szb >= minsize, sza >= minsize
            if not okb.any() or not oka.any():
                continue
            abb, aba = Pb[okb].max(), Pa[oka].min()
            if aba <= abb:
                continue
            mid0 = (abb + aba) / 2.0
            if mid0 <= 0.01 or mid0 >= 0.99:
                continue
            inband_min += 1
            mkt_spread_c = (aba - abb) * 100.0
            spread_sum += mkt_spread_c
            t_now = int(grid[gi])
            t_left = (end_ms - t_now) / 60000.0
            gate_ok = [g is None or mkt_spread_c <= g for g in GATES]
            if not any(gate_ok):
                continue
            for si, s in enumerate(S_LIST):
                pb, pa = tick_floor(mid0 - s / 100.0), tick_ceil(mid0 + s / 100.0)
                if pb < 0.01 or pa > 0.99 or pb >= pa:
                    continue
                # self-consistent adjusted midpoint INCLUDING our own >= min_size orders
                mid = (max(abb, pb) + min(aba, pa)) / 2.0
                sbid, sask = (mid - pb) * 100.0, (pa - mid) * 100.0
                if sbid < 0 or sask < 0 or sbid > v or sask > v:
                    continue
                sb_c, sa_c = (mid - Pb) * 100.0, (Pa - mid) * 100.0
                wb = np.where((sb_c >= 0) & (sb_c <= v), ((v - np.clip(sb_c, 0, v)) / v) ** 2, 0.0)
                wa = np.where((sa_c >= 0) & (sa_c <= v), ((v - np.clip(sa_c, 0, v)) / v) ** 2, 0.0)
                q_comp = combine_q(float((wb * szb).sum()), float((wa * sza).sum()), mid)
                if si == 0:
                    comp_q_sum += q_comp
                    comp_depth_sum += float(szb[(sb_c >= 0) & (sb_c <= v)].sum()
                                            + sza[(sa_c >= 0) & (sa_c <= v)].sum())
                fb, fa = ((v - sbid) / v) ** 2, ((v - sask) / v) ** 2
                for zi, sz in enumerate(SIZE_LIST):
                    q_ours = combine_q(fb * sz, fa * sz, mid)
                    if q_ours <= 0:
                        continue
                    share = q_ours / (q_ours + q_comp)
                    capital = sz * (pb + (1.0 - pa))
                    for di, (_, W, J) in enumerate(DEFENSES):
                        if W is not None and t_left <= W:
                            continue
                        if J is not None and blk[J][gi]:
                            continue
                        for ki in range(nG):
                            if not gate_ok[ki]:
                                continue
                            rew[di, si, zi, ki] += md["rate"] / 1440.0 * share
                            shr[di, si, zi, ki] += share
                            cap[di, si, zi, ki] += capital
                            mins[di, si, zi, ki] += 1

    if inband_min < 30:
        return []

    # ================= (B) pickoff ledger, event-driven on real trade prints =================
    tr = df[(df.event_type == "last_trade_price") & (df["size"] > 0) & (df.price > 0)
            & (df.ts <= end_ms)]
    t_ts = tr.ts.to_numpy().astype("int64")
    t_px = tr.price.to_numpy(float)
    t_sz = tr["size"].to_numpy(float)
    t_side = tr.side.to_numpy()
    lag_i = np.searchsorted(q_ts, t_ts - LATENCY_MS, "right") - 1   # our STALE quote anchor
    out_i = np.searchsorted(q_ts, t_ts + MARKOUT_S * 1000, "right") - 1
    for k in range(len(t_ts)):
        li, oi = lag_i[k], out_i[k]
        if li < 0 or oi < 0:
            continue
        mid_l, mid_out = q_mid[li], q_mid[oi]
        if mid_l <= 0.01 or mid_l >= 0.99:
            continue
        mkt_spread_c = (q_ask[li] - q_bid[li]) * 100.0
        gate_ok = [g is None or mkt_spread_c <= g for g in GATES]
        if not any(gate_ok):
            continue
        t_left = (end_ms - t_ts[k]) / 60000.0
        side = t_side[k]
        for si, s in enumerate(S_LIST):
            pb, pa = tick_floor(mid_l - s / 100.0), tick_ceil(mid_l + s / 100.0)
            if pb < 0.01 or pa > 0.99 or pb >= pa:
                continue
            hit_bid = (side == "SELL") and (t_px[k] <= pb + 1e-9)
            hit_ask = (side == "BUY") and (t_px[k] >= pa - 1e-9)
            if not (hit_bid or hit_ask):
                continue
            through = (t_px[k] < pb - 1e-9) if hit_bid else (t_px[k] > pa + 1e-9)
            for zi, sz in enumerate(SIZE_LIST):
                f = sz if through else min(sz, t_sz[k])   # a print THROUGH us takes our whole size
                if hit_bid:
                    p60 = (mid_out - pb) * f
                    ptch = (q_bid[oi] - pb) * f          # flatten a long INTO the bid
                    pres = ((res_yes - pb) * f) if np.isfinite(res_yes) else np.nan
                    e = (mid_l - pb) * f
                else:
                    p60 = (pa - mid_out) * f
                    ptch = (pa - q_ask[oi]) * f          # flatten a short INTO the ask
                    pres = ((pa - res_yes) * f) if np.isfinite(res_yes) else np.nan
                    e = (pa - mid_l) * f
                for di, (_, W, J) in enumerate(DEFENSES):
                    if W is not None and t_left <= W:
                        continue
                    if J is not None and blocked[J][li] > t_ts[k]:
                        continue
                    for ki in range(nG):
                        if not gate_ok[ki]:
                            continue
                        mk60[di, si, zi, ki] += p60
                        mktch[di, si, zi, ki] += ptch
                        if np.isfinite(pres):
                            mkres[di, si, zi, ki] += pres
                        edge[di, si, zi, ki] += e
                        fills[di, si, zi, ki] += 1
                        fsz[di, si, zi, ki] += f

    rows = []
    for di, (dl, W, J) in enumerate(DEFENSES):
        for si, s in enumerate(S_LIST):
            for zi, sz in enumerate(SIZE_LIST):
                for ki, g in enumerate(GATES):
                    m = mins[di, si, zi, ki]
                    if m < 30:
                        continue
                    rows.append(dict(
                        slug=slug, defense=dl, quote_s_c=s, size=sz,
                        gate_c=(-1.0 if g is None else g),
                        quote_minutes=int(m), quote_days=m / 1440.0,
                        avg_share=shr[di, si, zi, ki] / m, avg_capital=cap[di, si, zi, ki] / m,
                        reward_usd=rew[di, si, zi, ki],
                        markout60_usd=mk60[di, si, zi, ki], markoutres_usd=mkres[di, si, zi, ki],
                        markouttouch_usd=mktch[di, si, zi, ki], edge_usd=edge[di, si, zi, ki],
                        net60_usd=rew[di, si, zi, ki] + mk60[di, si, zi, ki],
                        netres_usd=rew[di, si, zi, ki] + mkres[di, si, zi, ki],
                        nettouch_usd=rew[di, si, zi, ki] + mktch[di, si, zi, ki],
                        fills=int(fills[di, si, zi, ki]), filled_shares=fsz[di, si, zi, ki],
                        rate=md["rate"], rate_observed=md["rate_is_observed"],
                        res_yes=md["res_yes"], closed=md["closed"],
                        inband_min=inband_min, book_min=tot_min,
                        avg_mkt_spread_c=spread_sum / max(inband_min, 1),
                        avg_comp_inband_depth=comp_depth_sum / max(inband_min, 1),
                        avg_comp_q=comp_q_sum / max(inband_min, 1),
                    ))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--by-slug", default=str(ROOT / "_DataMetricPulls/weather_recordings/by_slug"))
    ap.add_argument("--out", default=str(ROOT / "_DataMetricPulls/pacing_backtest/audit_out_weather"))
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    meta = load_meta()
    dirs = sorted(Path(a.by_slug).glob("slug=*"))
    if a.limit:
        dirs = dirs[:a.limit]
    print(f"{len(dirs)} slug partitions; {len(meta)} gamma meta rows", flush=True)
    allrows, done, empty = [], 0, 0
    span = [None, None]
    for d in dirs:
        slug = d.name.split("=", 1)[1]
        files = sorted(glob.glob(str(d / "*.parquet")))
        if not files:
            continue
        try:
            r = replay_slug(slug, files, meta)
        except Exception as e:
            print(f"  ERR {slug}: {type(e).__name__} {e}", flush=True)
            continue
        if not r:
            empty += 1
        allrows += r
        done += 1
        if done % 25 == 0:
            print(f"  {done}/{len(dirs)} slugs ({len(allrows)} rows, {empty} unusable)", flush=True)
    df = pd.DataFrame(allrows)
    if df.empty:
        print("NO ROWS"); return
    p = Path(out) / "weather_reward_farm_replay.csv"
    df.to_csv(p, index=False)
    print(f"\nwrote {len(df)} rows -> {p}")
    print(f"markets with usable data: {df.slug.nunique()} (of {done} scanned, {empty} unusable)")


if __name__ == "__main__":
    main()
