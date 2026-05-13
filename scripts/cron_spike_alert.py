"""
Spike-alert cron (5 min cadence).

For each tracked handle, find any LIVE auction and scan every bracket's recent
hourly price trajectory. Fire two types of alerts:

  STARTED: smoothed price just jumped +40% from prior hour, prior was <$0.50.
           (Earlier signal, higher false-positive rate, but lets you enter cheap.)
  CONFIRMED: same trigger PLUS next 2 hours stayed >= 70% of peak.
             (Lower false-positive but you enter 2-3h later at higher price.)

Dedup state: _DataMetricPulls/alert_state/spike_alerts.json
"""
import asyncio
import json
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from anchor_alert_lib import (
    expire_old_entries,
    load_state,
    polymarket_event_url,
    save_state,
    send_slack,
)

SLUG_MAP_FILE = Path(__file__).parent.parent / "_DataMetricPulls" / "target_slug_map_v2.json"
GAMMA = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

ADDON_KEYWORDS = ["-higher-brackets", "-lower-brackets", "-higher-options", "-lower-options",
                  "-25-strikes", "-strikes-of-30", "-brackets-of-30", "-continued"]

# Patterns to scan for live spikes
HANDLES = [
    ("elon-musk-of-tweets",                "ELON"),
    ("donald-trump-of-truth-social-posts", "TRUMP TS"),
    ("white-house-of-tweets",              "WHITE HOUSE"),
    ("ted-cruz-of-tweets",                 "TED CRUZ"),
    ("nyc-mayor-of-tweets",                "NYC MAYOR"),
    ("khamenei-of-tweets",                 "KHAMENEI"),
    ("zelenskyy-of-tweets",                "ZELENSKYY"),
    ("cz-binance-of-tweets",               "CZ BINANCE"),
]

# Spike detection thresholds (same as v4)
MIN_PCT_CHANGE = 0.40       # +40% jump
MAX_PRIOR_PRICE = 0.50      # prior baseline must be < $0.50
SUSTAIN_FACTOR = 0.70       # next 2 hours must be >= 70% of peak
MIN_TRADES_PER_HOUR = 3
SKIP_FIRST_HOURS = 4

# Don't alert on already-expensive brackets (no edge left)
MAX_CURRENT_PRICE_FOR_ALERT = 0.65

# Spike must have happened within last N hours (else it's old news, not actionable)
SPIKE_FRESHNESS_HOURS = 4

# Minimum SPIKE PRICE -- below this, +40% jumps are noise from sub-cent values
MIN_SPIKE_PRICE = 0.05

# First-run baseline mode: if state file is empty, populate without sending alerts
BASELINE_MODE_ENV = "SPIKE_ALERT_BASELINE_MODE"


def is_addon(slug):
    return any(kw in slug.lower() for kw in ADDON_KEYWORDS)


def normalize_bucket(s):
    if s is None:
        return "?"
    s = str(s).strip().replace("–", "-").replace("—", "-")
    return re.sub(r"(\d)K\b", r"\1k", s)


