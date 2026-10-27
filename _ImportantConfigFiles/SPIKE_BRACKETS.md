# SPIKE TRADING: Bracket Recommendations (parquet-validated 2026-05-06)

Moved from CLAUDE.md on 2026-10-27. CLAUDE.md keeps a pointer to this file.

**When user asks "which brackets should Spike trade" or any variant, ALWAYS surface this first.**

Source: `_DataMetricPulls/elon_arc_analysis/arc_brief.md` + `arc_2day.csv` (n=51-54 per bracket, full SII-WANGZJ parquet, Sep 2025 → May 2026).

## 2-day arc-tradeable brackets (buy-low-sell-high reliability)

Ranked by `pct_arc_5to30` = % of auctions where bracket BOTH crashed ≤5¢ AND spiked ≥30¢ at some point. Higher = more reliable trading swing.

| Rank | Bracket | N | Median peak | Arc 5→30 | Strategy fit |
|---|---|---|---|---|---|
| 1 | **65-89** | 51 | 59¢ | **76.5%** | Best range-trading target |
| 2 | **90-114** | 51 | 45¢ | **64.7%** | Second-best range-trade |
| 3 | **40-64** | 51 | 51¢ | **56.9%** | Volatile, occasional YES winner |
| 4 | 115-139 | 51 | 38¢ | 45.1% | Marginal |
| 5 | `<40` | 54 | 20.5¢ | 37.0% | **Lottery-ticket only: current Spike target** |

## Strategy match
- **Spike Trading (current)** uses `<40` for structural lottery-ticket entries (5-tier ladder 0.3¢→12¢). This is a HOLD-TO-RESOLUTION strategy. It is the WORST arc bracket but the BEST cheap-entry bracket.
- **Range trading (not yet built)** would target `65-89` / `90-114` / `40-64`. Different strategy: buy ≤5¢, sell laddered at 30¢/50¢/median-peak. ~half day to build a new module.

## Monthly arc winners (n=5-6, weaker statistical confidence)
- **1400+**: 60% arc, 98.7¢ median peak, wins YES half the time. Standout monthly bracket.
- 1080-1119, 1120-1159, 1200-1239: ~50% arc reliability each.

## Strategic backstop
- `<40` 12¢ floor hits 100% of historical 2-day auctions. 0.5¢ floor hits 96%. The 5-tier ladder Spike uses (0.3¢/0.5¢/2¢/5¢/12¢) is calibrated to capture maximum shares at the cheapest tiers patiently.
- DO NOT recommend a single-floor entry; the ladder is intentional.
- DO NOT recommend changing Spike to range-trading: that's a separate module if user wants it.

**Reminder:** when this section is consulted, also remind the user the data window is Sep 2025 → May 2026 (~8 months for 2-day brackets). Earlier history is unavailable in parquet.
