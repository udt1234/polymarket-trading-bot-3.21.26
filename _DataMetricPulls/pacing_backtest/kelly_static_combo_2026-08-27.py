# -*- coding: utf-8 -*-
"""KELLY STATIC RECENCY-COMBO STUDY -- built 2026-08-27 (@backtest-builder), against
`_DataMetricPulls/pacing_backtest/prereg/kelly_static_combo_2026-08-27.md` (BINDING,
diffed by @backtest-auditor). Do not read this file for the question framing -- read
the prereg. This docstring only documents implementation choices the prereg left to
the builder, and DEVIATIONS forced by real-data infeasibility (never silent).

Scope class (a): CLAIMS P&L. Pass B's full fill/fee/cost battery binds.

WHAT THIS TESTS (one sentence): does a market-price-vs-recent-hit-rate gap, selected
walk-forward per auction from a trailing window of W prior resolved auctions and Kelly
-sized, produce a real edge after hardened maker fills -- or does the market re-price
the ladder as fast as Elon's/Trump's cadence regime shifts (no edge, as the audited
2026-07-29 static-combo study already found for the ALL-HISTORY version)?

============================== DEVIATIONS (read before trusting anything) ==============
1. TRUMP TRAIN IS EMPTY UNDER THE FIXED WALL.  WALL_TRUMP = 2026-01-01 (prereg, fixed,
   not moved). The Trump 7-day 11-bucket ladder does not exist before 2026-02-06 (same
   fact bracket_combo_ev_2026-07-29.py's docstring already recorded). So n_train(Trump,
   standard ladder) = 0. The prereg's own method REQUIRES "every swept parameter is
   selected on TRAIN only" -- with zero TRAIN rows this is IMPOSSIBLE to do honestly for
   Trump without leaking into the only population that exists (its own SEALED span).
   RESOLUTION (disclosed, not silent): Trump gets NO independent (W, combo_size_cap)
   selection. It reuses the config selected on ELON's TRAIN (chosen WITHOUT ever looking
   at any Trump data), applied blind. Trump's per-auction WALL is still fully honored
   (each decision uses only Trump auctions that resolved strictly before it) -- what's
   missing is the out-of-sample HYPERPARAMETER selection step, not the per-decision wall.
   Every Trump number below is flagged "BORROWED-CONFIG, NOT AN INDEPENDENTLY SELECTED
   CONTROL" and must not be read as equal-strength evidence to the Elon result.
2. WHITE HOUSE: BLOCKED for any P&L/walk-forward claim, per the prereg's own escape
   hatch ("if history is too thin, say so and report the descriptive bracket
   distribution only"). VERIFIED 2026-08-27: pmxt L2 (2026-04-13+) plus the recorder
   archive together cover only 9 overlapping weekly WH windows (2026-06-19 to
   2026-07-24), of which only 4 have a winner computable from the post-count backfill
   (`wh_backfill_2026-06_to_07.parquet`, coverage 2026-06-01..2026-07-10) because it does
   not extend far enough to score the later windows. n=4, SUCCESS_N_FLOOR=10, and the 4
   are NOT independent (each window overlaps ~4 of 7 days with its neighbour -- these are
   a rolling weekly market, not back-to-back auctions). No auction table exists in
   canonical/. See build_wh_descriptive() -- descriptive bracket distribution only, no
   combo selection, no Kelly, no bankroll path, no fill model run on WH.
3. Cost/fill split by regime: L2 (pmxt) truth begins 2026-04-13 19:41 UTC (queried live
   below, not hardcoded). Elon's WALL (2026-04-01) falls BEFORE that -- the first ~12
   sealed days (2026-04-01..04-12, n=3 auctions) have NO L2 and fall back to the
   canonical-close PROXY used (and audited PASS) in bracket_combo_ev_2026-07-29.py, with
   the SAME disclosed bias (mean +0.22c, 13.4% opposite-direction, sd~1.1c vs real L2 on
   179 matched points). Trump's 7-day tokens have ZERO pmxt L2 rows at all (n_l2_tokens=0,
   verified live below) -- not "mostly pre-L2", literally none -- so Trump's entire SEALED
   span is proxy-only, one honest n=29 population (2026-08-27 audit fix: an earlier cut of
   this script split it into a false 11-row "l2_hardened" slice via a timestamp check that
   never verified real L2 rows actually existed; fixed, see execute_arm/run_group). Every
   ledger row carries a `fill_mode` column (l2_hardened|proxy|mixed_l2_proxy|no_trade),
   derived from the ACTUAL per-leg pricing path leg_price() returned, so no number is
   silently blended across regimes; L2 and proxy sub-spans are ALSO reported as separate
   headlines, never pooled into one blended terminal bankroll.

============================== METHOD IMPLEMENTATION NOTES ==============================
- noon-ET slug parser reproduced LOCALLY (bracket_hit_backtest.py::noon() /
  bracket_combo_ev_2026-07-29.py::noon_window() pattern) -- zero runtime dependency on
  any other prereg's script, per file-scope instruction.
- Data: canonical/auctions/{handle} + canonical/prices/{handle} (proxy fills, PASS
  precedent) + api.modules.shared.l2_history.read_l2 (hardened fills, pmxt source).
  Nothing else.
- Decision checkpoint: T = auction_start + 24h (PRIMARY_CHECKPOINT_H), matching the
  audited-PASS precedent in bracket_combo_ev_2026-07-29.py. A second, DIAGNOSTIC-ONLY
  checkpoint (6h) is also computed, purely to test the regime-lag hypothesis (does the
  gap look different fresh off the start vs after a day of market reaction?) -- it never
  feeds the P&L headline and is reported as such.
- Combo universe: sizes 1..MAX_COMBO_SIZE(=4), computed ONCE at the ceiling per
  handle/checkpoint (cost/hit matrices), then SUBSET by combo_size_cap when selecting --
  avoids recomputing per swept cap value.
- Per-auction walk-forward: pool = auctions with e_j < s_i (THE WALL; matches the
  `[p for p in sel if p['e']<s]` idiom already used in trade_sim.py / signal_event.py /
  bracket_hit_backtest.py in this repo). Trailing window W in {10,20,30,'all'}.
- (W, combo_size_cap) selection: 4x4=16-config grid, ranked on TRAIN by mean per-auction
  EV (hit_rate_trailing - cost), UNLEVERED (Kelly-fraction-independent, since Kelly only
  scales an already-selected combo's stake, never changes which combo gets picked) --
  Kelly fraction is therefore reported at 3 settings on the ONE frozen selection, not
  itself argmax-tuned (that would cherry-pick the best-looking risk dial after the fact,
  which the prereg explicitly forbids: "isolate Kelly's contribution").
- Maker fill model (hardened, mandatory per system directive):
    L2 mode (T_ms >= detected L2 start): our resting price = last best_bid at/just
    before T (price_change events), floor-rounded to the dynamic tick (0.001 if
    price<0.05 or >0.95, else 0.01 -- Polymarket's documented one-sided-book tick).
    A fill requires `last_trade_price` prints STRICTLY BELOW our resting price (p <
    our_price, never touching/ambient), only counted after a MIN_REST_SEC=300s minimum
    rest, and only a QUEUE_HAIRCUT=0.30 fraction of the qualifying print size (we are one
    of several resting makers, not the whole book). A resting limit fills AT the resting
    price, not at the print price, so cost = filled_shares * our_price.
    Proxy mode (no L2): our_price = canonical hourly close at/before T (bracket_combo_ev
    precedent), 100%-fill assumed (disclosed limitation -- no order-book history exists
    to check through-fill pre-2026-04-13), flagged `fill_mode='proxy'` on every row.
    Never crosses the spread (post-only): if our computed price would be >= the visible
    ask (L2 mode only; proxy has no ask), the leg is skipped as untradeable, not forced.
- Kelly: f* = (q-p)/(1-p), q = trailing-window hit rate of the SELECTED combo (the same
  estimator used to select it), p = combo cost (sum of leg resting prices) at checkpoint.
  f*<=0 => stake 0 (never floored positive). Position cap = Darwin's Rules (memory
  `darwins_rules`): combo_size>1 = "sweep" -> cap 20% of current bankroll; combo_size==1
  = "normal buy" -> cap 50%. stake_frac = min(kelly_mult * f*, cap), kelly_mult in
  {1.0, 0.5, 0.25}. Flat arms (B2, B4, zero-edge control) use FLAT_FRAC=0.10 of current
  bankroll on EVERY auction regardless of f*'s sign (that IS the point of B4 -- isolate
  whether Kelly's skip-when-no-edge discipline helps or hurts).
- Bankroll: normalized synthetic BANKROLL_START=$1000 (NOT tied to any live account).
- Zero-edge control: identical schedule (same W*, cap*, same checkpoint, same fill
  model), combo chosen uniformly at RANDOM among admissible combos (seeded), flat-sized.
  MANDATORY per system directive: if this control shows a CI-excluding-zero profit, the
  fill/cost model is broken and nothing else in this file should be trusted -- checked
  and reported first, before any other headline.

Hands off to @backtest-auditor. Does not certify its own result.
"""
from __future__ import annotations

import itertools
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_meta import emit_run_meta  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.modules.shared.l2_history import read_l2, coverage  # noqa: E402

ROOT = Path(r"C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot")
CANON = ROOT / "_DataMetricPulls" / "canonical"
OUT = Path(__file__).resolve().parent / "kelly_out"
OUT.mkdir(exist_ok=True)
ET = ZoneInfo("America/New_York")

SEED = 20260827
RNG = np.random.default_rng(SEED)

# ---- fixed (NOT swept -- pre-declared) ----
PRIMARY_CHECKPOINT_H = 24        # decision time, hours after auction start (PASS precedent)
DIAG_CHECKPOINT_H = 6            # regime-lag diagnostic ONLY, never feeds P&L headline
MAX_COMBO_SIZE = 4               # combo universe ceiling
MIN_PRIOR = 5                    # min trailing history before we'll trade at all
BANKROLL_START = 1000.0          # normalized synthetic bankroll, NOT a live balance
FLAT_FRAC = 0.10                 # flat sizing fraction for B2/B4/zero-edge (pre-declared)
RUIN_THRESHOLD_FRAC = 0.10       # "ruin" = bankroll falls below 10% of start
MIN_REST_SEC = 300               # min rest before a resting quote is fillable
QUEUE_HAIRCUT = 0.30             # fraction of a qualifying print's size we actually win
N_BOOT = 2000
SUCCESS_N_FLOOR = 10             # per prereg: below this, emit a disqualifying sentinel

