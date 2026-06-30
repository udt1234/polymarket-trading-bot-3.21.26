"use client"

import { useApi } from "@/lib/hooks"
import { fmtPrice, bracketSortKey, cn } from "@/lib/utils"

// Unified per-bracket market table. Merges price action (price + volume) and
// the order book (best bid/ask in cents + total depth) into ONE box, with light
// dividers separating the metric groups. Full-width on desktop; the table scrolls
// horizontally (swipe) on mobile, with the Bracket column pinned.

interface BookSnapshot {
  bracket: string
  best_bid: number
  best_ask: number
  bid_depth_5: number
  ask_depth_5: number
  spread: number
  midpoint: number
}

interface PriceSeries {
  bracket: string
  price: number
  volume?: number
  snapshot_hour: string
}

interface Row {
  bracket: string
  price: number | null
  volume: number | null
  bid: number | null
  ask: number | null
  totalBid: number | null
  totalAsk: number | null
  spread: number | null
}

function dollars(n: number | null): string {
  if (n == null) return "—"
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${n.toFixed(0)}`
}

function cents(n: number | null): string {
  return n != null ? fmtPrice(n) : "—"
}

export function BracketMetricsTable({ moduleId }: { moduleId: string }) {
  const { data: book } = useApi<{ snapshots: BookSnapshot[] }>(
    moduleId ? `/api/modules/${moduleId}/order-book-depth` : null
  )
  const { data: priceData } = useApi<{ series: PriceSeries[] }>(
    moduleId ? `/api/modules/${moduleId}/price-history?limit=200` : null
  )

  // latest price + volume per bracket
  const pv: Record<string, { price: number; volume: number }> = {}
  for (const r of priceData?.series || []) {
    const prev = pv[r.bracket] as any
    if (!prev || r.snapshot_hour > prev.snapshot_hour) {
      pv[r.bracket] = { price: r.price, volume: r.volume || 0, snapshot_hour: r.snapshot_hour } as any
    }
  }
  const bookByBracket: Record<string, BookSnapshot> = {}
  for (const s of book?.snapshots || []) bookByBracket[s.bracket] = s

  const brackets = Array.from(new Set([...Object.keys(pv), ...Object.keys(bookByBracket)]))
    .sort((a, b) => bracketSortKey(a) - bracketSortKey(b))

  const rows: Row[] = brackets.map((bracket) => {
    const b = bookByBracket[bracket]
    const p = pv[bracket]
    return {
      bracket,
      price: p?.price ?? null,
      volume: p?.volume ?? null,
      bid: b?.best_bid ?? null,
      ask: b?.best_ask ?? null,
      totalBid: b?.bid_depth_5 ?? null,
      totalAsk: b?.ask_depth_5 ?? null,
      spread: b?.spread ?? null,
    }
  })

  const groupBorder = "border-l border-border/60"
  const thBase = "px-3 py-2 text-right font-medium whitespace-nowrap"
  const tdBase = "px-3 py-2 text-right whitespace-nowrap tabular-nums"

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Market — Price, Volume &amp; Order Book
        </h2>
        <span className="text-[10px] text-muted-foreground sm:hidden">swipe →</span>
      </div>
      {rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {/* group header row */}
              <tr className="text-[10px] uppercase tracking-wide text-muted-foreground">
                <th
                  rowSpan={2}
                  className="sticky left-0 z-10 bg-card px-3 py-2 text-left align-bottom"
                >
                  Bracket
                </th>
                <th colSpan={2} className={cn("px-3 py-1 text-center", groupBorder)}>
                  Price Action
                </th>
                <th colSpan={5} className={cn("px-3 py-1 text-center", groupBorder)}>
                  Order Book
                </th>
              </tr>
              {/* column header row */}
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className={cn(thBase, groupBorder)}>Price</th>
                <th className={thBase}>Volume</th>
                <th className={cn(thBase, groupBorder)} title="Best bid price">Bid</th>
                <th className={thBase} title="Best ask price">Ask</th>
                <th className={thBase} title="Total bid depth (top 5 levels)">Total Bid</th>
                <th className={thBase} title="Total ask depth (top 5 levels)">Total Ask</th>
                <th className={thBase} title="Ask − Bid">Spread</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.bracket} className="border-b border-border last:border-0 hover:bg-accent/30">
                  <td className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-medium whitespace-nowrap">
                    {r.bracket}
                  </td>
                  <td className={cn(tdBase, groupBorder)}>{cents(r.price)}</td>
                  <td className={cn(tdBase, "text-muted-foreground")}>{dollars(r.volume)}</td>
                  <td className={cn(tdBase, groupBorder, "text-success")}>{cents(r.bid)}</td>
                  <td className={cn(tdBase, "text-destructive")}>{cents(r.ask)}</td>
                  <td className={cn(tdBase, "text-muted-foreground")}>{dollars(r.totalBid)}</td>
                  <td className={cn(tdBase, "text-muted-foreground")}>{dollars(r.totalAsk)}</td>
                  <td className={tdBase}>{cents(r.spread)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-muted-foreground">
          No market data yet — snapshot job runs every 5 min
        </p>
      )}
    </div>
  )
}
