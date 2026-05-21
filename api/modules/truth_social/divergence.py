"""Divergence reconciliation for Truth Social post counts.

Sir's spec (2026-05-21, revised):
  - When xTracker disagrees with TruthSocial Direct by > DIVERGENCE_THRESHOLD
    posts, swap to CNN Archive as the trading source.
  - NEVER pause the cycle. The bot always trades — divergence just changes
    which post-count source feeds the pacing/signal math.
  - Source preference on divergence: CNN > Direct > xTracker.
  - Daily summary log surfaces every divergence event so Sir can audit.

The whole truth_social module pipeline keys off a single `running_total`
variable. Swap that one value and all downstream math (5 pacing models,
ensemble projection, gates, regime detection, Kelly sizing) automatically
follows the authoritative source.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

log = logging.getLogger(__name__)

# How many posts of disagreement before we trigger the CNN lookup.
# Sir set this 2026-05-21.
DIVERGENCE_THRESHOLD_POSTS = 5


SourceLabel = Literal["xtracker", "direct", "cnn_archive"]


@dataclass
class DivergenceResult:
    # The count downstream code should use for pacing/signals.
    authoritative_count: int
    # Which source won.
    source: SourceLabel
    # Raw counts per source for the dashboard / logs.
    xtracker_count: int
    direct_count: int | None
    cnn_count: int | None
    # True iff |xtracker - direct| > threshold AND a QA was performed.
    divergence_detected: bool
    # Human-readable reason for the badge tooltip / daily summary.
    reason: str


async def resolve_post_count(
    xtracker_count: int,
    direct_count: int | None,
    window_start: datetime,
    window_end: datetime,
    handle: str = "realDonaldTrump",
) -> DivergenceResult:
    """Return the authoritative post count for this cycle.

    Logic (revised 2026-05-21 per Sir):
      - If |xtracker - direct| <= threshold: use xTracker. Fast path.
      - If divergence > threshold: PREFER CNN Archive (most reliable
        public source). Fall back to Direct if CNN unavailable. Fall back
        to xTracker if both are unavailable. **Never pause.**

    The bot always emits signals. Divergence only changes which post-count
    feeds the math.
    """
    # Smell check (2026-05-21): both sources reporting 0 on a multi-day-live
    # auction is itself broken — xTracker can be slow to pick up a new
    # tracking, Direct can be Cloudflare-blocked. In either case, fall back
    # to CNN Archive directly without waiting for a divergence trigger.
    # Only fires when the auction has been running long enough that 0 posts
    # is implausible (Trump posts 25-50/day; 0 over 24h+ = data fault).
    try:
        auction_age_hours = (datetime.now(timezone.utc) - window_start).total_seconds() / 3600.0
    except Exception:
        auction_age_hours = 0.0
    both_zero_on_live_auction = (
        xtracker_count == 0
        and (direct_count is None or direct_count == 0)
        and auction_age_hours > 24
    )
    if both_zero_on_live_auction:
        log.warning(
            f"TS smell-check: xtracker=0 direct={direct_count} on auction live for "
            f"{auction_age_hours:.1f}h. Forcing CNN lookup."
        )
        cnn_count: int | None = None
        try:
            from api.modules.truth_social.truthsocial_via_cnn import (
                count_posts_in_window_via_cnn,
            )
            cnn_res = await count_posts_in_window_via_cnn(window_start, window_end, handle=handle)
            if isinstance(cnn_res.get("count"), int):
                cnn_count = int(cnn_res["count"])
        except Exception as e:
            log.warning(f"CNN archive lookup failed on smell-check: {e}")
        if cnn_count is not None and cnn_count > 0:
            return DivergenceResult(
                authoritative_count=cnn_count,
                source="cnn_archive",
                xtracker_count=xtracker_count,
                direct_count=direct_count,
                cnn_count=cnn_count,
                divergence_detected=True,
                reason=(
                    f"smell-check fired: xtracker=0 direct={direct_count} on "
                    f"{auction_age_hours:.0f}h-live auction; using CNN ({cnn_count})"
                ),
            )

    # Fast path: Direct unavailable or counts agree -> just use xTracker.
    if direct_count is None:
        return DivergenceResult(
            authoritative_count=xtracker_count,
            source="xtracker",
            xtracker_count=xtracker_count,
            direct_count=None,
            cnn_count=None,
            divergence_detected=False,
            reason="direct source unavailable; using xtracker",
        )

    diff = abs(xtracker_count - direct_count)
    if diff <= DIVERGENCE_THRESHOLD_POSTS:
        # Agreement — no CNN lookup needed.
        return DivergenceResult(
            authoritative_count=xtracker_count,
            source="xtracker",
            xtracker_count=xtracker_count,
            direct_count=direct_count,
            cnn_count=None,
            divergence_detected=False,
            reason=f"sources agree (diff={diff})",
        )

    # Divergence > threshold — fetch CNN Archive and PREFER it.
    log.warning(
        f"TS divergence detected: xtracker={xtracker_count} direct={direct_count} "
        f"diff={diff} > threshold={DIVERGENCE_THRESHOLD_POSTS} — switching to CNN Archive"
    )

    cnn_count: int | None = None
    try:
        from api.modules.truth_social.truthsocial_via_cnn import (
            count_posts_in_window_via_cnn,
        )
        cnn_res = await count_posts_in_window_via_cnn(window_start, window_end, handle=handle)
        if isinstance(cnn_res.get("count"), int):
            cnn_count = int(cnn_res["count"])
    except Exception as e:
        log.warning(f"CNN archive lookup failed during divergence: {e}")
        cnn_count = None

    if cnn_count is not None:
        # Preferred path: CNN is the authoritative source on divergence.
        log.warning(
            f"TS divergence -> CNN Archive: cnn={cnn_count} "
            f"(xtracker={xtracker_count} direct={direct_count})"
        )
        return DivergenceResult(
            authoritative_count=cnn_count,
            source="cnn_archive",
            xtracker_count=xtracker_count,
            direct_count=direct_count,
            cnn_count=cnn_count,
            divergence_detected=True,
            reason=(
                f"divergence detected (xtracker={xtracker_count} "
                f"direct={direct_count}); using CNN Archive ({cnn_count})"
            ),
        )

    # CNN unavailable. Fall back to Direct — never pause.
    log.warning(
        f"TS divergence + CNN unavailable; falling back to Direct ({direct_count})"
    )
    return DivergenceResult(
        authoritative_count=direct_count,
        source="direct",
        xtracker_count=xtracker_count,
        direct_count=direct_count,
        cnn_count=None,
        divergence_detected=True,
        reason=(
            f"divergence detected (xtracker={xtracker_count} "
            f"direct={direct_count}); CNN unavailable, using Direct"
        ),
    )


# ============================================================
# Daily divergence summary — called by the daily QA scheduled task.
# ============================================================

async def get_daily_divergence_summary(hours: int = 24) -> dict:
    """Aggregate divergence events from the past N hours into a single
    summary dict the daily QA scheduled task can include in Sir's ping.

    Returns:
        {
          "cycles_with_divergence": int,
          "lookback_hours": int,
          "events": [{"at": iso, "msg": "..."}]  # up to 10 most recent
        }
    """
    from datetime import timedelta
    from api.dependencies import get_supabase

    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        rows = sb.table("logs").select("message,created_at").or_(
            "message.ilike.%Source switched%,message.ilike.%divergence detected%,"
            "message.ilike.%Divergence resolved%,message.ilike.%CNN Archive%"
        ).gte("created_at", cutoff).order("created_at", desc=True).execute().data or []
    except Exception as e:
        log.warning(f"divergence summary fetch failed: {e}")
        return {"error": str(e), "cycles_with_divergence": 0}

    return {
        "cycles_with_divergence": len(rows),
        "lookback_hours": hours,
        "events": [
            {"at": r["created_at"], "msg": r["message"][:200]}
            for r in rows[:10]
        ],
    }
