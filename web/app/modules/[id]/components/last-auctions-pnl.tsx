"use client"

import { cn, formatCurrency, formatDateShort } from "@/lib/utils"
import { TrendingUp, TrendingDown } from "lucide-react"

interface Auction { tracking_id: string; start_date: string; end_date: string; status: string; market_link?: string; market_ids?: string[] }
interface WalletAuction { slug?: string; end_date?: string; total_pnl?: number; bid_count?: number; status?: string; bids?: any[] }
interface PaperPosition { market_id?: string; bracket: string; size: number; avg_price: number; status: string; realized_pnl?: number; unrealized_pnl?: number }

export function LastAuctionsPnl({
  auctions,
  walletAuctions,
  paperPositions,
  marketPrices,
}: {
  auctions: Auction[]
  walletAuctions: WalletAuction[]
  paperPositions?: PaperPosition[]
  marketPrices?: Record<string, number>
}) {
  const pastAucs = (auctions || [])
    .filter((a) => a.status === "past")
    .sort((a, b) => b.end_date.localeCompare(a.end_date))
    .slice(0, 3)

  if (pastAucs.length === 0) return null

  const enriched = pastAucs.map((a) => {
    const aSlug = a.market_link?.split("/").pop()?.toLowerCase() || ""
    const walletAuc = (walletAuctions || []).find((wa: any) => {
      const waSlug = (wa.slug || "").toLowerCase()
      if (aSlug && waSlug === aSlug) return true
      if ((wa.end_date || "").slice(0, 10) === a.end_date) return true
      return false
    })
    // Real-wallet path (live mode)
    let pnl = walletAuc?.total_pnl ?? 0
    let bidCount = walletAuc?.bid_count ?? 0
    let totalCost = (walletAuc?.bids || []).reduce(
      (s: number, b: any) => s + (b.cost || b.size * (b.price || 0)),
      0,
    )
    const winBid = walletAuc?.bids?.find((b: any) => (b.pnl || 0) > 0)
    let winBracket = winBid?.outcome || winBid?.title?.match(/\d+-\d+|\d+\+/)?.[0] || ""
    let hadTrades = walletAuc && bidCount > 0

    // Paper-mode fallback: when there's no wallet auction match, scan paper
    // positions whose market_id is in this auction's market_ids. The backend
    // join uses market.endDate matching tracking.endDate (not signal-window),
    // so each market_id belongs to exactly one auction.
    if (!hadTrades && a.market_ids && a.market_ids.length > 0 && paperPositions) {
      const mySet = new Set(a.market_ids.map(String))
      const myPos = paperPositions.filter((p) => mySet.has(String(p.market_id)))
      if (myPos.length > 0) {
        hadTrades = true
        bidCount = myPos.length
        totalCost = myPos.reduce((s, p) => s + (p.size || 0) * (p.avg_price || 0), 0)
        // P&L: prefer realized when position is closed, otherwise mark-to-market
        // using the live market_prices passed in from pacing.
        pnl = myPos.reduce((s, p) => {
          const realized = p.realized_pnl || 0
          if (p.status !== "open") return s + realized
          const mark = (marketPrices && marketPrices[p.bracket]) ?? p.avg_price
          const unrealized = (mark - p.avg_price) * (p.size || 0)
          return s + realized + unrealized
        }, 0)
      }
    }
    return { auction: a, pnl, bidCount, totalCost, winBracket, hadTrades }
  })

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {enriched.map(({ auction, pnl, bidCount, totalCost, winBracket, hadTrades }) => {
        const isPositive = pnl >= 0
        // formatDateShort appends T00:00:00 so JS parses dates as LOCAL midnight
        // instead of UTC midnight — without this, '2026-05-07' renders as 'May 6'
        // for any user east of UTC.
        const label = `${formatDateShort(auction.start_date)} → ${formatDateShort(auction.end_date)}`
        return (
          <div key={auction.tracking_id} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">{label}</p>
              {hadTrades && (
                <div className={cn("flex items-center gap-0.5 text-xs", isPositive ? "text-success" : "text-destructive")}>
                  {isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                </div>
              )}
            </div>
            {hadTrades ? (
              <>
                <p className={cn("text-3xl font-bold", isPositive ? "text-success" : "text-destructive")}>
                  {isPositive ? "+" : ""}{formatCurrency(pnl)}
                </p>
                <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                  <p>{bidCount} bet{bidCount !== 1 ? "s" : ""} · ${Math.round(totalCost)} cost</p>
                  {winBracket && <p>Winner: <span className="text-foreground font-medium">{winBracket}</span></p>}
                </div>
              </>
            ) : (
              <>
                <p className="text-2xl font-bold text-muted-foreground">No bets</p>
                {winBracket && <p className="mt-2 text-xs text-muted-foreground">Winner: <span className="text-foreground">{winBracket}</span></p>}
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
