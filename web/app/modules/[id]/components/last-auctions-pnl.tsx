"use client"

import { cn, formatCurrency } from "@/lib/utils"
import { TrendingUp, TrendingDown } from "lucide-react"

interface Auction { tracking_id: string; start_date: string; end_date: string; status: string; market_link?: string }
interface WalletAuction { slug?: string; end_date?: string; total_pnl?: number; bid_count?: number; status?: string; bids?: any[] }

export function LastAuctionsPnl({ auctions, walletAuctions }: { auctions: Auction[]; walletAuctions: WalletAuction[] }) {
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
    const pnl = walletAuc?.total_pnl ?? 0
    const bidCount = walletAuc?.bid_count ?? 0
    const totalCost = (walletAuc?.bids || []).reduce((s: number, b: any) => s + (b.cost || b.size * (b.price || 0)), 0)
    const winBid = walletAuc?.bids?.find((b: any) => (b.pnl || 0) > 0)
    const winBracket = winBid?.outcome || winBid?.title?.match(/\d+-\d+|\d+\+/)?.[0] || ""
    const hadTrades = walletAuc && bidCount > 0
    return { auction: a, pnl, bidCount, totalCost, winBracket, hadTrades }
  })

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {enriched.map(({ auction, pnl, bidCount, totalCost, winBracket, hadTrades }) => {
        const isPositive = pnl >= 0
        const label = `${new Date(auction.start_date).toLocaleDateString("en-US", { month: "short", day: "numeric" })} → ${new Date(auction.end_date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
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
