from api.modules.shared.config_store import get_module_config as _get
from api.modules.shared.config_store import save_module_config as _save

# LP-reward farming: rest post-only bids INSIDE the reward band of mid on
# reward-eligible markets to earn Polymarket liquidity rewards - income that does
# NOT need us to out-predict anyone (the one mechanism our ~10 edge-tests didn't
# kill). MAKER-ONLY. Reward params come from Gamma per market (rewardsMinSize,
# rewardsMaxSpread in cents, clobRewards[].rewardsDailyRate).
DEFAULT_CONFIG: dict = {
    "max_markets": 5,              # cap concurrent reward markets
    "max_per_token_usd": 60.0,     # skip a market if meeting its min_size costs more
    "min_daily_rate": 1.0,         # skip markets with a tiny/zero reward pool
    "max_min_size": 500,           # skip markets whose rewardsMinSize is too large
    "quote_frac_of_band": 0.5,     # rest this fraction of rewardsMaxSpread inside mid
    "min_price": 0.05,
    "max_price": 0.95,
    # risk-gate overrides (income strategy, not directional edge - see module.py)
    "gate_min_edge": 0.0,          # no directional-edge floor; reward is the income
    "gate_spread_tol": 0.30,       # reward markets are wide; we're paid to quote them
}


def get_module_config(module_id: str) -> dict:
    return _get(module_id, DEFAULT_CONFIG)


def save_module_config(module_id: str, patch: dict) -> dict:
    return _save(module_id, patch, DEFAULT_CONFIG)
