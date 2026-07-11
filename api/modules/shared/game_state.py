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

# base-out run expectancy (RE24) collapsed to (runners_on, outs). The live feed
# gives only the runner COUNT, not exact base occupancy, so each row averages the
# same-count states from a standard 2010s RE24 matrix. Used by win_prob() as the
# batting team's expected runs this inning (the rally value).
RE_BY_COUNT = {
    0: [0.481, 0.254, 0.098],   # empty
    1: [1.103, 0.708, 0.299],   # one on  (avg of 1st/2nd/3rd)
    2: [1.728, 1.130, 0.496],   # two on  (avg of 1st_2nd/1st_3rd/2nd_3rd)
    3: [2.292, 1.541, 0.752],   # loaded
}
_VAR_PER_INNING = 1.05   # per-team run variance in one inning (calibration knob)

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


def evaluate_game(slug: str, fav_outcome: str,
                  states: dict[tuple[str, str], dict] | None = None) -> dict:
    """ONE live-feed fetch for a Polymarket game slug (mlb-<away>-<home>-<date>).
    Returns {ok, reason, p_true}:
      ok      = safe to sweep (SAFELY decided + not a high-leverage danger spot)
      reason  = human tag for logs
      p_true  = continuous fair win prob for the favorite (None on lookup miss)
    p_true is the FAIR VALUE the sweep prices against: edge = p_true - price."""
    out = {"ok": False, "reason": "no_state", "p_true": None}
    parts = slug.split("-")
    if len(parts) < 5:
        out["reason"] = "bad_slug"
        return out
    away, home = parts[1], parts[2]
    if states is None:
        states = mlb_live_states()
    st = states.get((away, home))
    if not st:
        return out
    if st["state"] == "Final":
        out["reason"] = "final"
        return out
    fav_ab = abbr_for_name(fav_outcome)
    if fav_ab not in (away, home):
        out["reason"] = "unmatched_team"
        return out
    detail = game_detail(st["pk"])
    leading_is_home = (fav_ab == home)
    a = assess(detail, leading_is_home)
    out["ok"] = a["decided"]
    out["reason"] = a["reason"]
    out["p_true"] = win_prob(detail, leading_is_home)
    return out


def sweep_ok_by_state(slug: str, fav_outcome: str,
                      states: dict[tuple[str, str], dict] | None = None) -> tuple[bool, str]:
    """Back-compat thin wrapper over evaluate_game (ok, reason only)."""
    r = evaluate_game(slug, fav_outcome, states)
    return r["ok"], r["reason"]


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


def _innings_left(inning: int, half: str, outs: int) -> tuple[float, float]:
    """Remaining full-inning-equivalents of offense for (batting_team, other_team)
    in a 9-inning game. 'batting' = the side currently at the plate. Used only for
    the remaining-run-margin variance, so the split between the two is symmetric."""
    half = (half or "").lower()
    future = max(0, 9 - inning)                 # full innings after this one (each side)
    if half == "top":                           # away batting; home still bats this inning
        return (3 - outs) / 3.0 + future, 1.0 + future
    if half == "bottom":                        # home batting; away already done this inning
        return (3 - outs) / 3.0 + future, float(future)
    if half == "middle":                        # between halves: home to bat next
        return 1.0 + future, float(future)
    return 1.0 + future, 1.0 + future           # 'end'/unknown: inning over


def win_prob(detail: dict, leading_is_home: bool) -> float:
    """Continuous FAIR win probability for the LEADING side from score + base-out
    state. Normal-approx of the remaining run margin:
        p = Phi((lead + rally) / sd)
    where 'rally' is the batting team's expected runs this inning (RE24, signed to
    the favorite) and 'sd' shrinks as the game runs out of outs. This is a v1
    parametric model - monotonic and directionally correct; calibrate the two
    knobs (_VAR_PER_INNING, RE weighting) against recorded finals later. Clamped
    to [0.01, 0.99] - never 100% until the game is Final."""
    from math import erf, sqrt
    if not detail or detail.get("inning") is None:
        return 0.5
    a, h = detail.get("away_runs"), detail.get("home_runs")
    if a is None or h is None:
        return 0.5
    lead = (h - a) if leading_is_home else (a - h)
    inning = detail["inning"]
    half = (detail.get("half") or "").lower()
    outs = int(detail.get("outs") or 0)
    runners = int(detail.get("runners_on") or 0)
    re = RE_BY_COUNT.get(runners, RE_BY_COUNT[0])[min(outs, 2)]
    batting_is_home = half == "bottom"
    fav_batting = (batting_is_home == leading_is_home)
    rally = re if fav_batting else -re          # helps whoever is batting
    bat_left, field_left = _innings_left(inning, half, outs)
    sd = (_VAR_PER_INNING * (bat_left + field_left)) ** 0.5
    if sd < 1e-6:
        return 0.99 if lead > 0 else (0.01 if lead < 0 else 0.5)
    z = (lead + rally) / sd
    p = 0.5 * (1 + erf(z / sqrt(2)))
    return max(0.01, min(0.99, p))


def edge(p_true: float, price: float) -> float:
    """Trading edge on a BUY: fair value minus the price we pay."""
    return p_true - price