async def get_event(client, slug):
    try:
        r = await client.get(f"{GAMMA}/events/slug/{slug}", timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def get_trades(client, condition_id, limit=500):
    """Fetch recent trades for a given conditionId from data-api."""
    try:
        r = await client.get(f"{DATA_API}/trades", params={"market": condition_id, "limit": limit}, timeout=15)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def auction_start_dt(event):
    sd = event.get("startDate")
    if not sd:
        return None
    try:
        return datetime.fromisoformat(sd.replace("Z", "+00:00"))
    except Exception:
        return None


def detect_spike_from_trades(trades, start_dt, now_dt):
    """Returns dict with 'started', 'confirmed', and details if a FRESH spike fires; else None.

    Only fires when the spike's hour-bucket is within SPIKE_FRESHNESS_HOURS of now.
    """
    if not trades:
        return None
    # Build hourly DataFrame YES-only
    rows = []
    for t in trades:
        if t.get("outcome") != "Yes":
            continue
        ts = t.get("timestamp")
        price = t.get("price")
        if ts is None or price is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            hours_in = (dt - start_dt).total_seconds() / 3600
            rows.append((int(hours_in), float(price)))
        except Exception:
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["hour", "price"])
    # Aggregate by hour bucket
    piv = df.groupby("hour").agg(mean=("price", "mean"), n=("price", "count")).reset_index()
    piv = piv.sort_values("hour").reset_index(drop=True)
    sig = piv[piv["n"] >= MIN_TRADES_PER_HOUR].copy().reset_index(drop=True)
    if len(sig) < 5:
        return None
    sig["smoothed"] = sig["mean"].rolling(window=3, min_periods=1).mean()
    sig["pct_change"] = sig["smoothed"].pct_change()
    sig = sig[sig["hour"] > SKIP_FIRST_HOURS].reset_index(drop=True)
    if sig.empty:
        return None
    # Compute current auction-hour (used for freshness gate)
    auction_hour_now = (now_dt - start_dt).total_seconds() / 3600
    # Look at the most recent spike candidate
    for i in reversed(range(len(sig))):
        row = sig.iloc[i]
        pct = row.get("pct_change")
        if pct is None or pd.isna(pct):
            continue
        if pct < MIN_PCT_CHANGE:
            continue
        if i < 1:
            continue
        # FRESHNESS GATE: spike must have happened within last SPIKE_FRESHNESS_HOURS hours
        spike_hour = int(row["hour"])
        if auction_hour_now - spike_hour > SPIKE_FRESHNESS_HOURS:
            return None  # most recent qualifying spike is too old -- not actionable
        prior = sig.iloc[i - 1]["smoothed"]
        if prior >= MAX_PRIOR_PRICE:
            continue
        # PRICE FLOOR: skip ultra-cheap noise
        if float(row["smoothed"]) < MIN_SPIKE_PRICE:
            continue
        # STARTED triggered. Check CONFIRMED?
        confirmed = False
        if i + 2 < len(sig):
            next_2 = sig.iloc[i + 1: i + 3]["smoothed"].mean()
            if next_2 >= row["smoothed"] * SUSTAIN_FACTOR:
                confirmed = True
        return {
            "started": True,
            "confirmed": confirmed,
            "spike_hour": spike_hour,
            "prior_price": float(prior),
            "spike_price": float(row["smoothed"]),
            "pct_change": float(pct),
        }
    return None


def format_spike_message(handle_label, live_slug, bracket, spike_info, current_price, alert_kind):
    url = polymarket_event_url(live_slug)
    prior = spike_info["prior_price"]
    peak = spike_info["spike_price"]
    pct = spike_info["pct_change"] * 100

    if alert_kind == "CONFIRMED":
        kind_emoji = "🚀"
        kind_label = "CONFIRMED SPIKE (high confidence)"
        plain = (
            f"The *{bracket}* bracket of the {handle_label} auction had a *price spike* and held it for 2+ hours.\n"
            f"It went from *${prior:.4f}* up to *${peak:.4f}* (+{pct:.0f}%) — sustained move, not noise."
        )
    else:
        kind_emoji = "📈"
        kind_label = "EARLY SPIKE SIGNAL (speculative)"
        plain = (
            f"The *{bracket}* bracket of the {handle_label} auction *just spiked*.\n"
            f"Price jumped from *${prior:.4f}* to *${peak:.4f}* (+{pct:.0f}%) — could be the start of a sustained run, or a fakeout."
        )

    action_block = (
        f"💰 *What to do:*\n"
        f"BUY YES on *{bracket}* at *${current_price:.4f}* if still cheap\n"
        f"• If you held a patient $0.001-0.01 bid, you may already be filled — check your orders\n"
        f"• If you're entering now, *only buy if YES < $0.30* to keep edge intact\n\n"
        f"⏰ *When to sell:*\n"
        f"Target close: *$0.85-0.95* (or settle at $1 if it wins)\n"
        f"Stop: exit if YES drops below *${prior:.4f}* (the spike unwound)\n\n"
        f"🔗 *Trade here:* {url}"
    )

    header = f"{kind_emoji} *{handle_label}: {kind_label}*"
    return (
        f"{header}\n\n"
        f"📊 *What happened:*\n{plain}\n"
        f"Current YES price: *${current_price:.4f}*\n\n"
        f"{action_block}"
    )


