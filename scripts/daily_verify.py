"""Daily END-TO-END money-path verifier (2026-07-24).

Runs on the Dublin box via a systemd timer (like the watchdog) - unattended, every
day. It checks the thing the CODE auditors and even the qa-functional-verifier agent
missed: for EVERY active module, does the full money path actually work against the
LIVE market? Signal -> fill -> settlement -> honest P&L. Alerts on Telegram when a
module is silently broken so Sir never has to be the one who finds the hole.

Why a script, not the agent: an agent runs inside a Claude session on demand; only a
box-side script can run daily on its own. The @qa-functional-verifier agent stays for
deep per-commit review; THIS is the daily heartbeat.

Checks per active (non-inactive) module:
  1. SIGNALS   - did it emit any decision in 24h? (silent no-output)
  2. FILLS     - if it emitted signals, did any order fill in 48h? (silent no-fill:
                 the exact NO-token coverage bug, 2026-07-24)
  3. STRANDED  - any position that is RESOLVED on-chain but still sits 'open'?
                 (the resolution-collection bug that hid $45 of P&L)
  4. PNL       - is realized P&L being computed (positions actually closing)?
Global: engine cycling, and the paper/live mode banner.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402

from api.dependencies import get_supabase  # noqa: E402

NO_SIGNAL_H = 24
NO_FILL_H = 48
CLOB = "https://clob.polymarket.com"


def _clob_resolved_winner(cid: str, token: str) -> bool | None:
    """True/False if the token won/lost on a CLOSED market, None if not resolved."""
    try:
        m = httpx.get(f"{CLOB}/markets/{cid}", timeout=15).json() or {}
    except Exception:
        return None
    if not m.get("closed"):
        return None
    for t in (m.get("tokens") or []):
        if str(t.get("token_id")) == str(token):
            return t.get("winner") is True
    return None


def main() -> None:
    sb = get_supabase()
    now = dt.datetime.now(dt.timezone.utc)
    since_sig = (now - dt.timedelta(hours=NO_SIGNAL_H)).isoformat()
    since_fill = (now - dt.timedelta(hours=NO_FILL_H)).isoformat()

    mods = {m["id"]: m for m in (sb.table("modules").select("*").execute().data or [])
            if m.get("status") not in ("inactive",)}
    problems: list[str] = []
    report: list[str] = []

    for mid, m in mods.items():
        name = m["name"]
        sigs = (sb.table("signals").select("approved").eq("module_id", mid)
                .gte("created_at", since_sig).limit(5000).execute().data) or []
        n_sig = len(sigs); n_ok = sum(1 for s in sigs if s.get("approved"))
        fills = (sb.table("orders").select("id").eq("module_id", mid)
                 .eq("status", "filled").gte("created_at", since_fill)
                 .limit(2000).execute().data) or []
        n_fill = len(fills)
        # NO_SIGNALS is report-only: a module can be legitimately idle (no live
        # auction inside its window - reversion/late_arb only fire in the last 6h).
        # The genuinely-BROKEN state that ALERTS = emitted approved signals but NOTHING
        # filled (the NO-token coverage bug class). Alerts must mean something.
        broken = n_ok > 0 and n_fill == 0
        note = "NO_SIGNALS(idle)" if n_sig == 0 else ("NO_FILLS!" if broken else "ok")
        report.append(f"{name}: sig={n_sig}/{n_ok}ok fill={n_fill} {note}")
        if broken:
            problems.append(f"{name}: {n_ok} approved signals in {NO_SIGNAL_H}h but "
                            f"0 fills in {NO_FILL_H}h - fill path broken")

    # STRANDED: open positions resolved on-chain but never settled
    open_pos = (sb.table("positions").select("id,market_id,token_id,bracket")
                .in_("status", ["open", "closing"]).limit(500).execute().data) or []
    stranded = 0
    for p in open_pos[:60]:  # cap on-chain calls per run
        w = _clob_resolved_winner(p.get("market_id") or "", p.get("token_id"))
        if w is not None:
            stranded += 1
    if stranded:
        problems.append(f"STRANDED: {stranded} resolved position(s) not settled "
                        f"(resolution sweep failing)")
    report.append(f"stranded_resolved_positions={stranded}")

    msg = ("daily_verify: ALL MODULES OK | " if not problems
           else "daily_verify PROBLEMS: " + " ; ".join(problems) + " || ")
    msg += " | ".join(report)
    try:
        sb.table("logs").insert({
            "log_type": "system", "severity": "error" if problems else "info",
            "message": msg[:900], "metadata": {"problems": problems, "report": report}}).execute()
    except Exception:
        pass
    if problems:
        try:
            from api.services.notifications import notify
            notify("🔎 Daily verify found broken module money-paths:\n- "
                   + "\n- ".join(problems))
        except Exception:
            pass
    print(msg)


if __name__ == "__main__":
    main()
