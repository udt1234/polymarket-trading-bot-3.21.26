"""Divergence reconciliation for Truth Social post counts.

When xTracker (current trading path) and TruthSocial Direct disagree by more
than a configurable threshold, the bot can't trust either number blindly.
This module:

  1. Detects the divergence at each cycle.
  2. Queries 2 independent sources of truth (CNN Archive + Direct scrape).
  3. Picks the consensus value, OR pauses the module if sources disagree.
  4. Returns the authoritative count for downstream pacing/signal code.

Sir's requirement (2026-05-21):
  > If divergence > 5 posts, QA with 2 other sources. If confirmed real,
  > use TruthSocial Direct instead of xTracker for trading + pacing.

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

# How many posts of disagreement before we trigger the QA flow.
# Sir set this 2026-05-21. Tunable per-module via config later if needed.
DIVERGENCE_THRESHOLD_POSTS = 5

# When 2 sources agree within this delta, we treat them as confirming.
SOURCE_AGREEMENT_TOLERANCE = 3


SourceLabel = Literal["xtracker", "direct", "cnn_archive", "disputed"]


@dataclass
class DivergenceResult:
    # The count downstream code should use for pacing/signals.
    authoritative_count: int
    # Which source won. 'disputed' means the QA failed and the caller
    # should PAUSE rather than trade.
    source: SourceLabel
    # Raw counts per source for the dashboard / logs.
    xtracker_count: int
    direct_count: int | None
    cnn_count: int | None
    # True iff |xtracker - direct| > threshold AND a QA was performed.
    divergence_detected: bool
    # True iff sources disagree and module should pause.
    paused: bool
    # Human-readable reason for the badge tooltip.
    reason: str


async def resolve_post_count(
    xtracker_count: int,
    direct_count: int | None,
    window_start: datetime,
    window_end: datetime,
    handle: str = "realDonaldTrump",
) -> DivergenceResult:
    """Return the authoritative post count for this cycle.

    Logic:
      - If |xtracker - direct| <= threshold: NO QA. Return xtracker (it's
        fast and we trust it when it agrees with Direct within tolerance).
      - If divergence > threshold: query CNN Archive as 3rd source.
        * If CNN agrees with Direct (within tolerance): swap to Direct.
        * If CNN agrees with xTracker (within tolerance): keep xTracker
          (Direct is the outlier — could be cloudflare blocking partial).
        * If neither agrees with CNN OR CNN unavailable: PAUSE module.

    Note on caller cost: this function only fetches CNN Archive when
    divergence is detected. Steady-state with agreement = 0 extra HTTP calls.
    """
    # Fast path: Direct unavailable or counts agree -> just use xTracker.
    if direct_count is None:
        return DivergenceResult(
            authoritative_count=xtracker_count,
            source="xtracker",
            xtracker_count=xtracker_count,
            direct_count=None,
            cnn_count=None,
            divergence_detected=False,
            paused=False,
            reason="direct source unavailable; using xtracker",
        )

    diff = abs(xtracker_count - direct_count)
    if diff <= DIVERGENCE_THRESHOLD_POSTS:
        # Agreement — no QA needed.
        return DivergenceResult(
            authoritative_count=xtracker_count,
            source="xtracker",
            xtracker_count=xtracker_count,
            direct_count=direct_count,
            cnn_count=None,
            divergence_detected=False,
            paused=False,
            reason=f"sources agree (diff={diff})",
        )

    # Divergence > threshold — run QA via CNN Archive.
    log.warning(
        f"TS divergence detected: xtracker={xtracker_count} direct={direct_count} "
        f"diff={diff} > threshold={DIVERGENCE_THRESHOLD_POSTS} — querying CNN Archive"
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
        log.warning(f"CNN archive lookup failed during divergence QA: {e}")
        cnn_count = None

    if cnn_count is None:
        # No third source available -> can't confirm. Pause as safety net.
        return DivergenceResult(
            authoritative_count=xtracker_count,
            source="disputed",
            xtracker_count=xtracker_count,
            direct_count=direct_count,
            cnn_count=None,
            divergence_detected=True,
            paused=True,
            reason=(
                f"diff={diff} between xtracker={xtracker_count} and direct={direct_count}; "
                f"CNN archive unavailable for confirmation — module paused"
            ),
        )

    # Compare CNN to both candidates.
    cnn_vs_xtracker = abs(cnn_count - xtracker_count)
    cnn_vs_direct = abs(cnn_count - direct_count)

    cnn_agrees_with_direct = cnn_vs_direct <= SOURCE_AGREEMENT_TOLERANCE
    cnn_agrees_with_xtracker = cnn_vs_xtracker <= SOURCE_AGREEMENT_TOLERANCE

    if cnn_agrees_with_direct and not cnn_agrees_with_xtracker:
        # Direct wins. Swap.
        log.warning(
            f"TS divergence confirmed by CNN: cnn={cnn_count} direct={direct_count} "
            f"(diff={cnn_vs_direct}) vs xtracker={xtracker_count} (diff={cnn_vs_xtracker}). "
            f"Switching authoritative source to Direct."
        )
        return DivergenceResult(
            authoritative_count=direct_count,
            source="direct",
            xtracker_count=xtracker_count,
            direct_count=direct_count,
            cnn_count=cnn_count,
            divergence_detected=True,
            paused=False,
            reason=(
                f"CNN ({cnn_count}) confirms Direct ({direct_count}); "
                f"xTracker ({xtracker_count}) is stale. Using Direct."
            ),
        )

    if cnn_agrees_with_xtracker and not cnn_agrees_with_direct:
        log.info(
            f"TS divergence: CNN ({cnn_count}) confirms xTracker ({xtracker_count}); "
            f"Direct ({direct_count}) is the outlier. Keeping xTracker."
        )
        return DivergenceResult(
            authoritative_count=xtracker_count,
            source="xtracker",
            xtracker_count=xtracker_count,
            direct_count=direct_count,
            cnn_count=cnn_count,
            divergence_detected=True,
            paused=False,
            reason=(
                f"CNN ({cnn_count}) confirms xTracker; Direct ({direct_count}) is outlier"
            ),
        )

    # No clear consensus -> pause.
    log.error(
        f"TS post count source disputed: xtracker={xtracker_count} direct={direct_count} "
        f"cnn={cnn_count} (no consensus). Pausing module."
    )
    return DivergenceResult(
        authoritative_count=xtracker_count,
        source="disputed",
        xtracker_count=xtracker_count,
        direct_count=direct_count,
        cnn_count=cnn_count,
        divergence_detected=True,
        paused=True,
        reason=(
            f"3-way disagreement (xtracker={xtracker_count} "
            f"direct={direct_count} cnn={cnn_count}); module paused"
        ),
    )