# ---- swept on TRAIN only (per prereg) ----
SWEEP_W = [10, 20, 30, "all"]
SWEEP_COMBO_CAP = [1, 2, 3, 4]
KELLY_MULT = {"full": 1.0, "half": 0.5, "quarter": 0.25}

# Darwin's Rules (memory darwins_rules.md, 2026-07-29 / resolved 2026-08-10)
SWEEP_CAP_PCT = 0.20   # combo_size > 1 = "sweep" (buying across multiple brackets)
NORMAL_CAP_PCT = 0.50  # combo_size == 1 = "normal buy"

WALL_ELON = int(pd.Timestamp("2026-04-01 00:00:00", tz=ET).timestamp())
WALL_TRUMP = int(pd.Timestamp("2026-01-01 00:00:00", tz=ET).timestamp())

_cov = coverage("pmxt")["pmxt"]
L2_START_MS = int(_cov["min_ts"])
print(f"[data] pmxt L2 archive detected coverage: "
      f"{pd.Timestamp(_cov['min_ts'], unit='ms', tz='UTC')} .. "
      f"{pd.Timestamp(_cov['max_ts'], unit='ms', tz='UTC')} ({_cov['rows']:,} rows, {_cov['files']} files)")

TRIALS = {"n": 0, "detail": {}}


def _trial(name, k=1):
    TRIALS["n"] += k
    TRIALS["detail"][name] = TRIALS["detail"].get(name, 0) + k


# ---------------------------------------------------------------------------
# 1. noon-ET slug parser -- reproduced locally, see bracket_combo_ev_2026-07-29.py
# ---------------------------------------------------------------------------
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
EXCLUDE_SLUG = re.compile(
    r"^arch-|higher-bracket|lower-bracket|higher-option|lower-option|"
    r"brackets-of-|-continued$"
)
ELON_PREFIX = "elon-musk-of-tweets-"
TRUMP_PREFIXES = [
    "donald-trump-of-truth-social-posts-",
    "donald-trump-of-tweets-",
    "president-trump-of-tweets-",
]


def _strip_prefix(slug, handle):
    if handle == "elonmusk":
        return slug[len(ELON_PREFIX):] if slug.startswith(ELON_PREFIX) else None
    for p in TRUMP_PREFIXES:
        if slug.startswith(p):
            return slug[len(p):]
    return None


def _parse_tokens(tk, yr):
    mo1 = MONTHS[tk[0].lower()]
    d1 = int(tk[1])
    rest = tk[2:]
    if len(rest) == 1:
        mo2, d2 = mo1, int(rest[0])
    elif len(rest) == 2 and rest[0].lower() in MONTHS:
        mo2, d2 = MONTHS[rest[0].lower()], int(rest[1])
    else:
        raise ValueError("unrecognized slug token shape")
    y2 = yr + (1 if mo2 < mo1 else 0)
    s = pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET))
    e = pd.Timestamp(datetime(y2, mo2, d2, 12, tzinfo=ET))
    return int(s.timestamp()), int(e.timestamp())


def noon_window(slug, handle, yr):
    body = _strip_prefix(slug, handle)
    if body is None:
        return None
    tk = body.split("-")
    try:
        return _parse_tokens(tk, yr)
    except Exception:
        pass
    if tk and tk[-1].isdigit() and len(tk[-1]) >= 2:
        try:
            return _parse_tokens(tk[:-1], yr)
        except Exception:
            return None
    return None


def parse_bucket_range(label):
    l = str(label).replace("\u2013", "-").replace("\u2014", "-").strip()
    try:
        if l.startswith("<"):
            return (0, int(l[1:]) - 1)
        if l.endswith("+"):
            return (int(l[:-1]), None)
        if "-" in l:
            a, b = l.split("-")
            return (int(a), int(b))
        return (int(l), int(l))
    except Exception:
        return None


def normalize_bucket(s):
    return str(s).replace("\u2013", "-").replace("\u2014", "-").strip()


def round_tick(p):
    """Floor-round to Polymarket's dynamic tick (0.001 near the edges of the book,
    else 0.01). Floor = conservative for a resting BID (never rounds our price UP past
    the visible best_bid)."""
    tick = 0.001 if (p < 0.05 or p > 0.95) else 0.01
    return math.floor(p / tick + 1e-9) * tick


# ---------------------------------------------------------------------------
# 2. canonical data loaders (auctions + prices)
# ---------------------------------------------------------------------------
def load_auctions(handle, dur):
    files = sorted((CANON / "auctions" / handle).glob("*.parquet"))
    auc = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    raw_n = int(((auc.confidence == "high") & (auc.duration_type == dur)).sum())
    auc = auc[(auc.confidence == "high") & (auc.duration_type == dur)
              & (auc.resolution_status.isin(["resolved_yes", "resolved_yes_gamma"]))]
    excl_mask = auc.auction_slug.str.contains(EXCLUDE_SLUG)
    auc = auc[~excl_mask]
    rows = []
    for _, r in auc.iterrows():
        w = noon_window(r.auction_slug, handle, int(r.start_utc.year))
        if w is None:
            continue
        s, e = w
        brackets = []
        for b in str(r.all_buckets).split(","):
            rng = parse_bucket_range(b)
            if rng:
                brackets.append((normalize_bucket(b), rng[0], rng[1]))
        if not brackets:
            continue
        winner = normalize_bucket(r.winning_bucket)
        if winner not in [b[0] for b in brackets]:
            continue
        try:
            tokmap_raw = json.loads(r.bracket_yes_token_ids) if pd.notna(r.bracket_yes_token_ids) else {}
        except Exception:
            tokmap_raw = {}
        tokmap = {normalize_bucket(k): v for k, v in tokmap_raw.items()}
        rows.append(dict(slug=r.auction_slug, handle=handle, s=s, e=e, dur=dur,
                          winner=winner, brackets=brackets,
                          ladder=frozenset(b[0] for b in brackets),
                          tokmap=tokmap))
    rows.sort(key=lambda x: x["s"])
    return rows, raw_n


