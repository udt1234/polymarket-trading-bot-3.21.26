"""Spike Trading module config — multi-auction-type, multi-profile.

Architecture:
  cfg["auction_types"] = list of auction-type objects, each with:
    - id, label, enabled flag, discovery params (handle/platform/series/window_days)
    - bracket_profiles: list of profile objects, each with:
        - bracket, enabled flag, strategy_name, label, params dict (overrides
          the strategy's DEFAULT_PARAMS for this profile)

Legacy keys (handle, bracket_pattern, buy_ladder, etc. at top level) remain
in DEFAULT_CONFIG for backwards compat. get_module_config() auto-migrates
old single-bracket configs by wrapping them into a single auction_type with
one bracket_profile when no `auction_types` list is present.

Strategy plugins live in `strategies/`. Adding a new strategy = drop a file
that subclasses Strategy. Profiles reference strategies by `name`.
"""
from api.dependencies import get_supabase

# ---------------------------------------------------------------------------
# DEFAULT_CONFIG: out-of-the-box behavior is identical to the pre-refactor
# single-bracket Spike Trading. The new auction_types list ships with one
# auction type (Elon 2-day) and one enabled profile (<40 with the
# Cheap_Lottery_Pacing strategy). Add more by editing this dict OR (better)
# editing live config from the dashboard.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    # ===== NEW: nested auction_types schema =====
    "auction_types": [
        {
            "id": "elon-2day",
            "label": "Elon 2-Day",
            "enabled": True,
            "handle": "elonmusk",
            "platform": "x",
            "series_slug": "elon-tweets-48h",
            "window_days": 2,
            "bracket_profiles": [
                {
                    "bracket": "<40",
                    "label": "Elon_2Day_<40",
                    "enabled": True,
                    "strategy_name": "Cheap_Lottery_Pacing",
                    "bracket_max_count": 40,
                    "params": {
                        # Inherits Cheap_Lottery_Pacing.DEFAULT_PARAMS
                        # Override individual keys here to customize this profile.
                    },
                },
                {
                    "bracket": "65-89",
                    "label": "Elon_2Day_65-89",
                    "enabled": False,  # off until you turn it on
                    "strategy_name": "Mid_Range_Spike",
                    "bracket_max_count": 89,
                    "params": {},
                },
                {
                    "bracket": "90-114",
                    "label": "Elon_2Day_90-114",
                    "enabled": False,
                    "strategy_name": "Mid_Range_Spike",
                    "bracket_max_count": 114,
                    "params": {},
                },
                {
                    "bracket": "40-64",
                    "label": "Elon_2Day_40-64",
                    "enabled": False,
                    "strategy_name": "Mid_Range_Spike",
                    "bracket_max_count": 64,
                    "params": {},
                },
            ],
        },
        {
            "id": "elon-monthly",
            "label": "Elon Monthly",
            "enabled": False,  # off — turn on after manual review
            "handle": "elonmusk",
            "platform": "x",
            "series_slug": "elon-tweets-monthly",  # update if Polymarket uses different slug
            "window_days": 30,
            "bracket_profiles": [
                {
                    "bracket": "1400+",
                    "label": "Elon_Monthly_1400+",
                    "enabled": False,
                    "strategy_name": "Big_Hold_Monthly",
                    "bracket_max_count": 1400,
                    "params": {},
                },
            ],
        },
        # Trump 7-day intentionally NOT included — the existing truth_social
        # ensemble module owns that. Per user 2026-05-06: do not touch ensemble.
    ],

    # ===== Module-wide knobs (apply across all auction types) =====
    "bracket_cap_pct_of_bankroll": 0.05,
    "max_open_positions": 3,
    "min_market_volume_24h": 0,
    "log_decisions_to_supabase": True,

    # ===== Legacy single-bracket keys (kept for backwards compat) =====
    # If a stored config lacks `auction_types`, get_module_config() wraps these
    # into a single-profile auction_type at read time. New code should always
    # consume `auction_types` instead.
    "platform": "x",
    "handle": "elonmusk",
    "window_days": 2,
    "bracket_pattern": "<40",
    "series_slug": "elon-tweets-48h",
    "buy_ladder": [
        {"price": 0.003, "pct": 0.30, "label": "lottery"},
        {"price": 0.005, "pct": 0.30, "label": "scoop"},
        {"price": 0.020, "pct": 0.20, "label": "value"},
        {"price": 0.050, "pct": 0.10, "label": "mid"},
        {"price": 0.120, "pct": 0.10, "label": "catchall"},
    ],
    "buy_tier_1_price": 0.003,
    "buy_tier_1_pct":   0.30,
    "buy_tier_2_price": 0.005,
    "buy_tier_2_pct":   0.30,
    "buy_cancel_after_hours": 24,
    "sell_multipliers": [1.5, 2.0, 4.0, 8.0],
    "sell_multiplier_pcts": [0.30, 0.30, 0.20, 0.20],
    "take_profit_pct": 7.0,
    "stop_loss_pct": 0.85,
    "trailing_stop_pct": 0.30,
    "hold_max_tweets": 5,
    "hold_min_hours_remaining": 24,
    "sellnow_grid": [[16, 24], [20, 18], [30, 0]],
    "bracket_max_count": 40,
    "pacing_sell_score": 1.20,
    "pacing_hold_score": 0.30,
}


