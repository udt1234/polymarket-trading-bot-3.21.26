"""Deterministic headline-rule engine for the Bracket Analysis card.

Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md (sections "Headlines"
and "Headline rule tables"). Phase 1: bracket rules. Phase 2: whale rules.

Rules are evaluated in priority order. The "always first" rule emits the
performance summary header. Up to 3 additional rules fire to fill the
headline. Output is a list of plain-English sentences ready to render.

NO LLM. Pure templates.
"""
from __future__ import annotations
from typing import Literal


def render_bracket_headline(
    rows: list[dict],
    comparison: list[dict],
    allocation: dict,
    mode: Literal["spike_only", "all_signals"],
    n_auctions: int,
    data_quality: str,
    window_label: str = "last_10",
) -> list[str]:
    """Return 1-5 plain-English headline lines for the Bracket Analysis card."""
    if data_quality == "insufficient":
        return ["Not enough data yet — keep current strategy."]

    # Always-first: performance summary
    total_signals = sum(r.get("signals_count", 0) for r in rows)
    total_trades = sum(r.get("trades_count", 0) for r in rows)
    mode_label = "Spike-triggered" if mode == "spike_only" else "All signals"

    # Bot-specific win rate: only count brackets the bot actually traded.
    bot_traded_rows = [r for r in rows if (r.get("trades_count") or 0) > 0]
    bot_wins = sum(r.get("won_count", 0) for r in bot_traded_rows)
    bot_events = sum(r.get("events_count", 0) for r in bot_traded_rows)
    bot_win_pct = round((bot_wins / bot_events) * 100) if bot_events else 0

    if total_trades > 0 and bot_events > 0:
        header = (
            f"{mode_label}: {total_trades} trades across {n_auctions} auctions "
            f"({bot_wins}/{bot_events} bracket events won, {bot_win_pct}%)."
        )
    elif n_auctions > 0:
        header = (
            f"{mode_label}: 0 trades across {n_auctions} resolved auctions yet."
        )
    else:
        header = f"{mode_label}: no resolved auctions in window yet."

    lines = [header]

    # Rule 1: All brackets EV<0 in window
    if rows and all((r.get("ev_per_trade_usd") or 0) <= 0 for r in rows) and total_trades >= 3:
        lines.append("→ No profitable bracket in this window. Pause this module.")
        return lines[:5]

    fired = []

    # Rule 2: Single bracket win% >65 AND trade share <20 AND n>=10
    for r in rows:
        if (r.get("win_rate_pct") or 0) >= 65 and (r.get("trade_share_pct") or 0) < 20 and (r.get("signals_count") or 0) >= 10:
            alloc_pct = allocation.get(r["bracket"], 0)
            fired.append((
                "rule_winner",
                f"→ Bracket {r['bracket']} wins {int(r['win_rate_pct'])}% ({r['won_count']}/{r['events_count']}). "
                f"You traded it {r['trades_count']} times. Move {alloc_pct}% of next auction's budget here."
            ))
            break

    # Rule 3: Single bracket EV<0 AND traded >5 times in window
    for r in rows:
        if (r.get("ev_per_trade_usd") or 0) < 0 and (r.get("trades_count") or 0) > 5:
            saving = abs(round((r.get("ev_per_trade_usd") or 0) * (r.get("trades_count") or 0)))
            fired.append((
                "rule_stop",
                f"→ Bracket {r['bracket']} has lost ~${saving} over {r['trades_count']} trades. "
                f"Stop trading. Save ~${saving} per window."
            ))
            break

    # Rule 4: Recent vs all-time delta <= -15pt for any bracket
    for c in comparison:
        if c.get("delta_pt", 0) <= -15:
            fired.append((
                "rule_regime",
                f"→ Bracket {c['bracket']} used to win {int(c['all_time_win_pct'])}%, now wins {int(c['last_window_win_pct'])}%. Regime shift."
            ))
            break

    # Rule 5: Spike-triggered count <3 in last 10 (only when in spike mode)
    if mode == "spike_only" and total_trades < 3 and n_auctions >= 5:
        fired.append((
            "rule_trigger_tight",
            f"→ Spike detection fired only {total_trades} times in {n_auctions} auctions. Trigger may be too tight."
        ))

    # Take top 3 fired rules
    for _, sentence in fired[:3]:
        lines.append(sentence)

    # If we still have nothing actionable, give a generic next-step
    if len(lines) == 1 and rows:
        best = max(rows, key=lambda r: r.get("ev_per_trade_usd") or -9999)
        if (best.get("ev_per_trade_usd") or 0) > 0:
            alloc_pct = allocation.get(best["bracket"], 0)
            lines.append(
                f"→ Best bracket so far: {best['bracket']} at +${best['ev_per_trade_usd']}/trade. "
                f"Allocation suggests {alloc_pct}% of next auction."
            )

    return lines[:5]