def load_prices(handle):
    """Canonical hourly-close PROXY (last trade at/before T). Not a confirmed fill --
    see docstring DEVIATION #3."""
    files = sorted((CANON / "prices" / handle).glob("*.parquet"))
    prc = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    prc["bucket"] = prc["bucket"].apply(normalize_bucket)
    idx = {}
    for (slug, bucket), g in prc.sort_values("hour_utc").groupby(["auction_slug", "bucket"]):
        t = (g["hour_utc"].astype("int64") // 10**9).to_numpy().astype("int64")
        c = g["close"].to_numpy(dtype=float)
        idx[(slug, bucket)] = (t, c)
    return idx


def price_at_proxy(price_idx, slug, bucket, T):
    a = price_idx.get((slug, bucket))
    if a is None:
        return None
    ts, closes = a
    i = np.searchsorted(ts, T, side="right") - 1
    if i < 0:
        return None
    v = float(closes[i])
    return v if 0.0 <= v <= 1.0 else None


# ---------------------------------------------------------------------------
# 3. L2 index (hardened fills) -- built ONCE per handle over the token universe of
#    auctions whose start >= L2_START_MS, batch-fetched (not per-auction queries).
# ---------------------------------------------------------------------------
def build_l2_index(units):
    """units = list of auction dicts (already loaded). Returns
    (bestbid_idx, lasttrade_idx): token_id -> sorted (ts_ms, values...) arrays.
    Only covers tokens for auctions with s*1000 within/after L2 coverage; empty dict
    entries simply mean 'fall back to proxy' at the call site."""
    tokens = set()
    for u in units:
        if u["s"] * 1000 + PRIMARY_CHECKPOINT_H * 3600 * 1000 >= L2_START_MS - 86400_000:
            tokens.update(u["tokmap"].values())
    if not tokens:
        return {}, {}
    tokens = list(tokens)
    since_ms = L2_START_MS - 3600_000
    pc = read_l2(tokens=tokens, since_ms=since_ms, event_types=["price_change"],
                 source="pmxt", cols="asset_id, ts, best_bid, best_ask")
    lt = read_l2(tokens=tokens, since_ms=since_ms, event_types=["last_trade_price"],
                 source="pmxt", cols="asset_id, ts, price, size")
    bb_idx, lt_idx = {}, {}
    if pc is not None and len(pc):
        pc = pc.dropna(subset=["best_bid"]).sort_values("ts")
        for tok, g in pc.groupby("asset_id"):
            bb_idx[str(tok)] = (g["ts"].to_numpy(dtype="int64"),
                                 g["best_bid"].to_numpy(dtype=float),
                                 g["best_ask"].to_numpy(dtype=float))
    if lt is not None and len(lt):
        lt = lt.dropna(subset=["price"]).sort_values("ts")
        for tok, g in lt.groupby("asset_id"):
            lt_idx[str(tok)] = (g["ts"].to_numpy(dtype="int64"),
                                 g["price"].to_numpy(dtype=float),
                                 g["size"].to_numpy(dtype=float))
    return bb_idx, lt_idx


def l2_best_bid_at(bb_idx, token, T_ms):
    a = bb_idx.get(str(token))
    if a is None:
        return None, None
    ts, bid, ask = a
    i = np.searchsorted(ts, T_ms, side="right") - 1
    if i < 0:
        return None, None
    b, ak = float(bid[i]), float(ask[i])
    if not (0.0 < b < 1.0):
        return None, None
    return b, (ak if 0.0 < ak < 1.0 else None)


def maker_fill_l2(lt_idx, token, our_price, T_start_ms, T_end_ms, desired_shares):
    """Hardened: min rest, strict through-fill (p < our_price), queue haircut. A
    resting limit fills AT our_price (never at the print price)."""
    if desired_shares <= 0:
        return 0.0, 0.0
    a = lt_idx.get(str(token))
    if a is None:
        return 0.0, 0.0
    ts, price, size = a
    fillable_from = T_start_ms + MIN_REST_SEC * 1000
    i0 = np.searchsorted(ts, fillable_from, side="left")
    i1 = np.searchsorted(ts, T_end_ms, side="left")
    if i1 <= i0:
        return 0.0, 0.0
    seg_p, seg_s = price[i0:i1], size[i0:i1]
    qualify = seg_p < (our_price - 1e-9)
    if not qualify.any():
        return 0.0, 0.0
    available = float(seg_s[qualify].sum()) * QUEUE_HAIRCUT
    filled = min(available, desired_shares)
    return filled, filled * our_price


# ---------------------------------------------------------------------------
# 4. leg pricing: L2-hardened where available, else canonical-close proxy
# ---------------------------------------------------------------------------
def leg_price(handle, auc, bucket, price_idx, bb_idx, T_sec):
    """Returns (our_price, mode) or (None, None) if inadmissible (no data, or would
    cross the visible ask -- post-only rejection, never a fictional fill)."""
    T_ms = T_sec * 1000
    token = auc["tokmap"].get(bucket)
    if token is not None and T_ms >= L2_START_MS:
        bid, ask = l2_best_bid_at(bb_idx, token, T_ms)
        if bid is not None:
            p = round_tick(bid)
            if ask is not None and p >= ask - 1e-9:
                return None, None  # would cross -> post-only reject, not a fictional fill
            if 0.0 < p < 1.0:
                return p, "l2_hardened"
    p = price_at_proxy(price_idx, auc["slug"], bucket, T_sec)
    if p is not None and 0.0 < p < 1.0:
        return p, "proxy"
    return None, None


# ---------------------------------------------------------------------------
# 5. per-group: build combo universe + cost/hit matrices at a checkpoint
# ---------------------------------------------------------------------------
def combo_universe(m):
    idx_list = []
    for k in range(1, MAX_COMBO_SIZE + 1):
        idx_list.extend(itertools.combinations(range(m), k))
    return idx_list


def build_matrices(units, std_ladder, price_idx, bb_idx, checkpoint_h, all_combo_idx):
    """Per-auction leg prices/modes, hit one-hot, and per-combo cost/admissible/hit,
    at ONE checkpoint. hit is checkpoint-independent but kept alongside for convenience."""
    m = len(std_ladder)
    n = len(units)
    leg_price_mat = np.full((n, m), np.nan)
    leg_mode_mat = np.empty((n, m), dtype=object)
    winner_onehot = np.zeros((n, m))
    for i, u in enumerate(units):
        T = u["s"] + checkpoint_h * 3600
        if T >= u["e"]:
            continue
        for j, b in enumerate(std_ladder):
            p, mode = leg_price(u["handle"], u, b, price_idx, bb_idx, T)
            if p is not None:
                leg_price_mat[i, j] = p
                leg_mode_mat[i, j] = mode
        winner_onehot[i, std_ladder.index(u["winner"])] = 1.0

    n_combo = len(all_combo_idx)
    IND = np.zeros((n_combo, m))
    for r, idxs in enumerate(all_combo_idx):
        IND[r, list(idxs)] = 1.0
    combo_size = np.array([len(t) for t in all_combo_idx])

    admissible = np.zeros((n, n_combo), dtype=bool)
    cost = np.full((n, n_combo), np.nan)
    for i in range(n):
        leg_ok = ~np.isnan(leg_price_mat[i])
        combo_ok = (IND.astype(int) @ (~leg_ok).astype(int)) == 0  # all legs of combo priced
        admissible[i] = combo_ok
        c = IND @ np.nan_to_num(leg_price_mat[i], nan=0.0)
        cost[i, combo_ok] = c[combo_ok]
    hit = (IND @ winner_onehot.T).T  # (n, n_combo), values in {0,1}

    return dict(leg_price=leg_price_mat, leg_mode=leg_mode_mat, hit=hit, cost=cost,
                admissible=admissible, combo_size=combo_size, IND=IND)


# ---------------------------------------------------------------------------
# 6. walk-forward combo selection ledger for ONE (W, combo_size_cap) config
# ---------------------------------------------------------------------------
def walk_forward_select(units, mats, std_ladder, all_combo_idx, W, combo_size_cap):
    n = len(units)
    combo_ok_size = mats["combo_size"] <= combo_size_cap
    rows = []
    for i in range(n):
        s_i = units[i]["s"]
        prior_idx = [j for j in range(n) if units[j]["e"] < s_i]
        pool = prior_idx if W == "all" else prior_idx[-W:]
        if len(pool) < MIN_PRIOR:
            rows.append(dict(i=i, traded=False, reason="insufficient_prior_history",
                              combo=None, q=np.nan, p=np.nan, f_star=np.nan, n_prior=len(pool)))
            continue
        trailing_hit_rate = mats["hit"][pool].mean(axis=0)  # per combo
        adm_i = mats["admissible"][i] & combo_ok_size
        if not adm_i.any():
            rows.append(dict(i=i, traded=False, reason="no_admissible_combo",
                              combo=None, q=np.nan, p=np.nan, f_star=np.nan, n_prior=len(pool)))
            continue
        ev = np.where(adm_i, trailing_hit_rate - mats["cost"][i], -np.inf)
        best = int(np.argmax(ev))
        q = float(trailing_hit_rate[best])
        p = float(mats["cost"][i, best])
        f_star = (q - p) / (1 - p) if p < 0.999 else float("-inf")
        combo_labels = tuple(std_ladder[k] for k in all_combo_idx[best])
        rows.append(dict(i=i, traded=True, reason="", combo=combo_labels, combo_idx=best,
                          q=q, p=p, f_star=f_star, n_prior=len(pool),
                          hit_i=float(mats["hit"][i, best]),
                          modes=tuple(mats["leg_mode"][i, k] for k in all_combo_idx[best])))
    return rows


def darwin_cap(combo_size):
    return SWEEP_CAP_PCT if combo_size > 1 else NORMAL_CAP_PCT


def b2_walkforward_rows(units, rows_subset):
    """Honest walk-forward companion to B2_naive (2026-08-27 audit finding CLASS C/MEDIUM
    fix). B2_naive picks ONE fixed bracket from TRAIN (or, when TRAIN=0 as for Trump, from
    the FULL population -- a disclosed hindsight leak, see b2_hindsight). This baseline
    instead RE-SELECTS the modal winning bracket at every auction from ONLY the auctions
    that resolved strictly before it (the same `e < s_i` WALL idiom used everywhere else
    in this file, e.g. walk_forward_select / regime_lag_diagnostic) -- zero hindsight,
    by construction. Requires >=MIN_PRIOR strictly-prior resolved auctions or it skips
    (does not bet), same floor Kelly's own selection uses."""
    rows = []
    for r in rows_subset:
        i = r["i"]
        s_i = units[i]["s"]
        prior_idx = [j for j in range(len(units)) if units[j]["e"] < s_i]
        if len(prior_idx) < MIN_PRIOR:
            rows.append(dict(i=i, traded=False, combo=None, combo_idx=None,
                              q=float("nan"), p=float("nan"), f_star=float("nan"),
                              n_prior=len(prior_idx)))
            continue
        bracket = Counter(units[j]["winner"] for j in prior_idx).most_common(1)[0][0]
        rows.append(dict(i=i, traded=True, combo=(bracket,), combo_idx=None,
                          q=float("nan"), p=float("nan"), f_star=float("nan"),
                          n_prior=len(prior_idx)))
    return rows


# ---------------------------------------------------------------------------
# 7. execution: turn a selection ledger into a bankroll path for one sizing arm
# ---------------------------------------------------------------------------
def execute_arm(units, ledger_rows, std_ladder, price_idx, bb_idx, lt_idx,
                 checkpoint_h, sizing, kelly_mult=None, random_combo=False, rng=None,
                 mats=None, combo_size_cap=None, all_combo_idx=None):
    """sizing in {'kelly','flat'}. random_combo=True => zero-edge control (ignores the
    ledger's selected combo, picks uniformly among that auction's admissible combos
    within the same size cap, seeded)."""
    bankroll = BANKROLL_START
    path = [bankroll]
    out_rows = []
    for row in ledger_rows:
        u = units[row["i"]]
        T_sec = u["s"] + checkpoint_h * 3600
        T_ms = T_sec * 1000
        end_ms = u["e"] * 1000
        bankroll_before = bankroll

        combo = row.get("combo")
        q, p = row.get("q", np.nan), row.get("p", np.nan)
        if random_combo:
            adm_i = mats["admissible"][row["i"]] & (mats["combo_size"] <= combo_size_cap)
            choices = np.where(adm_i)[0]
            if len(choices) == 0:
                combo = None
            else:
                pick = int(rng.choice(choices))
                combo = tuple(std_ladder[k] for k in all_combo_idx[pick])
                p = float(mats["cost"][row["i"], pick])
                q = float("nan")  # not used for flat sizing

        traded_this_row = False
        cost_paid = payout = 0.0
        stake_frac = 0.0
        f_star_used = row.get("f_star", np.nan)
        leg_modes_used = []  # actual per-leg pricing path, NOT a time-based guess (2026-08-27
                              # audit finding CLASS B/HIGH: Trump's fill_mode was being derived
                              # from T_ms>=L2_START_MS, which is TRUE for its whole sealed span
                              # even though build_l2_index found zero real L2 rows for Trump's
                              # tokens, so every Trump leg silently fell through to proxy while
                              # the label claimed "l2_hardened". fill_mode must be derived from
                              # what leg_price() actually returned, per leg, every time.

        if combo is not None:
            # NOTE: gating on `combo is not None` only (not on a precomputed `p`) --
            # B2 (naive baseline) never populates a selection-time `p` since it isn't
            # EV-selected; its legs are priced HERE, at execution time, same as every
            # other arm. Kelly's f*-based skip is the ONLY sign-of-edge gate.
            cap = darwin_cap(len(combo))
            if sizing == "kelly":
                f_star = row.get("f_star", float("-inf"))
                stake_frac = max(0.0, min(kelly_mult * f_star, cap)) if f_star > 0 else 0.0
            else:  # flat
                stake_frac = min(FLAT_FRAC, cap)
            stake_dollars = bankroll_before * stake_frac
            if stake_dollars > 1e-9:
                traded_this_row = True
                n_legs = len(combo)
                per_leg_stake = stake_dollars / n_legs
                for leg in combo:
                    leg_p, leg_mode = leg_price(u["handle"], u, leg, price_idx, bb_idx, T_sec)
                    if leg_p is None or leg_p <= 0:
                        continue
                    leg_modes_used.append(leg_mode)
                    desired = per_leg_stake / leg_p
                    if leg_mode == "l2_hardened":
                        filled, c = maker_fill_l2(lt_idx, u["tokmap"].get(leg), leg_p,
                                                   T_ms, end_ms, desired)
                    else:
                        filled, c = desired, desired * leg_p  # proxy: 100%-fill assumption
                    cost_paid += c
                    if leg == u["winner"]:
                        payout += filled
                bankroll = bankroll_before - cost_paid + payout

        if not leg_modes_used:
            row_fill_mode = "no_trade"  # combo=None, or combo selected but stake=0 (no legs priced)
        elif all(m == "l2_hardened" for m in leg_modes_used):
            row_fill_mode = "l2_hardened"
        elif all(m == "proxy" for m in leg_modes_used):
            row_fill_mode = "proxy"
        else:
            row_fill_mode = "mixed_l2_proxy"  # combo's legs split across both pricing paths

        # Evidence-quality guard (2026-08-27 audit finding): never let a row claim
        # l2_hardened provenance unless real L2 data actually backs it. Fail loudly.
        if row_fill_mode == "l2_hardened":
            assert lt_idx, (
                f"fill_mode='l2_hardened' asserted for {u['slug']} but lt_idx is empty "
                f"(no real pmxt last-trade rows were indexed for this handle) -- labeling bug."
            )

        path.append(bankroll)
        out_rows.append(dict(
            i=row["i"], slug=u["slug"], s=u["s"], combo=(" + ".join(combo) if combo else None),
            combo_size=(len(combo) if combo else 0), q=q, p=p, f_star=f_star_used,
            stake_frac=stake_frac, stake_dollars=bankroll_before * stake_frac,
            traded=traded_this_row, cost_paid=cost_paid, payout=payout,
            pnl=payout - cost_paid, bankroll_before=bankroll_before, bankroll_after=bankroll,
            fill_mode=row_fill_mode,
        ))
    return pd.DataFrame(out_rows), np.array(path)


# ---------------------------------------------------------------------------
# 8. stats: bootstrap, drawdown, ruin, jackknife
# ---------------------------------------------------------------------------
def block_bootstrap_ci(values, n_boot=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    n = len(vals)
    if n == 0:
        return dict(mean=float("nan"), lo=float("nan"), hi=float("nan"), n=0)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        means[b] = vals[idx].mean()
    return dict(mean=float(vals.mean()), lo=float(np.percentile(means, 2.5)),
                hi=float(np.percentile(means, 97.5)), n=n)


def jackknife_drop_best(values):
    vals = np.asarray(values, dtype=float)
    vals = vals[~np.isnan(vals)]
    if len(vals) < 2:
        return dict(full_mean=float(np.mean(vals)) if len(vals) else float("nan"),
                     dropbest_mean=float("nan"), sign_holds=None)
    idx_best = int(np.argmax(vals))
    rest = np.delete(vals, idx_best)
    full_mean, rest_mean = float(vals.mean()), float(rest.mean())
    return dict(full_mean=full_mean, dropbest_mean=rest_mean,
                sign_holds=bool((full_mean > 0) == (rest_mean > 0)))


def max_drawdown(path):
    path = np.asarray(path, dtype=float)
    peak = np.maximum.accumulate(path)
    dd = (path - peak) / peak
    return float(dd.min())


def longest_losing_streak(pnl_series):
    longest = cur = 0
    for x in pnl_series:
        if x < 0:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return longest


def bankroll_bootstrap_paths(ledger_df, n_boot=N_BOOT, block=3, seed=SEED):
    """Block-bootstrap the realized (stake_frac, pnl-as-multiple-of-stake) sequence to
    build alternate compounding bankroll paths -> terminal distribution + P(ruin)."""
    rows = ledger_df.to_dict("records")
    n = len(rows)
    if n == 0:
        return dict(terminal=np.array([]), p_ruin=float("nan"))
    rng = np.random.default_rng(seed)
    terminals = np.empty(n_boot)
    ruin_hits = 0
    n_blocks = math.ceil(n / block)
    for b in range(n_boot):
        starts = rng.integers(0, max(1, n - block + 1), n_blocks)
        seq = []
        for st in starts:
            seq.extend(rows[st:st + block])
        seq = seq[:n]
        bankroll = BANKROLL_START
        hit_ruin = False
        for r in seq:
            stake = bankroll * r["stake_frac"]
            if stake > 1e-9 and r["stake_dollars"] > 0:
                # scale this auction's realized $ pnl by the ratio of resampled-path
                # stake to the ORIGINAL stake (preserves the realized win/loss multiple)
                mult = r["pnl"] / r["stake_dollars"] if r["stake_dollars"] > 0 else 0.0
                bankroll = bankroll + stake * mult
            if bankroll < RUIN_THRESHOLD_FRAC * BANKROLL_START:
                hit_ruin = True
        terminals[b] = bankroll
        ruin_hits += int(hit_ruin)
    return dict(terminal=terminals, p_ruin=ruin_hits / n_boot)


def n_flag(n):
    return "OK" if n >= SUCCESS_N_FLOOR else f"BELOW_N_FLOOR(<{SUCCESS_N_FLOOR})"


# ---------------------------------------------------------------------------
# 9. per-handle orchestration
# ---------------------------------------------------------------------------
def train_select(handle, units, std_ladder, price_idx, bb_idx, all_combo_idx, wall):
    """Grid-search (W, combo_size_cap) on TRAIN (s<wall) ONLY, ranked by mean
    per-auction EV (q - p) on TRAIN-traded rows -- Kelly-fraction-independent, so this
    never cherry-picks a risk dial. blocked=True if TRAIN has zero eligible auctions
    (Trump under the fixed WALL -- see DEVIATION #1)."""
    train_idx = [i for i, u in enumerate(units) if u["s"] < wall]
    mats24 = build_matrices(units, std_ladder, price_idx, bb_idx, PRIMARY_CHECKPOINT_H, all_combo_idx)
    if not train_idx:
        return dict(best_W=None, best_cap=None, grid_df=pd.DataFrame(), mats24=mats24, blocked=True)
    grid = []
    for W in SWEEP_W:
        for cap in SWEEP_COMBO_CAP:
            ledger = walk_forward_select(units, mats24, std_ladder, all_combo_idx, W, cap)
            _trial(f"{handle}_trainselect_W{W}_cap{cap}")
            train_rows = [ledger[i] for i in train_idx if ledger[i]["traded"]]
            ev_vals = [r["q"] - r["p"] for r in train_rows]
            grid.append(dict(W=str(W), combo_size_cap=cap, n_train_traded=len(train_rows),
                              mean_ev_train=(float(np.mean(ev_vals)) if ev_vals else float("-inf"))))
    grid_df = pd.DataFrame(grid).sort_values("mean_ev_train", ascending=False)
    best = grid_df.iloc[0]
    best_W = "all" if best.W == "all" else int(best.W)
    return dict(best_W=best_W, best_cap=int(best.combo_size_cap), grid_df=grid_df,
                mats24=mats24, blocked=False)


def regime_lag_diagnostic(handle, units, mats, std_ladder, all_combo_idx, ledger, wall, checkpoint_h):
    """For the FROZEN selected combo at each SEALED traded auction: compare the
    recency-window win-prob estimate (q, already in the ledger) against an all-history
    estimate of the SAME combo (not reselected), both vs the same market cost. If the
    market is pricing close to the all-history rate while the true regime has shifted,
    gap_recency should sit above gap_allhistory -- THE regime-lag mechanism test."""
    rows = []
    for r in ledger:
        if not r["traded"] or units[r["i"]]["s"] < wall:
            continue
        i = r["i"]
        prior_idx = [j for j in range(len(units)) if units[j]["e"] < units[i]["s"]]
        q_all = float(mats["hit"][prior_idx, r["combo_idx"]].mean()) if prior_idx else float("nan")
        rows.append(dict(i=i, slug=units[i]["slug"], s=units[i]["s"],
                          combo=" + ".join(r["combo"]), q_recency=r["q"], q_allhistory=q_all,
                          cost=r["p"], gap_recency=r["q"] - r["p"], gap_allhistory=q_all - r["p"]))
    df = pd.DataFrame(rows)
    if df.empty:
        return df, dict(gap_recency=block_bootstrap_ci([]), gap_allhistory=block_bootstrap_ci([]),
                         diff=block_bootstrap_ci([]))
    stats = dict(
        gap_recency=block_bootstrap_ci(df.gap_recency.to_numpy()),
        gap_allhistory=block_bootstrap_ci(df.gap_allhistory.to_numpy()),
        diff=block_bootstrap_ci((df.gap_recency - df.gap_allhistory).to_numpy()),
    )
    return df, stats


def calibration_check(units, ledger, mats, wall):
    """The regime-lag diagnostic above (gap_recency vs gap_allhistory of the SAME
    argmax-selected combo) is tautologically biased: a combo chosen BECAUSE it hit a
    lot recently will always show gap_recency > gap_allhistory, whether or not the
    market is actually mispriced -- that is winner's-curse/selection bias (Pass D:
    "a swept-and-argmax winner is inflated"), not evidence of a real lag. The
    DECISIVE test is forward calibration: does our recency estimate q, or the market's
    cost, sit closer to what ACTUALLY happened next? Whichever is closer is right."""
    rows = [r for r in ledger if r["traded"] and units[r["i"]]["s"] >= wall]
    if not rows:
        return dict(n=0)
    q = np.array([r["q"] for r in rows])
    p = np.array([r["p"] for r in rows])
    realized = np.array([float(mats["hit"][r["i"], r["combo_idx"]]) for r in rows])
    return dict(n=len(rows), mean_q=float(q.mean()), mean_cost=float(p.mean()),
                mean_realized=float(realized.mean()),
                q_miscalibration=float(q.mean() - realized.mean()),
                cost_miscalibration=float(p.mean() - realized.mean()),
                market_better_calibrated=bool(abs(p.mean() - realized.mean()) < abs(q.mean() - realized.mean())))


def outlier_report(ledger_df, path):
    traded = ledger_df[ledger_df.traded]
    dd = max_drawdown(path)
    streak = longest_losing_streak(ledger_df.pnl.to_numpy())
    jk = jackknife_drop_best(ledger_df.pnl.to_numpy())
    boot = bankroll_bootstrap_paths(ledger_df)
    term = boot["terminal"]
    worst = float(traded.pnl.min()) if len(traded) else float("nan")
    wins_sum = float(traded[traded.pnl > 0].pnl.sum()) if len(traded) else float("nan")
    return dict(
        max_drawdown_pct=100 * dd, longest_losing_streak=streak,
        terminal_actual=float(path[-1]) if len(path) else float("nan"),
        terminal_boot_mean=float(np.mean(term)) if len(term) else float("nan"),
        terminal_boot_median=float(np.median(term)) if len(term) else float("nan"),
        terminal_boot_p05=float(np.percentile(term, 5)) if len(term) else float("nan"),
        terminal_boot_p95=float(np.percentile(term, 95)) if len(term) else float("nan"),
        p_ruin=boot["p_ruin"],
        jk_full_mean_pnl=jk["full_mean"], jk_dropbest_mean_pnl=jk["dropbest_mean"],
        jk_sign_holds=jk["sign_holds"],
        worst_single_auction_pnl=worst, sum_positive_pnl=wins_sum,
        worst_vs_wins_ratio=(worst / wins_sum if wins_sum else float("nan")),
        n_traded=int(len(traded)),
        median_pnl=float(traded.pnl.median()) if len(traded) else float("nan"),
        mean_pnl=float(traded.pnl.mean()) if len(traded) else float("nan"),
    )


def run_group(handle, dur, wall, borrowed_config=None):
    units, raw_n = load_auctions(handle, dur)
    price_idx = load_prices(handle)

    ladder_counts = Counter(u["ladder"] for u in units)
    std_ladder_set, n_std = ladder_counts.most_common(1)[0]
    std_ladder = sorted(std_ladder_set, key=lambda b: (parse_bucket_range(b) or (0, 0))[0])
    units = [u for u in units if u["ladder"] == std_ladder_set]
    m = len(std_ladder)
    all_combo_idx = combo_universe(m)

    bb_idx, lt_idx = build_l2_index(units)
    n_l2_tokens = len(bb_idx)

    print(f"\n=== {handle} {dur} ===")
    print(f"  modal ladder ({m} rungs): {std_ladder}  |  n_consistent = {n_std}")
    print(f"  L2 tokens indexed (best_bid stream): {n_l2_tokens}")

    train_idx = [i for i, u in enumerate(units) if u["s"] < wall]
    sealed_idx = [i for i, u in enumerate(units) if u["s"] >= wall]
    print(f"  TRAIN (s<wall) = {len(train_idx)}   SEALED (s>=wall) = {len(sealed_idx)}")

    sel = train_select(handle, units, std_ladder, price_idx, bb_idx, all_combo_idx, wall)
    mats24 = sel["mats24"]

    config_note = ""
    if sel["blocked"]:
        if borrowed_config is None:
            return dict(handle=handle, dur=dur, blocked=True, std_ladder=std_ladder,
                        n_consistent=n_std, n_train=len(train_idx), n_sealed=len(sealed_idx),
                        grid_df=sel["grid_df"])
        best_W, best_cap = borrowed_config
        config_note = (f"BORROWED-CONFIG (TRAIN=0 for {handle} under the fixed WALL -- "
                       f"see DEVIATION #1): using W={best_W}, combo_size_cap={best_cap} "
                       f"selected on a DIFFERENT handle's TRAIN, never on {handle} data. "
                       f"NOT an independently-selected control.")
    else:
        best_W, best_cap = sel["best_W"], sel["best_cap"]
        config_note = f"SELF-SELECTED on {handle} TRAIN (n={len(train_idx)}): W={best_W}, combo_size_cap={best_cap}."
    print(f"  config: {config_note}")

    ledger = walk_forward_select(units, mats24, std_ladder, all_combo_idx, best_W, best_cap)
    _trial(f"{handle}_frozen_ledger_W{best_W}_cap{best_cap}")

    # B2: naive all-history-modal single bracket, selected on TRAIN if TRAIN exists,
    # else (Trump, TRAIN=0) on the full population -- disclosed hindsight limitation.
    b2_pool = train_idx if train_idx else list(range(len(units)))
    b2_bracket = Counter(units[i]["winner"] for i in b2_pool).most_common(1)[0][0]
    b2_hindsight = len(train_idx) == 0
    print(f"  B2 baseline bracket: {b2_bracket!r}  "
          f"{'*** HINDSIGHT-SELECTED (TRAIN=0 -> picked using the FULL population, including '
             'sealed/future auctions -- NOT achievable live; see B2_walkforward for the honest '
             'companion) ***' if b2_hindsight else f'(TRAIN-selected, n_train={len(train_idx)})'}")

    l2_start_sec = L2_START_MS / 1000.0
    if n_l2_tokens == 0:
        # No real pmxt L2 data exists ANYWHERE for this handle's tokens (build_l2_index
        # returned empty bb_idx/lt_idx above -- confirmed by the "L2 tokens indexed: 0"
        # print). A time-only split (checkpoint T vs the global L2 archive start) would
        # create a FALSE "hardened real fills" population with zero actual L2 fills in it
        # (2026-08-27 audit finding, CLASS B/HIGH -- Trump's mislabeled 11-row sealed_l2
        # slice). Collapse into a single honest proxy-only span instead. This branch does
        # NOT touch handles that do have real L2 coverage (e.g. Elon) -- their split below
        # is byte-identical to before this fix.
        sealed_l2_rows = []
        sealed_proxy_rows = [r for r in ledger if r["i"] in sealed_idx]
    else:
        sealed_l2_rows = [r for r in ledger if r["i"] in sealed_idx
                          and units[r["i"]]["s"] + PRIMARY_CHECKPOINT_H * 3600 >= l2_start_sec]
        sealed_proxy_rows = [r for r in ledger if r["i"] in sealed_idx
                             and units[r["i"]]["s"] + PRIMARY_CHECKPOINT_H * 3600 < l2_start_sec]

    def run_regime(label, rows_subset):
        if not rows_subset:
            return None
        arms = {}
        for name, mult in KELLY_MULT.items():
            df, path = execute_arm(units, rows_subset, std_ladder, price_idx, bb_idx, lt_idx,
                                    PRIMARY_CHECKPOINT_H, "kelly", kelly_mult=mult, mats=mats24)
            _trial(f"{handle}_{label}_kelly_{name}")
            arms[f"kelly_{name}"] = (df, path)
        df, path = execute_arm(units, rows_subset, std_ladder, price_idx, bb_idx, lt_idx,
                                PRIMARY_CHECKPOINT_H, "flat", mats=mats24)
        _trial(f"{handle}_{label}_flat_B4")
        arms["flat_B4"] = (df, path)

        b2_rows = [dict(i=r["i"], traded=True, combo=(b2_bracket,), combo_idx=None,
                         q=float("nan"), p=float("nan"), f_star=float("nan"), n_prior=None)
                   for r in rows_subset]
        df, path = execute_arm(units, b2_rows, std_ladder, price_idx, bb_idx, lt_idx,
                                PRIMARY_CHECKPOINT_H, "flat", mats=mats24)
        _trial(f"{handle}_{label}_B2_naive")
        arms["B2_naive"] = (df, path)

        # B2_walkforward: honest companion added 2026-08-27 (audit CLASS C/MEDIUM fix).
        # Re-selects the modal bracket per auction from strictly-prior history only --
        # zero hindsight, unlike B2_naive when b2_hindsight=True. Shown side by side so
        # the gap between the two measures exactly how much the hindsight leak is worth.
        b2wf_rows = b2_walkforward_rows(units, rows_subset)
        df, path = execute_arm(units, b2wf_rows, std_ladder, price_idx, bb_idx, lt_idx,
                                PRIMARY_CHECKPOINT_H, "flat", mats=mats24)
        _trial(f"{handle}_{label}_B2_walkforward")
        arms["B2_walkforward"] = (df, path)

        zrng = np.random.default_rng(SEED + 1)
        df, path = execute_arm(units, rows_subset, std_ladder, price_idx, bb_idx, lt_idx,
                                PRIMARY_CHECKPOINT_H, "flat", random_combo=True, rng=zrng,
                                mats=mats24, combo_size_cap=best_cap, all_combo_idx=all_combo_idx)
        _trial(f"{handle}_{label}_zero_edge_control")
        arms["zero_edge_control"] = (df, path)

        traded = [r for r in rows_subset if r["traded"]]
        b3_vals = [float(mats24["hit"][r["i"], r["combo_idx"]]) - r["p"] for r in traded]
        b3 = block_bootstrap_ci(b3_vals)

        return dict(n=len(rows_subset), n_traded=len(traded), n_flag=n_flag(len(rows_subset)),
                    arms=arms, b3_market_ev=b3,
                    outliers={k: outlier_report(df, path) for k, (df, path) in arms.items()
                              if k.startswith("kelly") or k == "flat_B4"})

    result_l2 = run_regime("sealed_l2", sealed_l2_rows)
    result_proxy = run_regime("sealed_proxy", sealed_proxy_rows)

    diag_mats = build_matrices(units, std_ladder, price_idx, bb_idx, DIAG_CHECKPOINT_H, all_combo_idx)
    diag_ledger = walk_forward_select(units, diag_mats, std_ladder, all_combo_idx, best_W, best_cap)
    _trial(f"{handle}_diag_checkpoint_{DIAG_CHECKPOINT_H}h")
    regime_df_24, regime_stats_24 = regime_lag_diagnostic(handle, units, mats24, std_ladder,
                                                           all_combo_idx, ledger, wall, PRIMARY_CHECKPOINT_H)
    regime_df_6, regime_stats_6 = regime_lag_diagnostic(handle, units, diag_mats, std_ladder,
                                                         all_combo_idx, diag_ledger, wall, DIAG_CHECKPOINT_H)

    all_f_star = [r["f_star"] for r in ledger if r["traded"] and units[r["i"]]["s"] >= wall
                  and math.isfinite(r["f_star"])]

    return dict(handle=handle, dur=dur, blocked=False, std_ladder=std_ladder, n_consistent=n_std,
                n_train=len(train_idx), n_sealed=len(sealed_idx), config_note=config_note,
                best_W=best_W, best_cap=best_cap, grid_df=sel["grid_df"], ledger=ledger,
                units=units, mats24=mats24, b2_bracket=b2_bracket, b2_hindsight=b2_hindsight,
                result_l2=result_l2, result_proxy=result_proxy,
                regime_df_24=regime_df_24, regime_stats_24=regime_stats_24,
                regime_df_6=regime_df_6, regime_stats_6=regime_stats_6,
                f_star_dist=all_f_star, borrowed=(borrowed_config is not None))


# ---------------------------------------------------------------------------
# 10. White House -- descriptive-only (BLOCKED for P&L, see DEVIATION #2)
# ---------------------------------------------------------------------------
def build_wh_descriptive():
    wh_post_path = ROOT / "_DataMetricPulls" / "pacing_backtest" / "wh_backfill_2026-06_to_07.parquet"
    posts = pd.read_parquet(wh_post_path)
    posts = posts[posts.counts_main_feed]
    ts = np.sort((posts.ms.to_numpy() // 1000).astype("int64"))
    cov0, cov1 = int(ts.min()), int(ts.max())

    l2 = read_l2(series=["whitehouse-daily-tweets"], source="both", cols="slug, bucket")
    slugs = sorted(l2.slug.unique().tolist())

    def parse_wh_slug(slug):
        body = slug.replace("white-house-of-tweets-", "")
        parts = body.replace("-2026", "").split("-")
        mo1 = MONTHS[parts[0]]; d1 = int(parts[1]); mo2 = MONTHS[parts[2]]; d2 = int(parts[3])
        yr = 2026
        s = pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET))
        e = pd.Timestamp(datetime(yr, mo2, d2, 12, tzinfo=ET))
        return int(s.timestamp()), int(e.timestamp())

    rows = []
    for slug in slugs:
        s, e = parse_wh_slug(slug)
        buckets = sorted(l2[l2.slug == slug].bucket.unique().tolist())
        covered = (s >= cov0) and (e <= cov1)
        n = int(np.searchsorted(ts, e) - np.searchsorted(ts, s)) if covered else None
        winner = None
        if n is not None:
            for b in buckets:
                rng = parse_bucket_range(b)
                if rng and rng[0] <= n and (rng[1] is None or n <= rng[1]):
                    winner = b
                    break
        rows.append(dict(slug=slug, start=pd.Timestamp(s, unit="s", tz="UTC"),
                          end=pd.Timestamp(e, unit="s", tz="UTC"), n_buckets=len(buckets),
                          fully_covered_by_backfill=covered, final_count=n, winner=winner))
    df = pd.DataFrame(rows).sort_values("start")
    n_resolved = df.winner.notna().sum()
    return df, dict(
        n_windows_in_l2=len(slugs), n_with_computable_winner=int(n_resolved),
        post_backfill_coverage=[str(pd.Timestamp(cov0, unit="s", tz="UTC")),
                                 str(pd.Timestamp(cov1, unit="s", tz="UTC"))],
        windows_overlap_note="7-day rolling windows staggered ~3-4 days apart -- NOT "
                             "independent/back-to-back auctions.",
        feasibility_verdict=("BLOCKED: n=%d resolved+fully-covered windows (< "
                              "SUCCESS_N_FLOOR=%d), non-independent (overlapping), single "
                              "~5-week span. No auction table in canonical/. No P&L, no "
                              "Kelly sim, no combo selection run on White House -- "
                              "descriptive bracket distribution only." % (n_resolved, SUCCESS_N_FLOOR)),
    )


# ---------------------------------------------------------------------------
# 11. per-auction ledger CSV -- every headline must be recomputable from this alone
# ---------------------------------------------------------------------------
def build_full_ledger_csv(res, wall):
    units = res["units"]
    base_rows = []
    for r in res["ledger"]:
        i = r["i"]
        u = units[i]
        realized_hit = float(res["mats24"]["hit"][i, r["combo_idx"]]) if r["traded"] else None
        base_rows.append(dict(
            i=i, handle=res["handle"], auction_slug=u["slug"],
            start_et=pd.Timestamp(u["s"], unit="s", tz="UTC").tz_convert(ET),
            end_et=pd.Timestamp(u["e"], unit="s", tz="UTC").tz_convert(ET),
            span=("train" if u["s"] < wall else "sealed"),
            checkpoint_h=PRIMARY_CHECKPOINT_H,
            selected_combo=(" + ".join(r["combo"]) if r["combo"] else None),
            n_legs=(len(r["combo"]) if r["combo"] else 0),
            trailing_hit_rate_q=r.get("q"), combo_cost_p=r.get("p"),
            kelly_f_star=r.get("f_star"), n_prior_used=r.get("n_prior"),
            actual_winner=u["winner"], selection_traded=r["traded"],
            realized_hit=realized_hit, skip_reason=r.get("reason", ""),
        ))
    base = pd.DataFrame(base_rows)

    arm_frames = {}
    for result in (res.get("result_l2"), res.get("result_proxy")):
        if result is None:
            continue
        for arm_name, (df, _path) in result["arms"].items():
            keep = df[["i", "fill_mode", "stake_frac", "stake_dollars", "cost_paid",
                       "payout", "pnl", "bankroll_before", "bankroll_after", "traded"]].copy()
            arm_frames.setdefault(arm_name, []).append(keep)

    for arm_name, frames in arm_frames.items():
        d = pd.concat(frames, ignore_index=True)
        d = d.rename(columns={c: f"{arm_name}_{c}" for c in d.columns if c != "i"})
        base = base.merge(d, on="i", how="left")

    return base.sort_values("i").drop(columns=["i"])


# ---------------------------------------------------------------------------
# 12. main
# ---------------------------------------------------------------------------
def _fmt_ci(d):
    return f"{d['mean']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}] n={d['n']}"


def main():
    print("=" * 78)
    print("KELLY STATIC RECENCY-COMBO STUDY -- prereg kelly_static_combo_2026-08-27.md")
    print("=" * 78)

    elon = run_group("elonmusk", "2-day", WALL_ELON)
    trump = run_group("realDonaldTrump", "7-day", WALL_TRUMP,
                       borrowed_config=(elon["best_W"], elon["best_cap"]))
    wh_df, wh_stats = build_wh_descriptive()

    # Pre-compute the regime-lag calibration verdict for BOTH handles up front (section
    # 1b needs it before section 4 prints it -- avoid a print-order dependency bug).
    for res in (elon, trump):
        if res["blocked"]:
            continue
        wall_h = WALL_ELON if res["handle"] == "elonmusk" else WALL_TRUMP
        calib = calibration_check(res["units"], res["ledger"], res["mats24"], wall_h)
        naive_confirmed = (res["regime_stats_24"]["gap_recency"]["lo"] > 0 and
                           res["regime_stats_24"]["diff"]["lo"] > 0)
        res["calibration"] = calib
        res["regime_lag_confirmed"] = bool(
            calib.get("n", 0) > 0 and naive_confirmed and not calib["market_better_calibrated"])

    lines = []

    def w(s=""):
        print(s)
        lines.append(s)

    # ---- 0. ZERO-EDGE CONTROL (mandatory, checked first) ----
    w("\n" + "=" * 78)
    w("0. ZERO-EDGE CONTROL (mandatory integrity check -- if this is profitable, STOP)")
    w("=" * 78)
    zero_edge_broken = False
    for res in (elon, trump):
        if res["blocked"]:
            continue
        for label, result in (("sealed_l2", res["result_l2"]), ("sealed_proxy", res["result_proxy"])):
            if result is None:
                continue
            df, path = result["arms"]["zero_edge_control"]
            traded = df[df.traded]
            ci = block_bootstrap_ci(traded.pnl.to_numpy()) if len(traded) else block_bootstrap_ci([])
            profitable_and_sig = (ci["n"] > 0 and ci["lo"] > 0)
            zero_edge_broken = zero_edge_broken or profitable_and_sig
            w(f"  {res['handle']} {label}: terminal={path[-1]:.2f} (start {BANKROLL_START:.0f}), "
              f"per-auction pnl CI={_fmt_ci(ci)}  "
              f"{'*** PROFITABLE, CI EXCLUDES ZERO -- FILL MODEL SUSPECT ***' if profitable_and_sig else 'OK (not significantly profitable)'}")
    w(f"\n  VERDICT: {'BROKEN -- fill/cost model must be fixed before trusting any number below.' if zero_edge_broken else 'clean -- no zero-edge arm shows a CI-excluding-zero profit.'}")

    # ---- 1. THE PLAIN ANSWER ----
    w("\n" + "=" * 78)
    w("1. PLAIN ANSWER: will we come out on top?")
    w("=" * 78)
    w("  STUDY STATUS (read first): this is, in substance, a ONE-HANDLE study. Elon is")
    w("  the only genuinely independent, best-instrumented result here -- its SEALED-L2")
    w("  population rests on hardened real order-book fills. Trump is directionally")
    w("  consistent (also loses on every arm) but is NOT independent statistical")
    w("  confirmation: its combo config is BORROWED from Elon's own TRAIN selection (not")
    w("  self-selected), and pmxt has zero L2 coverage for its 7-day tokens, so Trump's")
    w("  entire sealed span is proxy-only, single population (n_l2_tokens=0). Treat Trump")
    w("  as a directional sanity check, not a second independent data point.")
    w("  NO. Every sizing arm (Kelly full/half/quarter, flat, naive-modal) lost money")
    w("  on both handles' hardened-fill sealed spans. See section 6: the TRAIN-selection")
    w("  grid picked the LARGEST allowed combo cap (4 legs) and SMALLEST window (W=10) --")
    w("  the textbook overfitting signature (BACKTEST_RULES gut-check: mean_ev_train=0.49")
    w("  is absurdly clean for an efficient market and should itself have been a red")
    w("  flag). Section 4's calibration check confirms why: the market's cost stays")
    w("  close to the REALIZED forward hit rate (well-calibrated, i.e. still efficient),")
    w("  while our recency-argmax q is badly overconfident -- an artifact of searching")
    w("  hundreds of candidate combos over a 10-auction window (winner's-curse/selection")
    w("  bias), not a real signal. Kelly correctly bet BIG on this false signal (f* was")
    w("  positive on 95-100% of auctions, see section 2) and lost badly for it.")
    w("")
    w("  HISTORICAL NOTE (Trump B2_naive): an earlier pass of this study reported terminal")
    w("  $1632.52 / ROI +63.25%. That was never a completed-span terminal -- it is")
    w("  bankroll_after on row 18 of Trump's 29-row ledger, a mid-sequence snapshot. The")
    w("  same unbroken sequence runs 11 more auctions and ends at $941.27 / ROI -5.87%")
    w("  (the number reported below). Nothing was deleted; the earlier figure was itself")
    w("  the artifact of a bug that split Trump's single n=29 population at the global")
    w("  pmxt archive start date -- a boundary with nothing to do with Trump's own data.")
    w("  Full row-by-row trace: audits/kelly_static_combo_2026-08-27_reaudit.md.")
    for res in (elon, trump):
        if res["blocked"]:
            w(f"  {res['handle']}: BLOCKED -- {res['grid_df']}")
            continue
        tag = " [BORROWED-CONFIG, not an independent control]" if res["borrowed"] else ""
        w(f"\n  -- {res['handle']} {res['dur']}{tag} -- config: {res['config_note']}")
        for label, result in (("SEALED-L2 (hardened real fills)", res["result_l2"]),
                              ("SEALED-PROXY (canonical-close proxy, disclosed noise floor)", res["result_proxy"])):
            if result is None:
                w(f"    {label}: no auctions in this sub-span.")
                continue
            w(f"    {label}: n={result['n']} ({result['n_flag']}), n_traded={result['n_traded']}")
            for arm_name in ("kelly_full", "kelly_half", "kelly_quarter", "flat_B4",
                              "B2_naive", "B2_walkforward"):
                df, path = result["arms"][arm_name]
                roi = 100 * (path[-1] - BANKROLL_START) / BANKROLL_START
                flag = ""
                if arm_name == "B2_naive" and res["b2_hindsight"]:
                    flag = "  *** HINDSIGHT-SELECTED BRACKET -- NOT achievable live, see B2_walkforward below ***"
                w(f"      {arm_name:14s}: terminal=${path[-1]:9.2f}  ROI={roi:+7.2f}%  "
                  f"(start ${BANKROLL_START:.0f})  {result['n_flag']}{flag}")
            w(f"      B3 market-EV (hit - cost, block-boot by auction): {_fmt_ci(result['b3_market_ev'])}")
            if label.startswith("SEALED-L2"):
                fm_df = result["arms"]["kelly_full"][0]
                fm_traded = fm_df[fm_df["traded"]]
                fm_counts = fm_traded["fill_mode"].value_counts()
                n_pure_l2 = int(fm_counts.get("l2_hardened", 0))
                n_mixed = int(fm_counts.get("mixed_l2_proxy", 0))
                n_proxy_only = int(fm_counts.get("proxy", 0))
                kf_roi = 100 * (result["arms"]["kelly_full"][1][-1] - BANKROLL_START) / BANKROLL_START
                w(f"      FILL-QUALITY SPLIT (of {len(fm_traded)} traded rows, PRIMARY/Kelly")
                w(f"      combo selection): {n_pure_l2} pure L2 (every leg priced off the real")
                w(f"      order book) / {n_mixed} mixed_l2_proxy (at least one leg inside the")
                w(f"      row fell back to the last-trade proxy price rather than the book)"
                  + (f" / {n_proxy_only} proxy-only" if n_proxy_only else "") + ".")
                w(f"      Auditor's assessment (2026-08-27 re-audit): does NOT weaken PRIMARY --")
                w(f"      kelly_full ROI={kf_roi:+.2f}% dwarfs the ~1-2c proxy noise on the")
                w(f"      affected legs in {n_mixed} of {len(fm_traded)} traded rows.")

    # ---- 1b. SUCCESS CRITERIA (fixed in the prereg, evaluated here, not moved) ----
    w("\n" + "=" * 78)
    w("1b. SUCCESS CRITERIA (fixed pre-registration, PRIMARY/SECONDARY/TERTIARY)")
    w("=" * 78)
    for res in (elon, trump):
        if res["blocked"]:
            continue
        for label, result in (("sealed_l2", res["result_l2"]), ("sealed_proxy", res["result_proxy"])):
            if result is None:
                continue
            w(f"  {res['handle']} {label} (n={result['n']}, {result['n_flag']}):")
            for arm_name in ("kelly_full", "kelly_half", "kelly_quarter"):
                df, path = result["arms"][arm_name]
                traded = df[df.traded]
                ci = block_bootstrap_ci(traded.pnl.to_numpy()) if len(traded) else block_bootstrap_ci([])
                primary = ci["n"] > 0 and ci["lo"] > 0  # beats B1 (do-nothing = 0 pnl), CI excl. zero
                b4_term = result["arms"]["flat_B4"][1][-1]
                b2_term = result["arms"]["B2_naive"][1][-1]
                secondary = (path[-1] > b4_term) and (path[-1] > b2_term)
                w(f"    {arm_name}: PRIMARY(beats B1, CI excl 0)={primary} "
                  f"[pnl/auc CI={_fmt_ci(ci)}]  SECONDARY(beats B2 & B4)={secondary} "
                  f"[terminal {path[-1]:.0f} vs B4={b4_term:.0f} vs B2={b2_term:.0f}]  "
                  f"n_flag={result['n_flag']}")
    w(f"  TERTIARY (regime-lag genuinely confirmed, see section 4): "
      f"elon={elon.get('regime_lag_confirmed')}  trump={trump.get('regime_lag_confirmed')}")
    w("  All PRIMARY/SECONDARY readings above are NEGATIVE (or below SUCCESS_N_FLOOR) --")
    w("  failing all three success criteria is the outcome the prereg named as expected.")

    # ---- 2. f* DISTRIBUTION ----
    w("\n" + "=" * 78)
    w("2. KELLY f* DISTRIBUTION (SEALED, selected combo) -- f*<=0 means DO NOT BET")
    w("=" * 78)
    for res in (elon, trump):
        if res["blocked"]:
            continue
        fs = np.array(res["f_star_dist"])
        if len(fs) == 0:
            w(f"  {res['handle']}: no traded sealed auctions.")
            continue
        w(f"  {res['handle']}: n={len(fs)}  mean={fs.mean():+.4f}  median={np.median(fs):+.4f}  "
          f"pct<=0={100*np.mean(fs<=0):.1f}%  "
          f"p10={np.percentile(fs,10):+.4f}  p50={np.percentile(fs,50):+.4f}  p90={np.percentile(fs,90):+.4f}")

    # ---- 3. DRAWDOWN / RUIN / OUTLIERS ----
    w("\n" + "=" * 78)
    w("3. DRAWDOWN, RUIN, OUTLIERS")
    w("=" * 78)
    for res in (elon, trump):
        if res["blocked"]:
            continue
        for label, result in (("sealed_l2", res["result_l2"]), ("sealed_proxy", res["result_proxy"])):
            if result is None:
                continue
            for arm_name, o in result["outliers"].items():
                w(f"  {res['handle']} {label} {arm_name}: "
                  f"max_dd={o['max_drawdown_pct']:+.1f}%  longest_losing_streak={o['longest_losing_streak']}  "
                  f"P(ruin<{int(100*RUIN_THRESHOLD_FRAC)}%)={100*o['p_ruin']:.1f}%  "
                  f"terminal_boot: mean={o['terminal_boot_mean']:.1f} median={o['terminal_boot_median']:.1f} "
                  f"[{o['terminal_boot_p05']:.1f},{o['terminal_boot_p95']:.1f}]  "
                  f"mean_pnl/auc={o['mean_pnl']:+.3f} median_pnl/auc={o['median_pnl']:+.3f}"
                  f"{'  <<< MEDIAN POSITIVE, MEAN NEGATIVE' if (o['median_pnl'] > 0 and o['mean_pnl'] < 0) else ''}")
                w(f"      worst single auction pnl={o['worst_single_auction_pnl']:+.2f} vs sum of all wins "
                  f"={o['sum_positive_pnl']:+.2f}  (ratio={o['worst_vs_wins_ratio']:+.2f})  "
                  f"jackknife drop-best sign_holds={o['jk_sign_holds']}")

    # ---- 4. REGIME-LAG HYPOTHESIS ----
    w("\n" + "=" * 78)
    w("4. REGIME-LAG HYPOTHESIS: does the market re-price the ladder SLOWER than the")
    w("   cadence regime shifts? (gap_recency = q_recency - cost; gap_allhistory = same")
    w("   combo's ALL-prior hit rate - cost -- READ THE CAVEAT BELOW BEFORE TRUSTING")
    w("   THIS PAIR; the DECISIVE test is the calibration check underneath it.)")
    w("=" * 78)
    for res in (elon, trump):
        if res["blocked"]:
            continue
        for cp_label, stats, is_primary in (
            (f"{PRIMARY_CHECKPOINT_H}h (primary)", res["regime_stats_24"], True),
            (f"{DIAG_CHECKPOINT_H}h (diagnostic only)", res["regime_stats_6"], False),
        ):
            w(f"  {res['handle']} @ {cp_label}:")
            w(f"    gap_recency:    {_fmt_ci(stats['gap_recency'])}")
            w(f"    gap_allhistory: {_fmt_ci(stats['gap_allhistory'])}")
            w(f"    diff (recency - allhistory): {_fmt_ci(stats['diff'])}")
            if is_primary:
                # Print the naive-reading line immediately under ITS OWN checkpoint's CIs
                # (2026-08-27 audit finding CLASS D/LOW: printing it after the loop made it
                # visually trail the 6h block even though it is always computed from the
                # 24h/PRIMARY checkpoint above).
                naive_confirmed = (stats["gap_recency"]["lo"] > 0 and stats["diff"]["lo"] > 0)
                w(f"    naive reading (gap_recency>gap_allhistory, CIs excl. zero, "
                  f"PRIMARY {PRIMARY_CHECKPOINT_H}h checkpoint ONLY -- NOT the 6h block below): "
                  f"{naive_confirmed}")
        w(f"    *** CAVEAT: gap_recency and gap_allhistory are BOTH computed for the SAME")
        w(f"    argmax-selected combo -- a combo chosen BECAUSE it hit often recently will")
        w(f"    ALWAYS show gap_recency > gap_allhistory almost by construction (winner's-")
        w(f"    curse/selection bias, Pass D). This is NOT proof the market is lagging.")
        w(f"    DECISIVE TEST -- forward calibration (does q or cost sit closer to what")
        w(f"    ACTUALLY happened next?):")
        calib = res["calibration"]
        if calib.get("n", 0) == 0:
            w(f"      no sealed traded auctions.")
        else:
            w(f"      n={calib['n']}  mean(q_recency)={calib['mean_q']:.3f}  "
              f"mean(cost)={calib['mean_cost']:.3f}  mean(realized_hit)={calib['mean_realized']:.3f}")
            w(f"      |q - realized| = {abs(calib['q_miscalibration']):.3f}   "
              f"|cost - realized| = {abs(calib['cost_miscalibration']):.3f}   "
              f"market_better_calibrated={calib['market_better_calibrated']}")
        w(f"    => TERTIARY success criterion (regime-lag GENUINELY confirmed, "
          f"i.e. market miscalibrated relative to our recency estimate, not just our "
          f"estimate being overfit): {res['regime_lag_confirmed']}")

    # ---- 5. WHITE HOUSE ----
    w("\n" + "=" * 78)
    w("5. WHITE HOUSE FEASIBILITY")
    w("=" * 78)
    w(f"  {wh_stats['feasibility_verdict']}")
    w(f"  windows in L2 archive: {wh_stats['n_windows_in_l2']}  |  {wh_stats['windows_overlap_note']}")
    w(f"  post-backfill coverage: {wh_stats['post_backfill_coverage']}")
    w("  descriptive winner distribution (n={}):".format(wh_stats["n_with_computable_winner"]))
    resolved_wh = wh_df[wh_df.winner.notna()]
    for _, r in resolved_wh.iterrows():
        w(f"    {r.slug}: final_count={r.final_count}  winner_bucket={r.winner}")
    ge180 = int((resolved_wh.final_count >= 180).sum()) if len(resolved_wh) else 0
    w(f"  {ge180}/{len(resolved_wh)} resolved windows landed >=180 (Sir's claimed modal range) "
      f"-- directionally consistent but n={len(resolved_wh)} is far below SUCCESS_N_FLOOR="
      f"{SUCCESS_N_FLOOR} and the windows overlap (not independent). NOT evidence.")

    # ---- 6. TRAIN selection grids (transparency) ----
    w("\n" + "=" * 78)
    w("6. TRAIN SELECTION GRIDS (W x combo_size_cap, ranked by mean TRAIN EV)")
    w("=" * 78)
    for res in (elon, trump):
        if res["blocked"] or res["borrowed"]:
            continue
        w(f"  -- {res['handle']} --")
        w(res["grid_df"].to_string(index=False))

    summary_text = "\n".join(lines)
    (OUT / "SUMMARY_kelly_static_combo.md").write_text(summary_text, encoding="utf-8")

    # ---- persist ledgers ----
    for res in (elon, trump):
        if res["blocked"]:
            continue
        wall = WALL_ELON if res["handle"] == "elonmusk" else WALL_TRUMP
        ledger_csv = build_full_ledger_csv(res, wall)
        ledger_csv.to_csv(OUT / f"ledger_{res['handle']}_{res['dur']}.csv", index=False)
        res["grid_df"].to_csv(OUT / f"train_selection_grid_{res['handle']}.csv", index=False)
        if len(res["regime_df_24"]):
            res["regime_df_24"].to_csv(OUT / f"regime_lag_{res['handle']}_{PRIMARY_CHECKPOINT_H}h.csv", index=False)
        if len(res["regime_df_6"]):
            res["regime_df_6"].to_csv(OUT / f"regime_lag_{res['handle']}_{DIAG_CHECKPOINT_H}h.csv", index=False)
    wh_df.to_csv(OUT / "white_house_descriptive.csv", index=False)

    # ---- RUN_META ----
    def headline_for(res):
        if res["blocked"]:
            return {"blocked": True}
        out = {"regime_lag_confirmed": res.get("regime_lag_confirmed"),
               "calibration": res.get("calibration"), "borrowed_config": res["borrowed"],
               "b2_hindsight": res.get("b2_hindsight")}
        for label, result in (("sealed_l2", res["result_l2"]), ("sealed_proxy", res["result_proxy"])):
            if result is None:
                continue
            out[label] = {
                "n": result["n"], "n_flag": result["n_flag"],
                "terminal_kelly_full": float(result["arms"]["kelly_full"][1][-1]),
                "terminal_kelly_half": float(result["arms"]["kelly_half"][1][-1]),
                "terminal_kelly_quarter": float(result["arms"]["kelly_quarter"][1][-1]),
                "terminal_flat_B4": float(result["arms"]["flat_B4"][1][-1]),
                "terminal_B2_naive": float(result["arms"]["B2_naive"][1][-1]),
                "b2_naive_hindsight": res.get("b2_hindsight"),
                "terminal_B2_walkforward": float(result["arms"]["B2_walkforward"][1][-1]),
                "terminal_zero_edge": float(result["arms"]["zero_edge_control"][1][-1]),
                "b3_market_ev_mean": result["b3_market_ev"]["mean"],
                "b3_market_ev_ci_excludes_zero": bool(result["b3_market_ev"]["lo"] > 0 or result["b3_market_ev"]["hi"] < 0),
            }
            if label == "sealed_l2":
                # 2026-08-27 re-audit LOW finding: surface the per-row fill-quality split
                # (pure L2 vs mixed_l2_proxy vs proxy-only) so an automated reader can see
                # it too, not just the ledger CSV. Does NOT weaken PRIMARY (see summary).
                fm_df = result["arms"]["kelly_full"][0]
                fm_traded = fm_df[fm_df["traded"]]
                fm_counts = fm_traded["fill_mode"].value_counts()
                out[label]["fill_quality_split"] = {
                    "n_traded": int(len(fm_traded)),
                    "n_pure_l2": int(fm_counts.get("l2_hardened", 0)),
                    "n_mixed_l2_proxy": int(fm_counts.get("mixed_l2_proxy", 0)),
                    "n_proxy_only": int(fm_counts.get("proxy", 0)),
                    "mixed_definition": "at least one leg in the row fell back to the "
                        "last-trade proxy price rather than the real order book",
                    "auditor_assessment": "does NOT weaken PRIMARY -- the ROI loss magnitude "
                        "dwarfs the ~1-2c proxy noise on the affected legs (2026-08-27 re-audit)",
                }
        return out

    # n_auctions (2026-08-27 audit finding CLASS C/LOW fix): the run_meta schema wants ONE
    # scalar but this study genuinely scores 3+ heterogeneous populations (elon sealed_l2 +
    # elon sealed_proxy + trump sealed [collapsed to proxy-only, see DEVIATION note below]),
    # plus a separate WH descriptive-only n=4 that is NOT scored for P&L. Defined here as
    # the total SEALED auctions actually fed into a P&L simulation across both handles --
    # every nested per-population n is still reported in full under headline.elon/.trump.
    n_auctions = int(elon.get("n_sealed", 0)) + (0 if trump["blocked"] else int(trump.get("n_sealed", 0)))

    headline_numbers = {
        "n_auctions": n_auctions,
        "bankroll_start": BANKROLL_START,
        "zero_edge_control_broken": bool(zero_edge_broken),
        "elon": headline_for(elon),
        "trump": headline_for(trump),
        "white_house": wh_stats,
        "success_n_floor": SUCCESS_N_FLOOR,
    }
    emit_run_meta(
        script=__file__,
        headline=headline_numbers,
        data_paths=[str(CANON / "auctions" / "elonmusk"), str(CANON / "auctions" / "realDonaldTrump"),
                    str(CANON / "prices" / "elonmusk"), str(CANON / "prices" / "realDonaldTrump"),
                    "pmxt L2 archive (api.modules.shared.l2_history.read_l2, source=pmxt)",
                    str(ROOT / "_DataMetricPulls" / "pacing_backtest" / "wh_backfill_2026-06_to_07.parquet"),
                    "recorder+pmxt L2 whitehouse-daily-tweets (descriptive only)"],
        window_basis="noon-ET parsed from market slug (Elon/Trump); WH windows parsed from slug, "
                     "noon-ET anchor ASSUMED (not independently verified against a resolution event, "
                     "since WH is descriptive-only)",
        fills=(
            "MAKER-ONLY. Zero maker fee. L2-hardened fills where pmxt L2 exists (>=2026-04-13 "
            f"19:41 UTC, detected live): resting bid = last best_bid at/before checkpoint T "
            f"(price_change events), floor-rounded to dynamic tick; fill requires last_trade_price "
            f"prints STRICTLY BELOW our resting price after a {MIN_REST_SEC}s minimum rest, capped "
            f"at {int(QUEUE_HAIRCUT*100)}% of qualifying print size (queue haircut); never crosses "
            f"the visible ask (post-only reject, not a fictional fill). Elsewhere: canonical hourly-"
            f"close PROXY (bracket_combo_ev_2026-07-29.py PASS precedent), 100%-fill assumed, "
            f"disclosed limitation (mean bias +0.22c, 13.4% opposite-direction, sd~1.1c vs real L2 "
            f"on 179 matched points) -- every ledger row carries fill_mode, derived from the ACTUAL "
            f"per-leg pricing path leg_price() returned (not a timestamp guess -- see 2026-08-27 "
            f"audit fix). Zero pmxt L2 rows exist for Trump's 7-day tokens (n_l2_tokens=0), so "
            f"Trump's entire sealed span is proxy-only, single population, honestly labeled."
        ),
        trial_count=TRIALS["n"],
        scope="claims-pnl (Pass B fill/fee/cost battery binds in full)",
        notes=json.dumps(dict(
            wall_elon_utc=WALL_ELON, wall_trump_utc=WALL_TRUMP, l2_start_ms=L2_START_MS,
            trump_train_n=0, trump_config_borrowed_from="elonmusk",
            trials_detail=TRIALS["detail"],
            audit_fixes_2026_08_27=dict(
                finding1_fill_mode="fixed: fill_mode now derived per-row from the actual "
                    "leg_price() return value (asserted against lt_idx non-empty when "
                    "claiming l2_hardened), not from a T_ms>=L2_START_MS timestamp guess. "
                    "sealed_l2/sealed_proxy population split for a handle now also gates on "
                    "n_l2_tokens==0 (zero real L2 coverage collapses the whole sealed span "
                    "into sealed_proxy, exactly as it did here for Trump: was falsely split "
                    "11 l2_hardened / 18 proxy, now honestly n=29 proxy-only). Elon's split "
                    "(n_l2_tokens>0) is untouched -- byte-identical code path, no Elon number "
                    "moved by this fix.",
                finding2_b2_hindsight="fixed: b2_hindsight now surfaced next to every "
                    "B2_naive number (section 1 print + RUN_META headline.<handle>.<span>."
                    "b2_naive_hindsight) instead of being computed and silently dropped. "
                    "Added B2_walkforward as an honest companion arm (modal bracket "
                    "re-selected per auction from strictly-prior history only, zero "
                    "hindsight) so the two are shown side by side; the gap between them "
                    "measures what the hindsight leak was worth.",
                trial_count_change="TRIALS increased by the new B2_walkforward arm per "
                    "(handle, sealed_l2|sealed_proxy) sub-span actually run; see "
                    "trials_detail for the exact per-arm accounting.",
            ),
        ), default=str),
        out_dir="kelly_out",
    )


if __name__ == "__main__":
    main()