def _migrate_legacy_to_auction_types(stored: dict) -> dict:
    """If stored config lacks `auction_types`, wrap legacy keys into a
    single-profile auction_type so the module can iterate uniformly.

    NOTE: an explicit empty `auction_types: []` is RESPECTED — that means the
    user intentionally cleared the list (module idle). Only legacy configs
    where the key is entirely absent get migrated."""
    if "auction_types" in stored:
        return stored
    legacy_profile = {
        "bracket": stored.get("bracket_pattern", "<40"),
        "label": f"{stored.get('handle', 'elonmusk')}_{stored.get('window_days', 2)}D_{stored.get('bracket_pattern', '<40')}",
        "enabled": True,
        "strategy_name": "Cheap_Lottery_Pacing",
        "bracket_max_count": int(stored.get("bracket_max_count", 40)),
        "params": {
            k: stored[k] for k in (
                "buy_ladder", "buy_cancel_after_hours",
                "sell_multipliers", "sell_multiplier_pcts",
                "take_profit_pct", "stop_loss_pct", "trailing_stop_pct",
                "hold_max_tweets", "hold_min_hours_remaining",
                "sellnow_grid", "pacing_sell_score", "pacing_hold_score",
            ) if k in stored
        },
    }
    legacy_auction = {
        "id": "elon-2day-legacy",
        "label": "Elon 2-Day (legacy)",
        "enabled": True,
        "handle": stored.get("handle", "elonmusk"),
        "platform": stored.get("platform", "x"),
        "series_slug": stored.get("series_slug", "elon-tweets-48h"),
        "window_days": stored.get("window_days", 2),
        "bracket_profiles": [legacy_profile],
    }
    out = dict(stored)
    out["auction_types"] = [legacy_auction]
    return out