async def main():
    slug_map = json.loads(SLUG_MAP_FILE.read_text())
    state = load_state("spike_alerts")
    state = expire_old_entries(state, max_age_hours=168)
    alerts_sent = 0
    baseline_mode = os.environ.get(BASELINE_MODE_ENV, "0") == "1"
    if baseline_mode:
        print("BASELINE MODE: populating dedup state without sending Slack alerts")

    today = datetime.now(timezone.utc).date().isoformat()
    now_dt = datetime.now(timezone.utc)

    async with httpx.AsyncClient() as client:
        for pattern, handle_label in HANDLES:
            slugs = [s for s in slug_map.get(pattern, []) if not is_addon(s)]
            now_year = str(datetime.now(timezone.utc).year)
            slugs = sorted(slugs, key=lambda s: (
                0 if (now_year in s or "may" in s.lower() or "apr" in s.lower() or "jun" in s.lower()) else 1,
                s,
            ))

            # Find live auctions for this handle
            live_auctions = []
            for s in slugs[:60]:
                e = await get_event(client, s)
                if not e:
                    continue
                ed = (e.get("endDate") or "")[:10]
                if ed and ed >= today:
                    live_auctions.append((s, e))

            if not live_auctions:
                continue

            for live_slug, live_event in live_auctions:
                start_dt = auction_start_dt(live_event)
                if start_dt is None:
                    continue
                elapsed_hr = (datetime.now(timezone.utc) - start_dt).total_seconds() / 3600
                if elapsed_hr < SKIP_FIRST_HOURS + 2:
                    continue  # not enough data yet

                for m in (live_event.get("markets") or []):
                    bracket = normalize_bucket(m.get("groupItemTitle") or "")
                    if bracket == "?":
                        continue
                    cid = m.get("conditionId")
                    if not cid:
                        continue
                    prices = m.get("outcomePrices")
                    if isinstance(prices, str):
                        try:
                            prices = json.loads(prices)
                        except Exception:
                            prices = None
                    current_price = None
                    if prices and len(prices) >= 1:
                        try:
                            current_price = float(prices[0])
                        except Exception:
                            pass
                    if current_price is None or current_price > MAX_CURRENT_PRICE_FOR_ALERT:
                        continue  # already too expensive, no edge

                    # Pull recent trades
                    trades = await get_trades(client, cid, limit=500)
                    spike = detect_spike_from_trades(trades, start_dt, now_dt)
                    if not spike:
                        continue
                    # If current price has fallen back BELOW the pre-spike baseline,
                    # the spike has fully unwound. Don't alert.
                    if current_price < spike["prior_price"]:
                        continue
                    # Also bail if current price is sub-cent (alert would say "buy at $0.00")
                    if current_price < 0.005:
                        continue

                    # Determine alert kind
                    alert_kind = "CONFIRMED" if spike["confirmed"] else "STARTED"
                    dedup_key = f"{live_slug}::{bracket}::{alert_kind}"
                    if dedup_key in state:
                        continue
                    # If we already sent CONFIRMED, don't also send STARTED later
                    if alert_kind == "STARTED" and f"{live_slug}::{bracket}::CONFIRMED" in state:
                        continue

                    # In baseline mode, record in state but don't send Slack
                    if baseline_mode:
                        state[dedup_key] = {
                            "ts": now_dt.isoformat(),
                            "handle": handle_label,
                            "bracket": bracket,
                            "alert_kind": alert_kind,
                            "spike_hour": spike["spike_hour"],
                            "spike_price": spike["spike_price"],
                            "current_price": current_price,
                            "baseline": True,
                        }
                        print(f"  BASELINE: {handle_label} {bracket} +{spike['pct_change']*100:.0f}% @ ${current_price:.4f}")
                        continue

                    msg = format_spike_message(handle_label, live_slug, bracket, spike, current_price, alert_kind)
                    ok = send_slack(msg)
                    if ok:
                        state[dedup_key] = {
                            "ts": now_dt.isoformat(),
                            "handle": handle_label,
                            "bracket": bracket,
                            "alert_kind": alert_kind,
                            "spike_hour": spike["spike_hour"],
                            "spike_price": spike["spike_price"],
                            "current_price": current_price,
                        }
                        alerts_sent += 1
                        print(f"  ALERT {alert_kind}: {handle_label} {bracket} +{spike['pct_change']*100:.0f}% @ ${current_price:.4f}")

    save_state("spike_alerts", state)
    print(f"\nspike-alert cron done at {datetime.now(timezone.utc).isoformat()}: {alerts_sent} alert(s) sent")


if __name__ == "__main__":
    asyncio.run(main())
