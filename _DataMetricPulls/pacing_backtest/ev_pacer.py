"""EV pacer for the accumulate-and-hold / partial-arb strategy.

Your strategy (as described): buy the cheap low bracket and HOLD, add other brackets
on seesaw dips, never sell out, collect $1 on whichever bracket wins. This tool does
the expected-value math for exactly that, on LIVE prices.

For a basket of YES shares across brackets, at resolution the winning bracket pays $1
per share and the rest pay $0. So:
    basket cost   = sum(shares_b * avg_cost_b)
    basket EV     = sum(shares_b * P(b))            # expected payout, P(b)=prob b wins
    EV of 1 more share of b bought at its ask = P(b) - ask_b   (positive = +EV buy)
    full-set arb  = sum(ask_b over ALL brackets);  < $1  => riskless profit

P(b) baseline = the market's own YES price (the crowd is better-calibrated than our
models). A seesaw DIP = live ask below the bracket's recent typical price, which is the
+EV moment to accumulate. Pass --count <tweets-so-far> to also show an independent
Kalman model probability as a cross-check.

Usage:
  python ev_pacer.py                          # current 7-day Elon market, full table + arb
  python ev_pacer.py --slug <event-slug>      # a specific market
  python ev_pacer.py --positions pos.json     # pos.json: {"<20": {"shares":1000,"avg":0.005}, ...}
  python ev_pacer.py --dips                    # also flag seesaw dips vs recent price (slower)
"""
import argparse, json, sys, urllib.request, urllib.parse, statistics
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def gget(url, timeout=30):
    r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())


def pick_market(slug):
    evs = gget(f"{GAMMA}/events?tag_id=972&closed=false&limit=500")
    if slug:
        ev = [e for e in evs if e.get("slug") == slug]
        return ev[0] if ev else None
    ev = [e for e in evs if e.get("seriesSlug") == "elon-tweets"]
    return sorted(ev, key=lambda e: e.get("endDate", ""))[0] if ev else None


def bracket_lo(label):
    s = str(label).strip().lstrip("<").rstrip("+")
    try:
        return int(s.split("-")[0])
    except Exception:
        return 0


def recent_price(token):
    """median traded price over the last ~6h (the bracket's 'normal' level)."""
    try:
        h = gget(f"{CLOB}/prices-history?market={token}&interval=6h&fidelity=10")
        ps = [float(x["p"]) for x in h.get("history", []) if 0 < float(x["p"]) < 1]
        return statistics.median(ps) if ps else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=None)
    ap.add_argument("--positions", default=None)
    ap.add_argument("--dips", action="store_true")
    a = ap.parse_args()

    ev = pick_market(a.slug)
    if not ev:
        print("no market found"); return
    pos = {}
    if a.positions:
        pos = json.load(open(a.positions, encoding="utf-8"))

    print(f"\n{ev.get('title')}   (ends {ev.get('endDate')})")
    print(f"{'bracket':<9}{'ask':>7}{'bid':>7}{'mktP':>7}{'buy_EV':>8}{'shares':>8}{'avg':>7}{'unreal':>9}", end="")
    print(f"{'dip?':>7}" if a.dips else "")

    # index EVERY bracket (incl. closed) so held-but-dead brackets are never dropped
    info = {}
    for m in ev.get("markets", []):
        lab = m.get("groupItemTitle", "")
        try:
            op = json.loads(m.get("outcomePrices", "[]"))
            mp = float(op[0]) if op else 0.0           # resolved/last YES prob
        except Exception:
            mp = 0.0
        info[lab] = dict(ask=float(m.get("bestAsk") or 0) or None,
                         bid=float(m.get("bestBid") or 0) or None,
                         mp=mp, closed=bool(m.get("closed")), m=m)
    ask_sum = sum(v["ask"] for v in info.values() if v["ask"] and not v["closed"])
    p_sum = sum(v["mp"] for v in info.values() if not v["closed"])

    # display: open brackets, plus any bracket you hold (even if it has since closed)
    labels = sorted([l for l, v in info.items()
                     if (not v["closed"]) or l in pos or v["mp"] > 0.005], key=bracket_lo)
    for lab in labels:
        v = info[lab]; ask, bid, mp = v["ask"], v["bid"], v["mp"]
        buy_ev = (mp - ask) if ask else float("nan")
        p = pos.get(lab, {}); sh = float(p.get("shares", 0)); avg = float(p.get("avg", 0))
        unreal = sh * (mp - avg) if sh else 0.0
        dip = ""
        if a.dips and mp > 0.03 and not v["closed"]:
            try:
                rp = recent_price(json.loads(v["m"].get("clobTokenIds", "[]"))[0])
            except Exception:
                rp = None
            if rp and ask and ask < rp * 0.9:
                dip = f"-{round(100*(1-ask/rp))}%"
        tag = " (CLOSED)" if v["closed"] else ""
        line = (f"{lab:<9}{('' if ask is None else f'{ask:.3f}'):>7}"
                f"{('' if bid is None else f'{bid:.3f}'):>7}{mp:>7.3f}"
                f"{('' if ask is None else f'{buy_ev:+.3f}'):>8}"
                f"{(f'{sh:.0f}' if sh else ''):>8}{(f'{avg:.3f}' if sh else ''):>7}"
                f"{(f'{unreal:+.2f}' if sh else ''):>9}")
        print(line + (f"{dip:>7}" if a.dips else "") + tag)

    # basket over ALL held labels (held-but-closed counts at its resolved $0/$1)
    basket_cost = sum(float(p.get("avg", 0)) * float(p.get("shares", 0)) for p in pos.values())
    basket_ev = sum(info.get(l, {}).get("mp", 0.0) * float(p.get("shares", 0)) for l, p in pos.items())

    print("-" * (66 + (7 if a.dips else 0)))
    print(f"full-set ask-sum = ${ask_sum:.3f}  (<$1.00 = riskless arb; gap = ${1-ask_sum:+.3f})")
    print(f"YES prob-sum     = {p_sum:.3f}  (sanity, should be ~1.00)")
    if any(pos):
        roi = (100 * (basket_ev / basket_cost - 1)) if basket_cost else 0
        print(f"\nYOUR BASKET: cost ${basket_cost:.2f}  |  expected payout ${basket_ev:.2f}  "
              f"|  EV ${basket_ev - basket_cost:+.2f}  ({roi:+.0f}%)")


if __name__ == "__main__":
    main()
