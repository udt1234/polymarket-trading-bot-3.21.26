"""
Anchor-trade alert cron (15 min cadence).

For each tracked section, find a FRESH live auction (<12h old), look up prev winner's
current price, compute EV, and post a Slack alert if EV > threshold and we haven't
already alerted for that auction.

Dedup state: _DataMetricPulls/alert_state/anchor_alerts.json
"""
import asyncio
import json
import os
import re
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

TRADES_DIR = Path(__file__).parent.parent / "_DataMetricPulls" / "whale_analysis"
SLUG_MAP_FILE = Path(__file__).parent.parent / "_DataMetricPulls" / "target_slug_map_v2.json"
GAMMA = "https://gamma-api.polymarket.com"

ADDON_KEYWORDS = ["-higher-brackets", "-lower-brackets", "-higher-options", "-lower-options",
                  "-25-strikes", "-strikes-of-30", "-brackets-of-30", "-continued"]

# (pattern, window, trade_type, repeat_p, kelly_fraction, label)
TRACKED = [
    ("elon-musk-of-tweets",                "2-Day", "FADE",  0.316, 0.25,  "ELON 2-DAY"),
    ("elon-musk-of-tweets",                "7-Day", "FADE",  0.087, 0.25,  "ELON 7-DAY"),
    ("donald-trump-of-truth-social-posts", "7-Day", "PRESS", 0.444, 0.125, "TRUMP TRUTH SOCIAL"),
    ("nyc-mayor-of-tweets",                "7-Day", "PRESS", 1.000, 0.125, "NYC MAYOR"),
]

MIN_EV_PER_SHARE = 0.02
MAX_AUCTION_AGE_HR = 12
BANKROLL = float(os.environ.get("ANCHOR_BANKROLL", "1000"))


def is_addon(slug):
    return any(kw in slug.lower() for kw in ADDON_KEYWORDS)


def normalize_bucket(s):
    if s is None:
        return "?"
    s = str(s).strip().replace("–", "-").replace("—", "-")
    return re.sub(r"(\d)K\b", r"\1k", s)


def classify_window_days(days):
    if days <= 5: return "2-Day"
    if days <= 12: return "7-Day"
    if days <= 20: return "Biweekly"
    return "Monthly"


def kelly_fade(p, X):
    if X <= 0 or X >= 1 or p <= 0 or p >= 1: return 0
    b = X / (1 - X)
    return max(0, (b * (1 - p) - p) / b)


def kelly_press(p, X):
    if X <= 0 or X >= 1: return 0
    if p >= 1: return 1.0
    b = (1 - X) / X
    return max(0, (b * p - (1 - p)) / b)


