# -*- coding: utf-8 -*-
"""Shared utilities for pattern_discovery_2026-07-26.py.

Data loading (canonical only), noon-ET slug parsing (bracket_hit_backtest.py::noon()
pattern, generalized to cover both Elon and Trump slug vocabularies), bracket-range
parsing, and generic probability-distribution helpers (Normal / empirical-mixture /
discrete-PMF -> bracket probabilities) reused by every baseline and method so the
math is written once and audited once.

THE WALL: every function here is a pure transform of data already selected by the
caller as ts <= T. This file does not itself enforce the wall -- the caller
(pattern_discovery_2026-07-26.py) must only ever pass causal slices in.
"""
from __future__ import annotations

import bisect
import glob
import json
import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.special import erf

ROOT = Path(r"C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot")
CANON = ROOT / "_DataMetricPulls" / "canonical"
PB = ROOT / "_DataMetricPulls" / "pacing_backtest"
ET = ZoneInfo("America/New_York")
SQRT2 = math.sqrt(2.0)

# ---------------------------------------------------------------------------
# 1. noon-ET slug parser (generalizes bracket_hit_backtest.py::noon())
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


def _strip_prefix(slug: str, handle: str):
    if handle == "elonmusk":
        if slug.startswith(ELON_PREFIX):
            return slug[len(ELON_PREFIX):]
        return None
    for p in TRUMP_PREFIXES:
        if slug.startswith(p):
            return slug[len(p):]
    return None


def _try_parse_tokens(tk, yr):
    mo1 = MONTHS[tk[0].lower()]
    d1 = int(tk[1])
    rest = tk[2:]
    if len(rest) == 1:
        mo2, d2 = mo1, int(rest[0])
    elif len(rest) == 2 and rest[0].lower() in MONTHS:
        mo2, d2 = MONTHS[rest[0].lower()], int(rest[1])
    else:
        raise ValueError("unrecognized token shape")
    y2 = yr + (1 if mo2 < mo1 else 0)
    s = pd.Timestamp(datetime(yr, mo1, d1, 12, tzinfo=ET))
    e = pd.Timestamp(datetime(y2, mo2, d2, 12, tzinfo=ET))
    return int(s.timestamp()), int(e.timestamp())


def noon_window(slug: str, handle: str, yr: int):
    """Parse noon-ET [start,end) unix seconds from a market slug. NEVER from
    trade-derived start_utc/end_utc (those are ~2x wrong) -- yr is taken from
    start_utc.year only as a YEAR anchor (month/day come from the slug itself),
    the same pattern bracket_hit_backtest.py / odds_vs_market.py use."""
    if EXCLUDE_SLUG.search(slug):
        return None
    body = _strip_prefix(slug, handle)
    if body is None:
        return None
    tk = body.split("-")
    try:
        return _try_parse_tokens(tk, yr)
    except Exception:
        pass
    # some slugs carry a trailing disambiguating numeric id, e.g. "...-april-11-18-628"
    if tk and tk[-1].isdigit() and len(tk[-1]) >= 2:
        try:
            return _try_parse_tokens(tk[:-1], yr)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# 2. bracket-range parsing
# ---------------------------------------------------------------------------
def parse_bucket_range(label: str):
    """'<40'->(0,39); '140+'->(140,None); '40-64'->(40,64); '115'->(115,115)."""
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


def normalize_bucket(s: str) -> str:
    return str(s).replace("\u2013", "-").replace("\u2014", "-").strip()


# ---------------------------------------------------------------------------
# 3. causal feature primitives on a sorted post-timestamp array (unix seconds)
# ---------------------------------------------------------------------------
def obs_count(post_ts: np.ndarray, a: int, b: int) -> int:
    """# of counted posts in [a,b). post_ts must be sorted. THE WALL: caller
    must ensure b <= decision time T when used as a feature (not scoring)."""
    return int(np.searchsorted(post_ts, b) - np.searchsorted(post_ts, a))


