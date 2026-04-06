import { formatCurrency, cn } from "@/lib/utils"

function fmt(n: number, decimals = 1): string {
  return parseFloat(n.toFixed(decimals)).toString()
}

interface Position {
  bracket: string
  side: string
  size: number
  avg_price: number
  realized_pnl: number
  unrealized_pnl: number
  status: string
}

export function PositionsTable({
  openPositions, totalInvested, potentialWin, bestBracket, marketPrices, auctionLabel,
}: {
  openPositions: Position[]
  totalInvested: number
  potentialWin: number
  bestBracket: string
  marketPrices?: Record<string, number>
  auctionLabel?: string
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-6 py-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Open Positions ({openPositions.length})
          </h2>
          {auctionLabel && (
            <span className="text-xs text-muted-foreground">{auctionLabel}</span>
          )}
        </div>
        <p className="mt-1 mb-3 text-xs text-muted-foreground">Positions for the selected auction. Each share pays out $1.00 if it resolves YES.</p>
      </div>
      {openPositions.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-6 py-2 text-left">Side</th>
                <th className="px-6 py-2 text-left">Bracket</th>
                <th className="px-6 py-2 text-right">Shares</th>
                <th className="px-6 py-2 text-right">Avg → Now</th>
                <th className="px-6 py-2 text-right">Cost</th>
                <th className="px-6 py-2 text-right">Value</th>
                <th className="px-6 py-2 text-right">Payout If Wins</th>
                <th className="px-6 py-2 text-right">Net P&L If Wins</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map((p, i) => {
                const cost = p.size * p.avg_price
                const payout = p.size * 1.0
                const nowPrice = marketPrices?.[p.bracket] ?? p.avg_price
                const currentValue = p.size * nowPrice
                const valuePnl = currentValue - cost
                const othersCost = openPositions
                  .filter((op) => op.bracket !== p.bracket)
                  .reduce((s, op) => s + (op.size * op.avg_price), 0)
                const netPnl = (payout - cost) - othersCost
                return (
                  <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/50">
                    <td className="px-6 py-3">
                      <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${p.side === "BUY" ? "bg-success/20 text-success" : "bg-destructive/20 text-destructive"}`}>
                        {p.side}
                      </span>
                    </td>
                    <td className="px-6 py-3 font-medium">{p.bracket}</td>
                    <td className="px-6 py-3 text-right">{fmt(p.size)}</td>
                    <td className="px-6 py-3 text-right">
                      <span className="text-muted-foreground">{fmt(p.avg_price * 100)}¢</span>
                      <span className="mx-1">→</span>
                      <span className={cn(nowPrice > p.avg_price ? "text-success" : nowPrice < p.avg_price ? "text-destructive" : "")}>
                        {fmt(nowPrice * 100)}¢
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right">{formatCurrency(cost)}</td>
                    <td className="px-6 py-3 text-right">
                      <span className="font-medium">{formatCurrency(currentValue)}</span>
                      <br />
                      <span className={cn("text-xs", valuePnl >= 0 ? "text-success" : "text-destructive")}>
                        {valuePnl >= 0 ? "+" : ""}{formatCurrency(valuePnl)} ({cost > 0 ? `${((valuePnl / cost) * 100).toFixed(1)}%` : "0%"})
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right">{formatCurrency(payout)}</td>
                    <td className={cn("px-6 py-3 text-right font-medium", netPnl >= 0 ? "text-success" : "text-destructive")}>
                      {netPnl >= 0 ? "+" : ""}{formatCurrency(netPnl)}
                    </td>
                  </tr>
                )
              })}
              {(() => {
                const totalCurrentValue = openPositions.reduce((s, p) => s + p.size * (marketPrices?.[p.bracket] ?? p.avg_price), 0)
                const totalValuePnl = totalCurrentValue - totalInvested
                return (
                  <tr className="bg-muted/30 font-medium">
                    <td className="px-6 py-3" colSpan={4}>Totals</td>
                    <td className="px-6 py-3 text-right">{formatCurrency(totalInvested)}</td>
                    <td className="px-6 py-3 text-right">
                      <span>{formatCurrency(totalCurrentValue)}</span>
                      <br />
                      <span className={cn("text-xs", totalValuePnl >= 0 ? "text-success" : "text-destructive")}>
                        {totalValuePnl >= 0 ? "+" : ""}{formatCurrency(totalValuePnl)}
                      </span>
                    </td>
                    <td className="px-6 py-3" />
                    <td className={cn("px-6 py-3 text-right text-xs", potentialWin >= 0 ? "text-success" : "text-destructive")}>
                      Best: {potentialWin >= 0 ? "+" : ""}{formatCurrency(potentialWin)} if {bestBracket}
                    </td>
                  </tr>
                )
              })()}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-muted-foreground">No open positions</p>
      )}
    </div>
  )
}