async def get_event(client, slug):
    try:
        r = await client.get(f"{GAMMA}/events/slug/{slug}", timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def determine_winner_from_parquet(path):
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if df.empty or "outcome" not in df.columns or "hours_in" not in df.columns:
        return None
    df = df[df["outcome"] == "Yes"].dropna(subset=["hours_in"]).copy()
    if df.empty:
        return None
    df["bn"] = df["_bucket"].apply(normalize_bucket)
    df["hr"] = df["hours_in"].astype(int)
    last = df["hr"].max()
    if pd.isna(last):
        return None
    final = df[df["hr"] >= last - 4]
    if final.empty:
        return None
    by_b = final.groupby("bn")["price"].mean()
    cands = by_b[by_b >= 0.85]
    if cands.empty:
        return None
    return cands.idxmax()


def winner_from_event(event):
    """Fallback when no parquet -- use gamma final outcomePrices."""
    for m in (event.get("markets") or []):
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                continue
        if prices and len(prices) >= 1:
            try:
                if float(prices[0]) >= 0.85:
                    return normalize_bucket(m.get("groupItemTitle") or "")
            except Exception:
                pass
    return None


def get_market_price(event, bracket_norm):
    for m in (event.get("markets") or []):
        if normalize_bucket(m.get("groupItemTitle") or "") == bracket_norm:
            prices = m.get("outcomePrices")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except Exception:
                    return None
            if prices and len(prices) >= 1:
                try:
                    return float(prices[0])
                except Exception:
                    return None
    return None


def format_layman_message(label, trade_type, prev_winner, current_price, p_repeat,
                          ev, n_shares, dollars_at_risk, expected_profit, live_slug,
                          elapsed_hr, fair_price):
    url = polymarket_event_url(live_slug)
    age_str = f"{elapsed_hr:.1f}h" if elapsed_hr is not None else "?"
    if trade_type == "FADE":
        action_verb = "SELL YES on"
        close_target = f"${fair_price:.2f}"
        plain = (
            f"Last week, the *{prev_winner}* bracket won the {label.lower()} auction.\n"
            f"The market just opened the NEW auction with *{prev_winner}* priced at *${current_price:.4f}*.\n"
            f"Historically, prev winners only repeat *{p_repeat*100:.1f}%* of the time — fair price ~${fair_price:.2f}.\n"
            f"This is *overpriced anchor bias*. Selling YES collects the premium."
        )
        risk_line = f"Risk *${dollars_at_risk:.2f}* (max ${1-current_price:.2f}/share if it repeats)"
        close_line = f"Close: buy-to-close at *${fair_price:.2f}* or hold to settlement"
    else:
        action_verb = "BUY YES on"
        close_target = "$0.85+ (or hold to settlement)"
        plain = (
            f"Last week, the *{prev_winner}* bracket won the {label.lower()} auction.\n"
            f"The market just opened the NEW auction with *{prev_winner}* priced at *${current_price:.4f}*.\n"
            f"Historically, prev winners repeat *{p_repeat*100:.1f}%* of the time — fair price ~${p_repeat:.2f}.\n"
            f"This is *underpriced anchor bias*. Buying YES captures the gap."
        )
        risk_line = f"Risk *${dollars_at_risk:.2f}* (max ${current_price:.2f}/share if it fails to repeat)"
        close_line = f"Close: sell at *${p_repeat*0.85:.2f}+* or hold to settlement"

    header = f"🎯 *{label}: {trade_type} OPPORTUNITY* (auction is {age_str} old)"

    text = (
        f"{header}\n\n"
        f"📊 *The play:*\n{plain}\n\n"
        f"💰 *What to do:*\n"
        f"{action_verb} the *{prev_winner}* bracket\n"
        f"• {n_shares} shares at *${current_price:.4f}* (or better)\n"
        f"• {risk_line}\n"
        f"• Expected profit: *${expected_profit:+.2f}*\n\n"
        f"⏰ *Timing:*\n"
        f"{close_line}\n"
        f"Window closes in {MAX_AUCTION_AGE_HR - elapsed_hr:.1f}h\n\n"
        f"🔗 *Trade here:* {url}"
    )
    return text


async def main():
    slug_map = json.loads(SLUG_MAP_FILE.read_text())
    state = load_state("anchor_alerts")
    state = expire_old_entries(state, max_age_hours=168)  # keep 1 week of dedup
    alerts_sent = 0

    async with httpx.AsyncClient() as client:
        for pattern, window, trade_type, p_repeat, kelly_frac, label in TRACKED:
            slugs = [s for s in slug_map.get(pattern, []) if not is_addon(s)]
            now_year = str(datetime.now(timezone.utc).year)
            slugs = sorted(slugs, key=lambda s: (
                0 if (now_year in s or "may" in s.lower() or "apr" in s.lower() or "jun" in s.lower()) else 1,
                s,
            ))

            events = []
            for s in slugs[:120]:
                e = await get_event(client, s)
                if not e:
                    continue
                sd = (e.get("startDate") or "")[:10]
                ed = (e.get("endDate") or "")[:10]
                if not sd or not ed:
                    continue
                try:
                    days = (datetime.fromisoformat(ed) - datetime.fromisoformat(sd)).days
                except Exception:
                    continue
                if classify_window_days(days) != window:
                    continue
                events.append((s, sd, ed, e))

            today = datetime.now(timezone.utc).date().isoformat()
            live = [x for x in events if x[2] >= today]
            completed = [x for x in events if x[2] < today]
            if not live or not completed:
                continue

            live.sort(key=lambda x: x[1])
            completed.sort(key=lambda x: x[2], reverse=True)
            live_slug, live_sd, live_ed, live_event = live[0]
            prev_slug, _, _, prev_event = completed[0]

            # Compute auction age
            try:
                start_dt = datetime.fromisoformat(live_event["startDate"].replace("Z", "+00:00"))
                elapsed_hr = (datetime.now(timezone.utc) - start_dt).total_seconds() / 3600
            except Exception:
                elapsed_hr = None

            if elapsed_hr is None or elapsed_hr > MAX_AUCTION_AGE_HR:
                continue  # too old

            # Determine prev winner
            parquet_path = TRADES_DIR / f"trades_{prev_slug}.parquet"
            prev_winner = determine_winner_from_parquet(parquet_path)
            if prev_winner is None:
                prev_winner = winner_from_event(prev_event)
            if prev_winner is None:
                continue

            current_price = get_market_price(live_event, prev_winner)
            if current_price is None or current_price <= 0 or current_price >= 1:
                continue

            # EV check
            X = current_price
            if trade_type == "FADE":
                full_k = kelly_fade(p_repeat, X)
                ev = (1 - p_repeat) * X - p_repeat * (1 - X)
                risk_per_share = 1 - X
                fair_price = p_repeat
            else:
                full_k = kelly_press(p_repeat, X)
                ev = p_repeat * (1 - X) - (1 - p_repeat) * X
                risk_per_share = X
                fair_price = p_repeat

            if ev < MIN_EV_PER_SHARE:
                continue

            partial_k = full_k * kelly_frac
            dollars_at_risk = BANKROLL * partial_k
            n_shares = int(dollars_at_risk / risk_per_share) if risk_per_share > 0 else 0
            expected_profit = n_shares * ev

            # Dedup key: section + live_slug
            dedup_key = f"{label}::{live_slug}"
            if dedup_key in state:
                continue  # already alerted on this auction

            msg = format_layman_message(
                label, trade_type, prev_winner, current_price, p_repeat,
                ev, n_shares, dollars_at_risk, expected_profit, live_slug,
                elapsed_hr, fair_price,
            )
            ok = send_slack(msg)
            if ok:
                state[dedup_key] = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "label": label,
                    "trade_type": trade_type,
                    "prev_winner": prev_winner,
                    "current_price": current_price,
                    "ev": ev,
                    "n_shares": n_shares,
                }
                alerts_sent += 1
                print(f"  ALERT sent: {label} {trade_type} on {prev_winner} @ ${current_price:.4f} (EV ${ev:+.4f})")

    save_state("anchor_alerts", state)
    print(f"\nanchor-alert cron done at {datetime.now(timezone.utc).isoformat()}: {alerts_sent} alert(s) sent")


if __name__ == "__main__":
    asyncio.run(main())
