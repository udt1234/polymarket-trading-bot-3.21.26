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
    single-profile auction_type so the module can iterate uniformly."""
    if "auction_types" in stored and stored["auction_types"]:
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


def _validate_auction_types(at_list) -> list:
    """Sanity-check the auction_types structure. Drops malformed entries."""
    if not isinstance(at_list, list):
        return []
    cleaned = []
    for at in at_list:
        if not isinstance(at, dict):
            continue
        profiles = []
        for p in at.get("bracket_profiles", []) or []:
            if not isinstance(p, dict):
                continue
            profiles.append({
                "bracket": str(p.get("bracket", "")),
                "label": str(p.get("label", "")),
                "enabled": bool(p.get("enabled", False)),
                "strategy_name": str(p.get("strategy_name", "Cheap_Lottery_Pacing")),
                "bracket_max_count": int(p.get("bracket_max_count", 40)),
                "params": p.get("params", {}) if isinstance(p.get("params"), dict) else {},
            })
        cleaned.append({
            "id": str(at.get("id", "")),
            "label": str(at.get("label", "")),
            "enabled": bool(at.get("enabled", False)),
            "handle": str(at.get("handle", "")),
            "platform": str(at.get("platform", "")),
            "series_slug": str(at.get("series_slug", "")),
            "window_days": int(at.get("window_days", 2)),
            "bracket_profiles": profiles,
        })
    return cleaned


def _validate_against_schema(config: dict) -> dict:
    from api.modules.spike_trading.module import SpikeTradingModule
    schema = {f["key"]: f for f in SpikeTradingModule().get_config_schema()}
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
