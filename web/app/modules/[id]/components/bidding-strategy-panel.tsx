"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, BookOpen } from "lucide-react"

interface BiddingStrategyPanelProps {
  config: Record<string, any> | null
  moduleName?: string
}

/**
 * Plain-English step-by-step explanation of how the bot bids and sells.
 * Reflects the LIVE config values so when the user edits Configuration,
 * this panel updates with them.
 *
 * Currently scoped to spike-style structural strategies. Ensemble modules
 * (Trump/Elon) keep their inline "How this bot works" block in the
 * legacy config UI.
 */
export function BiddingStrategyPanel({ config }: BiddingStrategyPanelProps) {
  const [open, setOpen] = useState(false)

  // Pull live config values with safe defaults so the panel works even
  // before the schema fetch resolves.
  const cfg = config || {}
  const handle = cfg.handle ?? "elonmusk"
  const platform = cfg.platform ?? "x"
  const windowDays = cfg.window_days ?? 2
  const bracket = cfg.bracket_pattern ?? "<40"
  const seriesSlug = cfg.series_slug ?? "elon-tweets-48h"
  const buy1Price = cfg.buy_tier_1_price ?? 0.12
  const buy1Pct = cfg.buy_tier_1_pct ?? 0.5
  const buy2Price = cfg.buy_tier_2_price ?? 0.005
  const buy2Pct = cfg.buy_tier_2_pct ?? 0.5
  const buyCancelHrs = cfg.buy_cancel_after_hours ?? 24
  const sellMults = Array.isArray(cfg.sell_multipliers) ? cfg.sell_multipliers : [1.5, 2.0, 4.0, 8.0]
  const sellPcts = Array.isArray(cfg.sell_multiplier_pcts) ? cfg.sell_multiplier_pcts : [0.3, 0.3, 0.2, 0.2]
  const takeProfit = cfg.take_profit_pct ?? 7.0
  const stopLoss = cfg.stop_loss_pct ?? 0.85
  const trailingStop = cfg.trailing_stop_pct ?? 0.30
  const holdMaxTweets = cfg.hold_max_tweets ?? 5
  const holdMinHours = cfg.hold_min_hours_remaining ?? 24
  const sellnowGrid = Array.isArray(cfg.sellnow_grid) ? cfg.sellnow_grid : [[16, 24], [20, 18], [30, 0]]
  const bracketMax = cfg.bracket_max_count ?? 40
  const pacingSell = cfg.pacing_sell_score ?? 1.20
  const pacingHold = cfg.pacing_hold_score ?? 0.30
  const bracketCap = cfg.bracket_cap_pct_of_bankroll ?? 0.05
  const maxOpen = cfg.max_open_positions ?? 3

  // Helpers
  const cents = (p: number) => `${(p * 100).toFixed(p < 0.01 ? 2 : 1)}¢`
  const pct = (p: number) => `${(p * 100).toFixed(0)}%`

  // Compute absolute sell prices from multipliers × tier-1 buy price
  // (rough preview — actual ladder uses real fill price)
  const sellPreview = sellMults.map((m: number) => Math.min(buy1Price * m, 0.99))

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-6 py-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground hover:bg-accent/50"
      >
        <span className="flex items-center gap-2">
          <BookOpen className="h-4 w-4" />
          Bidding Strategy
        </span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>
      {open && (
        <div className="border-t border-border px-6 py-4 space-y-4 text-xs leading-relaxed text-muted-foreground">
          <p className="text-foreground">
            Plain-English walkthrough of what the bot does, in order. Numbers update live as you edit Configuration.
          </p>

          <Step n={1} title={`Discover live auctions (every 5 min)`}>
            Query Polymarket Series API for <code className="rounded bg-muted px-1">{seriesSlug}</code>.
            Filter to <strong>{windowDays}-day</strong> windows. xTracker fallback runs if the Series API is down.
            Tracks <strong>@{handle}</strong> on <strong>{platform}</strong>.
          </Step>

          <Step n={2} title="Skip auctions that don't qualify">
            For each live auction, fetch the <code className="rounded bg-muted px-1">{bracket}</code> market.
            Skip if: max open positions ({maxOpen}) hit, auction more than {buyCancelHrs}h past its open
            (too late to enter), or BUY orders already in flight on this market.
          </Step>

          <Step n={3} title="Place buy ladder (limit orders)">
            Open a tracked position and emit two BUY signals:
            <ul className="mt-1 ml-4 list-disc space-y-0.5">
              <li>
                <strong>Tier 1</strong>: limit BUY at <strong>{cents(buy1Price)}</strong>
                {" "}— <strong>{pct(buy1Pct * bracketCap)}</strong> of bankroll ({pct(buy1Pct)} of the {pct(bracketCap)} per-cycle cap).
                Adaptive: if the market's ask is already at or below {cents(buy1Price)}, jump the queue at <code>ask − 0.001</code>.
              </li>
              <li>
                <strong>Tier 2</strong>: limit BUY at <strong>{cents(buy2Price)}</strong>
                {" "}— <strong>{pct(buy2Pct * bracketCap)}</strong> of bankroll. The "scoop" tier if the bracket crashes.
              </li>
            </ul>
          </Step>

          <Step n={4} title="Risk gate (per signal)">
            Risk manager runs all checks. Spike opts out of edge / spread / liquidity / EV checks
            via <code className="rounded bg-muted px-1">skip_edge_check=true</code> (it's a structural lottery-ticket bet, not edge-driven).
            Circuit breaker, kelly cap, daily/weekly loss caps still apply.
          </Step>

          <Step n={5} title="Wait for fills">
            Limit orders sit on the book. Spike orders are exempt from the global 5-min stale-order sweep —
            they get a {buyCancelHrs}h TTL instead. If price never drops to your tier, the limit expires unfilled.
          </Step>

          <Step n={6} title="When a position is open: classify state every 5 min">
            Compute pacing score = <code>projected_final_tweets / {bracketMax}</code> via linear extrapolation.
            <ul className="mt-1 ml-4 list-disc space-y-0.5">
              <li><strong>SELL-NOW</strong> if pacing_score ≥ {pacingSell.toFixed(2)} <em>and</em> at least 20% of window elapsed (clear bracket-bust trajectory)</li>
              <li><strong>SELL-NOW</strong> if any cell in the grid matches:
                {sellnowGrid.map((row: any, i: number) => Array.isArray(row) ? (
                  <span key={i} className="ml-1">[≥{row[0]} tweets &amp; ≥{row[1]}h left]{i < sellnowGrid.length - 1 ? "," : ""}</span>
                ) : null)}
              </li>
              <li><strong>HOLD</strong> if ≤{holdMaxTweets} tweets AND ≥{holdMinHours}h left (clean lottery-ticket setup, ride it)</li>
              <li><strong>HOLD-LIGHT</strong> if pacing_score ≤ {pacingHold.toFixed(2)} (soft hold — bracket clearly NOT busting)</li>
              <li><strong>SELL</strong> default — let limit-sell ladder fill organically</li>
            </ul>
          </Step>

          <Step n={7} title="Sell ladder (multipliers of fill price)">
            On fill, the ladder multipliers determine sell tiers (preview shown for {cents(buy1Price)} entry):
            <ul className="mt-1 ml-4 list-disc space-y-0.5">
              {sellMults.map((m: number, i: number) => (
                <li key={i}>
                  <strong>Tier {i + 1}</strong>: sell {pct(sellPcts[i] ?? 0)} at {m}× entry → {cents(sellPreview[i])}
                </li>
              ))}
            </ul>
          </Step>

          <Step n={8} title="Auto-exit thresholds (exit_manager)">
            Independent of the classifier, the position-level exit manager fires when:
            <ul className="mt-1 ml-4 list-disc space-y-0.5">
              <li><strong>Take profit</strong>: price ≥ {(1 + takeProfit).toFixed(1)}× entry ({pct(takeProfit)} gain)</li>
              <li><strong>Stop loss</strong>: price ≤ {((1 - stopLoss) * 100).toFixed(0)}% of entry ({pct(stopLoss)} drawdown)</li>
              <li><strong>Trailing stop</strong>: once up &gt;50%, trail {pct(trailingStop)} below the running peak</li>
            </ul>
          </Step>

          <Step n={9} title="If SELL-NOW fires but bid book is empty">
            Slow-bleed exit: post a SELL limit a tick under the bid (or at <code>0.01 × hours_remaining/24</code> if no bid).
            Each cycle the price walks lower until we fill or the auction closes. <strong>No manual intervention.</strong>
          </Step>

          <Step n={10} title="Resolution">
            When the auction settles, resolution tracker (every 30 min) marks any remaining position closed.
            P&amp;L locks in. Spike's bet is <em>asymmetric</em>: ~96% of {bracket} auctions die at ≤0.5¢
            (your stop loss handles those); ~2% resolve YES at $1 (the {sellMults[sellMults.length - 1]}× moonshot tier captures these).
          </Step>
        </div>
      )}
    </div>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="border-l-2 border-border pl-3">
      <p className="font-semibold text-foreground">
        <span className="text-muted-foreground">{n}.</span> {title}
      </p>
      <div className="mt-1 text-xs">{children}</div>
    </div>
  )
}