def get_module_config(module_id: str) -> dict:
    sb = get_supabase()
    key = f"module_config:{module_id}"
    res = sb.table("settings").select("*").eq("key", key).execute()
    if res.data:
        stored = res.data[0].get("value", {}) or {}
        merged = {**DEFAULT_CONFIG, **stored}
        # Auto-migrate legacy configs (no auction_types list saved yet).
        return _migrate_legacy_to_auction_types(merged)
    return dict(DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Validation: bounds-clamp incoming dashboard payloads. Schema-driven for
# leaf number/boolean fields; structural fields (auction_types) pass through
# but are sanity-checked.
# ---------------------------------------------------------------------------
def _ladder_pairs_to_dicts(pairs):
    out = []
    for row in pairs or []:
        if isinstance(row, dict):
            out.append({
                "price": float(row.get("price", 0)),
                "pct": float(row.get("pct", 0)),
                "label": str(row.get("label", "")),
            })
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append({"price": float(row[0]), "pct": float(row[1])})
    return out


import math
import re

# Defense-in-depth bounds on per-profile params. The dashboard clamps inputs,
# but a buggy/malicious client could POST arbitrary JSON. These caps make
# sure that no value can cause: (a) >100% bankroll deployment, (b) infinite
# loops, (c) NaN propagation through the pacing classifier.
_PARAM_BOUNDS = {
    # ladder pricing
    "buy_tier_1_price": (0.0, 1.0),
    "buy_tier_2_price": (0.0, 1.0),
    # generic per-tier caps applied inside lists below too
    # exit thresholds
    "take_profit_pct": (0.0, 100.0),     # multiples of entry
    "stop_loss_pct": (0.0, 1.0),         # fraction of entry
    "trailing_stop_pct": (0.0, 1.0),
    # pacing
    "pacing_sell_score": (0.0, 10.0),
    "pacing_hold_score": (0.0, 10.0),
    "pacing_eligible_after_pct": (0.0, 1.0),
    # timing
    "buy_cancel_after_hours": (0.0, 168.0 * 4),
    "enter_after_hours_elapsed": (0.0, 168.0 * 4),
    "hold_max_tweets": (0, 10000),
    "hold_min_hours_remaining": (0.0, 168.0 * 4),
}

# Valid charset for free-text fields stored in config and later passed into
# HTTP calls / log lines. Conservative: alnum + a few separators.
_SAFE_STR = re.compile(r"^[A-Za-z0-9_./<>+:\- ]{0,128}$")
# Stricter charset for handles (passed straight into URLs as path components)
# — no dots, slashes, or anything that could traverse a path.
_SAFE_HANDLE = re.compile(r"^[A-Za-z0-9_-]{0,64}$")
_MAX_LADDER_TIERS = 10
_MAX_PROFILES_PER_AUCTION = 30
_MAX_AUCTION_TYPES = 20


def _safe_str(v, fallback: str = "", max_len: int = 64) -> str:
    if v is None:
        return fallback
    s = str(v)[:max_len]
    if not _SAFE_STR.fullmatch(s):
        # Strip unsafe chars rather than rejecting outright (UX > strictness)
        s = re.sub(r"[^A-Za-z0-9_./<>+:\- ]", "", s)[:max_len]
    return s or fallback


def _safe_handle(v, fallback: str = "elonmusk") -> str:
    """Stricter than _safe_str — for handle/platform values that get
    interpolated into URL path components. No dots/slashes/control chars."""
    if v is None:
        return fallback
    s = str(v)[:64]
    if not _SAFE_HANDLE.fullmatch(s):
        s = re.sub(r"[^A-Za-z0-9_-]", "", s)[:64]
    return s or fallback


def _safe_finite_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        if not math.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_finite_int(v, default: int = 0) -> int:
    try:
        n = int(v)
        return n
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _validate_ladder(raw, max_tiers: int = _MAX_LADDER_TIERS) -> list:
    """Validate a buy ladder (list of {price, pct, label} dicts).
    Each price clamped [0, 1]; each pct clamped [0, 1]; sum-of-pct clamped to 1.0
    (extras silently scaled down so total allocation never exceeds 100%).
    """
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw[:max_tiers]:
        if isinstance(row, dict):
            price = _clamp(_safe_finite_float(row.get("price"), 0), 0.0, 1.0)
            pct = _clamp(_safe_finite_float(row.get("pct"), 0), 0.0, 1.0)
            label = _safe_str(row.get("label"), "tier", max_len=32)
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            price = _clamp(_safe_finite_float(row[0], 0), 0.0, 1.0)
            pct = _clamp(_safe_finite_float(row[1], 0), 0.0, 1.0)
            label = "tier"
        else:
            continue
        if price <= 0 or pct <= 0:
            continue
        out.append({"price": price, "pct": pct, "label": label})
    # If sum of pct > 1.0, scale down proportionally
    total = sum(t["pct"] for t in out)
    if total > 1.0:
        for t in out:
            t["pct"] = t["pct"] / total
    return out


def _validate_params(raw: dict) -> dict:
    """Apply numeric bounds + finite-checks to a profile.params dict.
    Unknown keys are dropped (NOT passed through) — preventing a malicious
    payload from injecting arbitrary keys that downstream strategy code
    might trust."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    # Valid param key charset: alnum + underscore. Anything else dropped to
    # prevent control chars / log-injection / weird strategy lookups.
    _key_re = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
    for k, v in raw.items():
        if not isinstance(k, str) or not _key_re.fullmatch(k):
            continue
        # Special-case structured fields
        if k == "buy_ladder":
            out[k] = _validate_ladder(v)
            continue
        if k == "sell_targets":
            # list of {price, pct} dicts
            cleaned = []
            if isinstance(v, list):
                for row in v[:_MAX_LADDER_TIERS]:
                    if not isinstance(row, dict):
                        continue
                    price = _clamp(_safe_finite_float(row.get("price"), 0), 0.0, 1.0)
                    pct = _clamp(_safe_finite_float(row.get("pct"), 0), 0.0, 1.0)
                    if price > 0 and pct > 0:
                        cleaned.append({"price": price, "pct": pct})
                # Scale pct sum down to ≤1.0
                total = sum(t["pct"] for t in cleaned)
                if total > 1.0:
                    for t in cleaned:
                        t["pct"] = t["pct"] / total
            out[k] = cleaned
            continue
        if k == "sell_multipliers":
            if isinstance(v, list):
                out[k] = [_clamp(_safe_finite_float(x, 0), 0.0, 1000.0) for x in v[:_MAX_LADDER_TIERS]]
            continue
        if k == "sell_multiplier_pcts":
            if isinstance(v, list):
                cleaned = [_clamp(_safe_finite_float(x, 0), 0.0, 1.0) for x in v[:_MAX_LADDER_TIERS]]
                total = sum(cleaned)
                if total > 1.0:
                    cleaned = [x / total for x in cleaned]
                out[k] = cleaned
            continue
        if k == "sellnow_grid":
            if isinstance(v, list):
                cleaned = []
                for row in v[:20]:
                    if isinstance(row, (list, tuple)) and len(row) >= 2:
                        cleaned.append([
                            _clamp(_safe_finite_float(row[0], 0), 0.0, 1e6),
                            _clamp(_safe_finite_float(row[1], 0), 0.0, 1e6),
                        ])
                out[k] = cleaned
            continue
        # Bounded scalar params
        if k in _PARAM_BOUNDS:
            lo, hi = _PARAM_BOUNDS[k]
            out[k] = _clamp(_safe_finite_float(v, lo), lo, hi)
            continue
        # Unknown leaf key — coerce to safe primitive types only
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = _safe_finite_float(v, 0)
        elif isinstance(v, str):
            out[k] = _safe_str(v, "", max_len=128)
        # Other types (lists/dicts of unknown shape) are dropped silently
    return out


def _validate_auction_types(at_list) -> list:
    """Sanity-check the auction_types structure with bounds + length caps."""
    if not isinstance(at_list, list):
        return []
    cleaned = []
    seen_ids: set[str] = set()
    for at in at_list[:_MAX_AUCTION_TYPES]:
        if not isinstance(at, dict):
            continue
        at_id = _safe_str(at.get("id"), "auction", max_len=48)
        # Enforce id uniqueness — silently drop duplicates so React keys stay
        # stable and downstream lookups don't collide.
        if at_id in seen_ids:
            continue
        seen_ids.add(at_id)
        profiles = []
        seen_profile_keys: set[tuple] = set()
        for p in (at.get("bracket_profiles") or [])[:_MAX_PROFILES_PER_AUCTION]:
            if not isinstance(p, dict):
                continue
            bracket = _safe_str(p.get("bracket"), "", max_len=32)
            if not bracket:
                continue
            # Profile uniqueness key: (bracket, label) — duplicates dropped
            key = (bracket, _safe_str(p.get("label"), "", max_len=64))
            if key in seen_profile_keys:
                continue
            seen_profile_keys.add(key)
            profiles.append({
                "bracket": bracket,
                "label": _safe_str(p.get("label"), bracket, max_len=64),
                "enabled": bool(p.get("enabled", False)),
                "strategy_name": _safe_str(p.get("strategy_name"), "Cheap_Lottery_Pacing", max_len=64),
                "bracket_max_count": max(_safe_finite_int(p.get("bracket_max_count"), 40), 0),
                "params": _validate_params(p.get("params") or {}),
            })
        cleaned.append({
            "id": at_id,
            "label": _safe_str(at.get("label"), at_id, max_len=64),
            "enabled": bool(at.get("enabled", False)),
            "handle": _safe_handle(at.get("handle"), "elonmusk"),
            "platform": _safe_handle(at.get("platform"), "x"),
            "series_slug": _safe_str(at.get("series_slug"), "", max_len=128),
            "window_days": max(_safe_finite_int(at.get("window_days"), 2), 1),
            "bracket_profiles": profiles,
        })
    return cleaned


# Module-wide schema for the schema-driven form. Defined here (not imported
# from module.py) to avoid the module_config <-> module circular dependency
# QA-flagged in the 2026-05-06 review. SpikeTradingModule.get_config_schema()
# returns this same list.
MODULE_WIDE_SCHEMA = [
    {"key": "min_market_volume_24h", "type": "number", "min": 0, "max": 1_000_000, "step": 100},
    {"key": "bracket_cap_pct_of_bankroll", "type": "number", "min": 0.01, "max": 0.5, "step": 0.01},
    {"key": "max_open_positions", "type": "number", "min": 1, "max": 20, "step": 1},
    {"key": "log_decisions_to_supabase", "type": "boolean"},
]


def _validate_against_schema(config: dict) -> dict:
    schema = {f["key"]: f for f in MODULE_WIDE_SCHEMA}
    out = {}
    for k, v in (config or {}).items():
        if k == "auction_types":
            out[k] = _validate_auction_types(v)
            continue
        spec = schema.get(k)
        if spec is None:
            out[k] = v
            continue
        t = spec.get("type")
        try:
            if t == "number":
                v = float(v)
                if "min" in spec: v = max(v, float(spec["min"]))
                if "max" in spec: v = min(v, float(spec["max"]))
            elif t == "boolean":
                v = bool(v)
            elif t == "string":
                v = str(v) if v is not None else ""
            elif t == "select":
                if "options" in spec and v not in spec["options"]:
                    continue
            elif t == "number_list_2":
                if k == "buy_ladder":
                    v = _ladder_pairs_to_dicts(v)
                elif isinstance(v, list):
                    if v and isinstance(v[0], (list, tuple)):
                        v = [[float(x) for x in row] for row in v]
                    else:
                        v = [float(x) for x in v]
        except (ValueError, TypeError):
            continue
        out[k] = v
    return out


def save_module_config(module_id: str, config: dict):
    validated = _validate_against_schema(config)
    sb = get_supabase()
    key = f"module_config:{module_id}"
    existing_row = sb.table("settings").select("value").eq("key", key).execute()
    stored = (existing_row.data[0].get("value") or {}) if existing_row.data else {}
    merged = {**DEFAULT_CONFIG, **stored, **validated}
    sb.table("settings").upsert({"key": key, "value": merged}).execute()
