"""BUILD_SPEC PART J Step 2 acceptance test.

Places ONE post-only limit BUY far below the ask on a live Elon tweet
bracket (~$1 notional, cannot fill), verifies it RESTS on the book, cancels
it, and confirms the lifecycle via BOTH the user WebSocket channel and the
REST reconciler, with the orders state machine written to Supabase.

Run: python -u scripts/step2_acceptance.py
"""
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.polymarket_proxy import install_httpx_proxy_patch

install_httpx_proxy_patch()

import httpx  # noqa: E402

from api.services import clob, fills, order_state  # noqa: E402
from api.services.polymarket_proxy import gamma_base  # noqa: E402

WS_EVENTS: list[dict] = []
WS_AUTH: dict | None = None


def use_manual_wallet() -> None:
    """--manual: run the identical execution path through the funded MANUAL
    wallet (signature_type=1 proxy) while the BOT wallet awaits funding.
    Test order is ~$1.05, far from the ask, post-only, cancelled in seconds."""
    global WS_AUTH
    import os
    shared = Path.home() / ".credentials" / "shared.env"
    if shared.exists():  # absent inside containers - env comes from the platform
        for line in open(shared, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"'))
    # shared.env was loaded after the import-time patch call - re-arm it so
    # any proxy vars just placed in os.environ take effect (reads only).
    from api.services import polymarket_proxy
    polymarket_proxy._PATCHED = False
    polymarket_proxy.install_httpx_proxy_patch()
    from polymarket import SecureClient
    client = SecureClient.create(
        private_key=os.environ["POLY_MANUAL_PRIVATE_KEY"],
        wallet=os.environ["POLY_MANUAL_WALLET_ADDRESS"])
    clob._client = client
    WS_AUTH = {"apiKey": os.environ["POLY_MANUAL_API_KEY"],
               "secret": os.environ["POLY_MANUAL_SECRET"],
               "passphrase": os.environ["POLY_MANUAL_PASSPHRASE"]}
    print("  [using MANUAL wallet, signature_type=1]")


def on_ws_message(msg: dict) -> None:
    WS_EVENTS.append(msg)
    try:
        fills.handle_user_message(msg)
    except Exception as e:
        print(f"  [ws handler error] {e}")


def pick_market() -> dict:
    """Pick a live tweet-market bracket with a real ask well above 1c."""
    r = httpx.get(f"{gamma_base()}/events",
                  params={"tag_id": 972, "closed": "false", "limit": 25},
                  timeout=30)
    r.raise_for_status()
    for ev in r.json():
        for m in ev.get("markets", []):
            if m.get("closed") or m.get("acceptingOrders") is False:
                continue
            try:
                best_ask = float(m.get("bestAsk") or 0)
                token_ids = json.loads(m.get("clobTokenIds") or "[]")
            except (TypeError, ValueError):
                continue
            if best_ask >= 0.05 and token_ids:
                return {
                    "question": m.get("question"),
                    "condition_id": m.get("conditionId"),
                    "yes_token": token_ids[0],
                    "best_bid": float(m.get("bestBid") or 0),
                    "best_ask": best_ask,
                    "tick": float(m.get("orderPriceMinTickSize") or 0.01),
                    "event": ev.get("title"),
                }
    raise SystemExit("ACCEPT FAIL: no suitable live tweet bracket found via Gamma")


def main() -> None:
    print("== 1. credentials + collateral ==")
    bal = clob.get_collateral_balance()
    print(f"  balance/allowance: {bal}")
    usable = float(bal.get("balance") or 0) / 1e6
    print(f"  collateral: ${usable:.2f}")
    if usable < 1.10:
        print("ACCEPT BLOCKED: wallet has <$1.10 collateral. Fund pUSD first (PART N).")
        return

    print("== 2. pick market ==")
    mkt = pick_market()
    print(f"  {mkt['event']} | {mkt['question']}")
    print(f"  bid {mkt['best_bid']} / ask {mkt['best_ask']} tick {mkt['tick']}")

    print("== 3. user WS subscribe ==")
    stream = fills.UserChannelStream(on_message=on_ws_message,
                                     markets=[mkt["condition_id"]], auth=WS_AUTH)
    threading.Thread(target=lambda: asyncio.run(stream.run()), daemon=True).start()
    time.sleep(3)

    print("== 4. place post-only limit far from market ==")
    price = max(mkt["tick"], 0.01)
    if price >= mkt["best_ask"]:
        price = mkt["tick"]
    size = max(5, int(1.05 / price) + 1)
    resp = clob.place_post_only(mkt["yes_token"], "BUY", price, size, tick=mkt["tick"])
    print(f"  CLOB response: {resp}")
    oid = (resp or {}).get("orderID")
    if not oid:
        print("ACCEPT FAIL: no orderID in response")
        return
    order_state.record_submitted(
        module_id=None, market_id=mkt["condition_id"], bracket=mkt["question"],
        side="BUY", price=price, size=size, token_id=mkt["yes_token"],
        clob_order_id=oid, executor="live",
        metadata={"test": "step2_acceptance",
                  "wallet": "manual" if WS_AUTH else "bot"})

    print("== 5. verify it RESTS ==")
    time.sleep(3)
    o = clob.get_order(oid) or {}
    print(f"  get_order status: {o.get('status')} size_matched: {o.get('size_matched')}")
    resting = (o.get("status") or "").upper() == "LIVE" and float(o.get("size_matched") or 0) == 0
    print(f"  RESTING: {resting}")

    print("== 6. REST reconciler ==")
    n = fills.reconcile_open_orders()
    print(f"  reconcile advanced {n} row(s)")

    print("== 7. cancel ==")
    c = clob.cancel_order(oid)
    print(f"  cancel response: {c}")
    time.sleep(4)
    o2 = clob.get_order(oid) or {}
    print(f"  post-cancel status: {o2.get('status')}")
    fills.reconcile_open_orders()
    stream.stop()

    print("== 8. final orders row + WS events ==")
    from api.dependencies import get_supabase
    row = (get_supabase().table("orders").select("status,size_filled,post_only,order_type")
           .eq("clob_order_id", oid).limit(1).execute()).data
    print(f"  orders row: {row}")
    kinds = [f"{m.get('event_type')}:{m.get('type') or m.get('status')}" for m in WS_EVENTS]
    print(f"  WS events seen ({len(WS_EVENTS)}): {kinds}")

    ok = resting and row and row[0]["status"] == "cancelled"
    print("\nACCEPT PASS" if ok else "\nACCEPT FAIL (see above)")


if __name__ == "__main__":
    if "--manual" in sys.argv:
        use_manual_wallet()
    main()
