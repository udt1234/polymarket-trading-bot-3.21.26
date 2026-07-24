from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# MARKET MAKER (paper test, 2026-07-24). True two-sided market making: rest a BID
# below mid and, when holding inventory, an ASK above cost - capture the spread and
# earn reward-pool income. Runs across a configurable UNIVERSE of markets we have
# live L2 for. This is DISTINCT from lp_rewards (which only farmed the reward pool,
# no spread capture) and from the arb modules (locked-below-$1, not spread-capture).
#
# HONEST THESIS STATUS: on Elon the book is ~1c wide (efficient) so spread capture is
# thin there; the real shot is WEATHER (wider spreads + $100/day reward pools) and
# other less-efficient tweet markets (White House, 11-23c spreads). We run all three
# to MEASURE where MM actually pays. Adverse selection is the #1 risk (we get filled
# exactly when the market runs through us) - inventory skew + a tight max cap defend it.
DEFAULT_CONFIG: dict = {
    # which market families to make on. "tweets" = every tag-972 tweet market we have
    # L2 for (elon, white-house, khamenei, cz, zelenskyy, cruz, nyc-mayor, trump-truth).
    "markets": ["tweets", "weather"],
    # optional slug allowlist to narrow "tweets" (empty = all we have L2 for)
    "tweet_slug_allow": [],
    "half_spread_cents": 2.0,        # quote this many cents either side of mid
    "skew_cents": 3.0,               # push both quotes down this many cents at full inventory
    "max_inventory_usd": 40.0,       # per-token inventory cap (adverse-selection bound)
    "min_markup_cents": 1.0,         # never offer inventory below cost + this
    "quote_size_usd": 20.0,          # notional per resting quote
    "min_price": 0.05,
    "max_price": 0.95,
    "max_tokens": 40,                # cap concurrent tokens quoted (breadth control)
    "weather_min_daily_rate": 50.0,  # only weather markets with a real reward pool
    "min_notional": 1.0,
    # MM edge is spread capture + rewards, not a directional fair-value gap
    "gate_min_edge": 0.0,
    "gate_spread_tol": 0.40,
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
