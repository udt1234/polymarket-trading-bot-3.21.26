"""Live game-state feed (MLB StatsAPI, free, no key).

The sweep only knew the PRICE, which whipsaws and can't tell a scare that
fizzles from a real collapse. This gives the GROUND TRUTH - score, inning,
outs, and which bases are occupied - so we can:
  1. only sweep GENUINELY-decided games (safe lead + late), not just price>=0.97
  2. AVOID sweeping a "decided" favorite sitting in a high-LEVERAGE spot
     (Sir's example: up 3, bases loaded, slugger up - one swing ties it)
  3. later: buy price OVERREACTIONS when the true state says the game is still
     safe (the market panicked, the score didn't).

MLB only for now (StatsAPI is MLB). NBA/NHL/NFL would use ESPN's feed - same
shape, add later.
"""
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

STATS = "https://statsapi.mlb.com/api/v1"
STATS11 = "https://statsapi.mlb.com/api/v1.1"

# safe-lead thresholds: a lead of >= L in inning >= I is ~decided (ignoring the
# leverage override below). Conservative (favor NOT sweeping when unsure).
_SAFE = [(9, 2), (8, 4), (7, 5), (6, 7)]

_abbr_cache: dict[int, str] = {}
_name_abbr_cache: dict[str, str] = {}
_SLUG_RE = None


def _load_teams():
    global _abbr_cache, _name_abbr_cache
    if not _abbr_cache:
        try:
            teams = httpx.get(f"{STATS}/teams", params={"sportId": 1}, timeout=20).json()["teams"]
            _abbr_cache = {t["id"]: (t.get("abbreviation") or "").lower() for t in teams}
            for t in teams:
                ab = (t.get("abbreviation") or "").lower()
                for key in (t.get("name"), t.get("teamName"), t.get("clubName")):
                    if key:
                        _name_abbr_cache[key.lower()] = ab
        except Exception:
            log.exception("team fetch failed")


def _abbr() -> dict[int, str]:
    _load_teams()
    return _abbr_cache


def abbr_for_name(name: str) -> str | None:
    """Map an outcome team name ('New York Mets') to its abbr ('nym')."""
    _load_teams()
    n = (name or "").lower()
    if n in _name_abbr_cache:
        return _name_abbr_cache[n]
    # loose contains match (outcome may be 'New York Mets' vs teamName 'Mets')
    for full, ab in _name_abbr_cache.items():
        if full in n or n.endswith(full):
            return ab
    return None


def sweep_ok_by_state(slug: str, fav_outcome: str,
                      states: dict[tuple[str, str], dict] | None = None) -> tuple[bool, str]:
    """Given a Polymarket game slug (mlb-<away>-<home>-<date>) and the favorite's
    outcome name, return (ok_to_sweep, reason) using live game state. ok=True
    only when the game is SAFELY decided and NOT in a high-leverage danger spot.
    On any lookup failure returns (False, 'no_state') - caller decides fallback."""
    parts = slug.split("-")
    if len(parts) < 5:
        return False, "bad_slug"
    away, home = parts[1], parts[2]
    if states is None:
        states = mlb_live_states()
    st = states.get((away, home))
    if not st:
        return False, "no_state"
    if st["state"] == "Final":
        return False, "final"
    fav_ab = abbr_for_name(fav_outcome)
    if fav_ab not in (away, home):
        return False, "unmatched_team"
    detail = game_detail(st["pk"])
    a = assess(detail, leading_is_home=(fav_ab == home))
    return a["decided"], a["reason"]


def mlb_live_states() -> dict[tuple[str, str], dict]:
    """(away_abbr, home_abbr) -> live state for today's + yesterday's games."""
    out: dict[tuple[str, str], dict] = {}
    ab = _abbr()
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        sched = httpx.get(f"{STATS}/schedule", params={"sportId": 1, "date": today}, timeout=20).json()
    except Exception:
        log.exception("schedule fetch failed")
        return out
    for day in sched.get("dates", []):
        for g in day.get("games", []):
            a = ab.get(g["teams"]["away"]["team"]["id"])
            h = ab.get(g["teams"]["home"]["team"]["id"])
            state = (g.get("status", {}) or {}).get("abstractGameState", "")
            if not a or not h:
                continue
            out[(a, h)] = {"pk": g["gamePk"], "state": state,
                           "away_score": g["teams"]["away"].get("score"),
                           "home_score": g["teams"]["home"].get("score"),
                           "detail": None}
    return out


def game_detail(pk: int) -> dict | None:
    """Full live linescore for one game (inning/outs/bases/runs)."""
    try:
        ls = httpx.get(f"{STATS11}/game/{pk}/feed/live", timeout=25).json()["liveData"]["linescore"]
    except Exception:
        log.exception("live feed failed for %s", pk)
        return None
    off = ls.get("offense", {}) or {}
    runners = sum(1 for b in ("first", "second", "third") if off.get(b) is not None)
    t = ls.get("teams", {})
    return {"inning": ls.get("currentInning"),
            "half": (ls.get("inningState") or "").lower(),   # 'top'|'bottom'|'middle'|'end'
            "outs": ls.get("outs") or 0,
            "runners_on": runners,
            "away_runs": (t.get("away", {}) or {}).get("runs"),
            "home_runs": (t.get("home", {}) or {}).get("runs")}


def assess(detail: dict, leading_is_home: bool) -> dict:
    """Given a live linescore + which side leads, decide if the game is SAFELY
    decided and whether we're in a high-leverage danger spot right now.

    Returns {decided: bool, danger: bool, lead: int, reason: str}."""
    if not detail or detail.get("inning") is None:
        return {"decided": False, "danger": True, "lead": 0, "reason": "no_state"}
    a, h = detail.get("away_runs"), detail.get("home_runs")
    if a is None or h is None:
        return {"decided": False, "danger": True, "lead": 0, "reason": "no_score"}
    lead = (h - a) if leading_is_home else (a - h)
    inning = detail["inning"]
    # base safe-lead-by-inning threshold
    safe = any(inning >= I and lead >= L for I, L in _SAFE)
    # leverage override: is the TRAILING team batting with a swing that could
    # bring the lead within 1? (bases loaded => up to 4 runs on one swing)
    trailing_batting = (detail["half"] in ("bottom",)) == (not leading_is_home)
    swing = detail["runners_on"] + 1  # runs a grand-slam-type swing could add
    danger = bool(trailing_batting and inning >= 7 and (lead - swing) <= 1
                  and detail["outs"] < 3)
    decided = bool(safe and not danger)
    reason = (f"lead {lead:+d} inn{inning} {detail['half']} outs{detail['outs']} "
              f"runners{detail['runners_on']}" + (" DANGER" if danger else ""))
    return {"decided": decided, "danger": danger, "lead": lead, "reason": reason}
