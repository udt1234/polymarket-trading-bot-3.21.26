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


# --- Whale Watching headline (Phase 2) ---


def _wallet_short(addr: str) -> str:
    if not addr or len(addr) < 10:
        return addr or ""
    return addr[:6] + "..." + addr[-4:]


def _compute_whale_pricing(
    grid_metrics: list[dict],
    breakdown: dict,
) -> tuple[float | None, float | None]:
    """Derive (target_bid, skip_offer_above) from the grid.

    target_bid: the median entry price of the lowest-priced active archetype
        (excluding tail_punter which is structural noise) — i.e. where the
        smart cheap-entry crowd is buying.
    skip_offer_above: median Market-Maker offer ≈ their median entry price,
        the resistance level we shouldn't cross.
    """
    target = None
    by_arch = {g["archetype"]: g for g in grid_metrics}
    # Prefer spike_trader's median entry (the profitable cheap-entry crowd).
    # NEVER fall back to pace_chaser — that cohort loses -30% to -80% per
    # spec; recommending their price would point the user at a losing entry.
    for k in ("spike_trader", "tail_scooper"):
        g = by_arch.get(k)
        if g and g.get("median_entry_price") is not None and (g.get("fills_count") or 0) > 0:
            target = round(float(g["median_entry_price"]), 2)
            break
    mm = by_arch.get("market_maker") or {}
    skip = None
    if mm.get("median_entry_price") is not None and (mm.get("fills_count") or 0) > 0:
        skip = round(float(mm["median_entry_price"]), 2)
    return target, skip


def render_whale_headline(
    breakdown: dict,
    top_wallets: list[dict],
    grid_metrics: list[dict],
    n_auctions: int,
    bot_wallet: str | None,
    data_quality: str,
    last_auction_top_wallet_dollars: float | None = None,
    last_auction_total_dollars: float | None = None,
    same_archetype_roi_avg: float | None = None,
    last_top_wallet_obj: dict | None = None,
) -> list[str]:
    """Plain-English headline for the 🐋 Whale Watching card.

    Spec: WHALE_BRACKET_CARDS_SPEC.md lines 87-152. Up to 5 lines. The
    last 1-2 lines are always action arrows ("→ Bid $X.XX..."). Rules
    are scored by priority and the top 2-3 non-arrow rules fire."""
    if data_quality == "insufficient":
        return ["Not enough data yet — keep current strategy."]

    lines: list[str] = []
    fired: list[tuple[int, str]] = []

    # Rule 2: Single wallet drove >25% of last-auction $. Cite the actual
    # most-recent-snapshot top wallet, not the aggregated-window top wallet.
    if (
        last_auction_top_wallet_dollars is not None
        and last_auction_total_dollars
        and last_auction_total_dollars > 0
        and last_auction_top_wallet_dollars / last_auction_total_dollars > 0.25
        and last_top_wallet_obj
    ):
        pct = round(100 * last_auction_top_wallet_dollars / last_auction_total_dollars)
        if pct <= 100:
            short = last_top_wallet_obj.get("wallet_short") or _wallet_short(
                last_top_wallet_obj.get("wallet") or ""
            )
            fired.append((
                2,
                f"Wallet {short} drove {pct}% of last auction "
                f"(${int(last_auction_top_wallet_dollars):,}). Track this address."
            ))

    # Rule 3: Market-Maker concentration >50% of total $
    mm = breakdown.get("market_maker") or {}
    if mm.get("share", 0) > 0.50:
        mm_grid = next((g for g in grid_metrics if g["archetype"] == "market_maker"), {})
        mm_px = mm_grid.get("median_entry_price")
        if mm_px is not None:
            fired.append((
                3,
                f"Market-Makers control {int(mm.get('share', 0) * 100)}% of the market. "
                f"Don't lift offers above ${float(mm_px):.2f} (median MM offer)."
            ))
        else:
            fired.append((
                3,
                f"Market-Makers control {int(mm.get('share', 0) * 100)}% of the market."
            ))

    # Rule 4 / 5: Same archetype (Spike Trader) profitable/losing in last 5
    if same_archetype_roi_avg is not None:
        if same_archetype_roi_avg > 0:
            fired.append((
                4,
                f"Spike Traders averaged +${int(round(same_archetype_roi_avg))}/auction. "
                f"Your strategy is in a working regime."
            ))
        else:
            fired.append((
                5,
                f"Spike Traders lost ${int(round(abs(same_archetype_roi_avg)))}/auction over last "
                f"{n_auctions}. Tighten entry threshold."
            ))

    # Rule 6: New whale appeared (first sighting, ≥$1k notional). Use
    # `auctions_seen` from top_wallets meta when available.
    for w in top_wallets[:5]:
        seen = w.get("auctions_seen")
        flowed = w.get("dollars_flowed", 0) or 0
        if seen is not None and seen <= 1 and flowed >= 1000:
            fired.append((
                6,
                f"New entrant {w['wallet_short']} deployed ${int(flowed):,}. First sighting."
            ))
            break

    # Rule 7: Pace Chaser cohort active (≥2 in last auction)
    pc_wallets = [w for w in top_wallets if w.get("archetype") == "pace_chaser"]
    if len(pc_wallets) >= 2:
        fired.append((
            7,
            f"{len(pc_wallets)} Pace Chasers active. Bid early to catch their late-window unwinds."
        ))

    # Rule 8: Tail Punter $ flow >15%
    tp_share = (breakdown.get("tail_punter") or {}).get("share", 0)
    if tp_share > 0.15:
        tp_dollars = (breakdown.get("tail_punter") or {}).get("dollars", 0)
        fired.append((
            8,
            f"Tail Punters putting ${int(tp_dollars):,} into long-tail buckets. "
            f"Avoid those buckets."
        ))

    # Sort by priority (lower = higher priority) and take top 3
    fired.sort(key=lambda x: x[0])
    for _, sentence in fired[:3]:
        lines.append(sentence)

    # Always-last: target bid + skip line
    target_bid, skip_above = _compute_whale_pricing(grid_metrics, breakdown)
    if target_bid is not None and skip_above is not None and skip_above > target_bid:
        lines.append(
            f"→ Bid ${target_bid:.2f} on modal bucket early. Skip offers above ${skip_above:.2f}."
        )
    elif target_bid is not None:
        lines.append(f"→ Bid ${target_bid:.2f} on modal bucket early.")
    else:
        lines.append("→ No clear price signal — wait for early-window quotes.")

    # Optional second arrow: identify a specific Spike Trader entry
    if bot_wallet:
        for w in top_wallets[:5]:
            if w.get("archetype") == "spike_trader" and not w.get("is_us"):
                # Use the grid's spike_trader median price as their entry signal
                st_grid = next((g for g in grid_metrics if g["archetype"] == "spike_trader"), {})
                st_px = st_grid.get("median_entry_price")
                if st_px is not None:
                    undercut = max(0.01, round(float(st_px) - 0.01, 2))
                    lines.append(
                        f"→ Spike Trader {w['wallet_short']} typical entry ~${float(st_px):.2f} — "
                        f"undercut at ${undercut:.2f}."
                    )
                    break

    if len(lines) == 1:
        lines.insert(0, "Mixed archetype landscape. No single cohort dominating yet.")

    return lines[:5]
