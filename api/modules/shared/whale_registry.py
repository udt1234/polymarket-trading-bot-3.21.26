"""Whale registry - the wallets we track, tagged by strategy archetype.

Goal (Sir, 2026-07-24): watch provably-profitable wallets and LEARN how they operate
where we can't, by logging their movements over time. We can see WHAT they do (markets,
prices, sizes, timing, order patterns) but not their private signal - so we classify by
BEHAVIOR into archetypes and let each strategy module reference the relevant ones.

Archetypes:
  market_maker  - rests on both sides of many markets, high order count, thin margins
  lp_reward     - rests near mid on reward-eligible markets (farms the pool)
  arbitrage     - buys complete sets / complement pairs (locked-below-$1)
  tweet         - trades tweet-count markets (elon/wh/etc.)
  other         - profitable but doesn't fit the above (directional, sports, politics)

Stored in the settings table under key `whale_registry` = {wallet: {archetype, label,
source, added}} so there is no schema migration to add/remove a whale.
"""
import logging
from datetime import datetime, timezone

from api.dependencies import get_supabase

log = logging.getLogger(__name__)

KEY = "whale_registry"
ARCHETYPES = ("market_maker", "lp_reward", "arbitrage", "tweet", "other")


def load() -> dict:
    try:
        res = get_supabase().table("settings").select("value").eq("key", KEY).limit(1).execute()
        return (res.data[0]["value"] or {}) if res.data else {}
    except Exception:
        log.exception("whale_registry load failed")
        return {}


def save(reg: dict) -> None:
    get_supabase().table("settings").upsert({"key": KEY, "value": reg}).execute()


def add(wallet: str, archetype: str, label: str = "", source: str = "manual") -> dict:
    wallet = wallet.lower()
    reg = load()
    reg[wallet] = {"archetype": archetype, "label": label, "source": source,
                   "added": datetime.now(timezone.utc).isoformat()}
    save(reg)
    return reg


def by_archetype(archetype: str) -> list[str]:
    return [w for w, v in load().items() if v.get("archetype") == archetype]