def gap_features(post_ts: np.ndarray, s: int, T: int) -> dict:
    """Median/longest/variance of inter-arrival gaps, time-of-first-post,
    max-in-60min, posts-in-1h/3h/6h -- all computed on posts strictly in [s,T)."""
    lo = bisect.bisect_left(post_ts, s)
    hi = bisect.bisect_left(post_ts, T)
    seg = post_ts[lo:hi]
    out = {
        "median_gap_s": np.nan, "longest_gap_s": np.nan, "gap_var_s2": np.nan,
        "first_post_hours": np.nan, "max_posts_60min": 0.0,
        "posts_last_1h": 0.0, "posts_last_3h": 0.0, "posts_last_6h": 0.0,
    }
    if len(seg) >= 1:
        out["first_post_hours"] = (int(seg[0]) - s) / 3600.0
        out["posts_last_1h"] = float(obs_count(post_ts, max(s, T - 3600), T))
        out["posts_last_3h"] = float(obs_count(post_ts, max(s, T - 3 * 3600), T))
        out["posts_last_6h"] = float(obs_count(post_ts, max(s, T - 6 * 3600), T))
    if len(seg) >= 2:
        gaps = np.diff(seg.astype("int64"))
        out["median_gap_s"] = float(np.median(gaps))
        out["longest_gap_s"] = float(np.max(gaps))
        out["gap_var_s2"] = float(np.var(gaps))
    if len(seg) >= 1:
        # sliding 60-min count, stepped every 15 min for tractability
        best = 0
        t = seg[0]
        while t <= T - 1:
            c = obs_count(post_ts, int(t), int(t) + 3600)
            if c > best:
                best = c
            t += 900
        out["max_posts_60min"] = float(best)
    return out


def et_hour_dow(ts_unix: int):
    dt = pd.Timestamp(ts_unix, unit="s", tz="UTC").tz_convert(ET)
    return int(dt.hour), int(dt.dayofweek)


# ---------------------------------------------------------------------------
# 4. distribution helpers -> bracket probabilities
# ---------------------------------------------------------------------------
def _ncdf(z):
    return 0.5 * (1.0 + math.erf(z / SQRT2))


def normal_bracket_probs(mu: float, sigma: float, brackets):
    sigma = max(sigma, 1.0)
    out = {}
    for label, lo, hi in brackets:
        zl = (lo - 0.5 - mu) / sigma
        p = (1.0 - _ncdf(zl)) if hi is None else (_ncdf((hi + 0.5 - mu) / sigma) - _ncdf(zl))
        out[label] = max(1e-6, p)
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()}


def gaussian_mixture_bracket_probs(centers: np.ndarray, weights: np.ndarray,
                                    bandwidth: float, brackets):
    """Mixture-of-Gaussians CDF evaluated on bracket edges. `centers` are
    scalar values (e.g. historical final counts), `weights` sum to any
    positive total (renormalized here). This is the nonparametric building
    block for M1 (empirical table+shrinkage), M2 (within-bin density), M3
    (cluster-conditional), M5/M6 (Monte-Carlo/simulation empirical outputs),
    and B2 (climatology)."""
    centers = np.asarray(centers, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if len(centers) == 0 or weights.sum() <= 0:
        return None
    weights = weights / weights.sum()
    h = max(bandwidth, 0.75)
    out = {}
    for label, lo, hi in brackets:
        zl = (lo - 0.5 - centers) / h
        if hi is None:
            p = 1.0 - _ncdf_vec(zl)
        else:
            zh = (hi + 0.5 - centers) / h
            p = _ncdf_vec(zh) - _ncdf_vec(zl)
        out[label] = max(1e-6, float(np.sum(weights * p)))
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()}


def _ncdf_vec(z):
    return 0.5 * (1.0 + erf(np.asarray(z) / SQRT2))


def discrete_pmf_bracket_probs(offset: int, pmf: np.ndarray, brackets):
    """pmf[i] = P(value == offset+i). Sums the pmf mass landing inside each
    bracket's [lo,hi] integer range. Used by M4 (HMM Poisson mixture) and M7
    (daily-distribution convolution), which are inherently discrete-count
    processes rather than continuous kernels."""
    n = len(pmf)
    out = {}
    for label, lo, hi in brackets:
        i0 = max(0, lo - offset)
        i1 = (n - 1) if hi is None else min(n - 1, hi - offset)
        if i1 < i0:
            out[label] = 1e-6
        else:
            out[label] = max(1e-6, float(pmf[i0:i1 + 1].sum()))
    tot = sum(out.values())
    return {k: v / tot for k, v in out.items()}


