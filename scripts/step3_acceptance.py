"""BUILD_SPEC PART J Step 3 acceptance test.

For a LIVE Elon auction: print the current in-window count, the projection,
and a bracket probability distribution that sums to 1 with impossible
brackets at exactly 0. Read-only (Gamma + xTracker), no orders.

Run: python -u scripts/step3_acceptance.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.modules.shared import discovery, fair_value, windows
from api.modules.shared.polymarket import fetch_xtracker_stats, get_xtracker_summary
import httpx


def live_tracking_for(slug: str) -> dict | None:
    r = httpx.get("https://xtracker.polymarket.com/api/users/elonmusk/trackings",
                  params={"platform": "x"}, timeout=30)
    items = r.json()
    if isinstance(items, dict):
        items = items.get("data", [])
    tail = slug.split("/")[-1]
    for t in items:
        if (t.get("marketLink") or "").rstrip("/").endswith(tail):
            return t
    return None


def main() -> None:
    print("== 1. discovery (Gamma tag 972) ==")
    auctions = discovery.fetch_tweet_auctions(slug_contains="elon-musk-of-tweets")
    print(f"  live Elon count auctions: {len(auctions)}")
    for a in auctions:
        print(f"   - {a['slug']} [{a['duration_type']}] {len(a['brackets'])} live brackets")
    auction = discovery.freshest_auction(auctions, duration="2-day") or discovery.freshest_auction(auctions)
    if not auction:
        raise SystemExit("ACCEPT FAIL: no live auction in window")

    print("== 2. window (parsed from slug, noon ET) ==")
    ws, we = auction["window_start"], auction["window_end"]
    elapsed = windows.elapsed_fraction(ws, we)
    print(f"  {auction['slug']}: {ws}  ->  {we}  ({auction['duration_type']})")
    print(f"  elapsed_fraction: {elapsed:.4f}")

    print("== 3. current count (xTracker) ==")
    tracking = live_tracking_for(auction["slug"])
    if not tracking:
        raise SystemExit("ACCEPT FAIL: no xTracker tracking matches the auction slug")
    stats = asyncio.run(fetch_xtracker_stats(tracking["id"]))
    summary = get_xtracker_summary(stats)
    count = int(summary.get("total") or 0)
    print(f"  tracking: {tracking['title']}")
    print(f"  count so far: {count} (pace {summary.get('pace')}, "
          f"{summary.get('percent_complete')}% complete)")

    print("== 4. projection (Gamma-Poisson posterior) ==")
    prior_mean, prior_std = fair_value.VALIDATED_PRIORS.get(
        auction["duration_type"], fair_value.VALIDATED_PRIORS["2-day"])
    projection = fair_value.gamma_poisson_projection(count, elapsed, prior_mean, prior_std)
    naive = count / max(elapsed, 1e-9)
    print(f"  prior ({auction['duration_type']}): mean {prior_mean} std {prior_std}")
    print(f"  naive linear: {naive:.1f}  |  posterior projection: {projection:.1f}")

    print("== 5. bracket distribution ==")
    labels = [b["label"] for b in auction["brackets"]]
    dist = fair_value.bracket_distribution(projection, count, labels)
    print(f"  {'bracket':<14} {'fair':>7} {'bid':>6} {'ask':>6} {'edge@ask':>9}")
    for b in auction["brackets"]:
        fv = dist[b["label"]]
        e = fair_value.edge(fv, b["best_ask"])
        print(f"  {b['label']:<14} {fv:>7.4f} "
              f"{(b['best_bid'] if b['best_bid'] is not None else float('nan')):>6.3f} "
              f"{(b['best_ask'] if b['best_ask'] is not None else float('nan')):>6.3f} "
              f"{(e if e is not None else float('nan')):>9.4f}")

    total = sum(dist.values())
    impossible = [l for l in labels
                  if (rng := fair_value.parse_bracket_range(l)) and rng[1] < count]
    bad_impossible = [l for l in impossible if dist[l] != 0.0]
    print(f"\n  sum(probabilities) = {total:.6f}")
    print(f"  impossible brackets (upper < {count}): {impossible} -> "
          f"all zero: {not bad_impossible}")

    ok = abs(total - 1.0) < 1e-6 and not bad_impossible and projection > 0
    print("\nACCEPT PASS" if ok else "\nACCEPT FAIL")


if __name__ == "__main__":
    main()