def empty_uniform_probs(brackets):
    n = len(brackets)
    return {label: 1.0 / n for label, _, _ in brackets}


# ---------------------------------------------------------------------------
# 5. scoring
# ---------------------------------------------------------------------------
def log_loss_1(probs: dict, winner: str) -> float:
    return -math.log(max(probs.get(winner, 1e-9), 1e-9))


def brier_1(probs: dict, winner: str, brackets) -> float:
    return sum((probs.get(label, 0.0) - (1.0 if label == winner else 0.0)) ** 2
               for label, _, _ in brackets)


# ---------------------------------------------------------------------------
# 6. data loaders (canonical only)
# ---------------------------------------------------------------------------
def load_elon_posts():
    """Returns sorted post_ts (unix s, int64) + is_qr (bool, quote|repost) aligned
    array, filtered counts_main_feed == True. Source: elon_backfill_2025-09_to_now.parquet
    (the declared clean X-API span, Sep 2025 -> Jun 29 2026, covers every auction/day
    used by this study -- the ext file was checked and is not needed, see run notes)."""
    bf = pd.read_parquet(PB / "elon_backfill_2025-09_to_now.parquet")
    bf = bf[bf.counts_main_feed].sort_values("ms")
    post_ts = (bf["ms"].to_numpy() // 1000).astype("int64")
    is_qr = bf["type"].isin(["quote", "repost"]).to_numpy()
    return post_ts, is_qr


def load_trump_posts():
    files = sorted((CANON / "posts" / "realDonaldTrump").glob("*.parquet"))
    tp = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    tp = tp[tp.counts_for_auction].sort_values("ts_utc")
    post_ts = (tp["ts_utc"].astype("int64") // 10**9).to_numpy().astype("int64")
    is_qr = (tp["is_repost"] | tp["is_quote"]).to_numpy()
    return post_ts, is_qr


def load_auctions(handle: str, resolved_only=("resolved_yes", "resolved_yes_gamma")):
    files = sorted((CANON / "auctions" / handle).glob("*.parquet"))
    auc = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    auc = auc[(auc.confidence == "high") & (auc.resolution_status.isin(resolved_only))
              & (auc.duration_type.isin(["2-day", "7-day"]))]
    auc = auc[~auc.auction_slug.str.contains(EXCLUDE_SLUG)]
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
        rows.append(dict(slug=r.auction_slug, handle=handle, s=s, e=e,
                          dur=r.duration_type, winner=winner, brackets=brackets))
    rows.sort(key=lambda x: x["s"])
    return rows


def load_prices(handle: str):
    """dict[(slug,bucket)] -> (times int64[] hour_utc unix-s sorted, close float[])."""
    files = sorted((CANON / "prices" / handle).glob("*.parquet"))
    prc = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    prc["bucket"] = prc["bucket"].apply(normalize_bucket)
    idx = {}
    for (slug, bucket), g in prc.sort_values("hour_utc").groupby(["auction_slug", "bucket"]):
        t = (g["hour_utc"].astype("int64") // 10**9).to_numpy().astype("int64")
        c = g["close"].to_numpy(dtype=float)
        idx[(slug, bucket)] = (t, c)
    return idx


def price_at(price_idx: dict, slug: str, bucket: str, T: int):
    a = price_idx.get((slug, bucket))
    if a is None:
        return None
    ts, closes = a
    i = np.searchsorted(ts, T, side="right") - 1
    if i < 0:
        return None
    v = float(closes[i])
    return v if 0.0 <= v <= 1.0 else None


def market_bracket_probs(price_idx: dict, slug: str, brackets, T: int):
    """Causal market-implied distribution at T, normalized across brackets that
    HAVE a price at/ before T. Returns (probs_or_None, n_covered, n_total).
    If ANY bracket lacks a price, that bracket's true market view is unknown --
    we do NOT invent a price for it; the caller decides whether the auction is
    admissible for a B4 comparison based on winner coverage specifically."""
    vals = {}
    for label, _, _ in brackets:
        v = price_at(price_idx, slug, label, T)
        if v is not None:
            vals[label] = max(v, 1e-6)
    if not vals:
        return None, 0, len(brackets)
    tot = sum(vals.values())
    probs = {k: v / tot for k, v in vals.items()}
    return probs, len(vals), len(brackets)
