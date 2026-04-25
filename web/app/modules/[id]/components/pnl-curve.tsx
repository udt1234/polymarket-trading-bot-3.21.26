"use client"

import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown } from "lucide-react"
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts"

interface Trade { bracket: string; side: string; size: number; price: number; executed_at: string }
interface Position { bracket: string; size: number; avg_price: number; realized_pnl: number; status: string; closed_at?: string | null }

export function PnlCurve({ trades, openPositions, closedPositions, marketPrices }: {
  trades: Trade[]
  openPositions: Position[]
  closedPositions: Position[]
  marketPrices?: Record<string, number>
}) {
  if (!trades.length && !closedPositions.length) return null

  const sortedTrades = [...trades].sort((a, b) => a.executed_at.localeCompare(b.executed_at))
  const totalInvestedAll = sortedTrades.reduce((s, t) => s + t.size * t.price, 0)
  const realizedPnlTotal = closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0)
  const unrealizedPnlTotal = openPositions.reduce(
    (s, p) => s + (p.size * (marketPrices?.[p.bracket] ?? p.avg_price)) - (p.size * p.avg_price),
    0,
  )
  const finalPnl = realizedPnlTotal + unrealizedPnlTotal

  let cumInvested = 0
  let cumPnl = 0
  let peak = 0
  let maxDrawdown = 0
  const chartData = sortedTrades.map((t, idx) => {
    cumInvested += t.size * t.price

    const tradeTime = t.executed_at
    const realizedToDate = closedPositions
      .filter((p) => (p.closed_at || "") <= tradeTime)
      .reduce((s, p) => s + (p.realized_pnl || 0), 0)

    const isLastTrade = idx === sortedTrades.length - 1
    const unrealizedToDate = isLastTrade ? unrealizedPnlTotal : 0

    cumPnl = realizedToDate + unrealizedToDate
    peak = Math.max(peak, cumPnl)
    const dd = peak > 0 ? ((peak - cumPnl) / peak) * 100 : 0
    maxDrawdown = Math.max(maxDrawdown, dd)
    return {
      date: new Date(t.executed_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      pnl: parseFloat(cumPnl.toFixed(2)),
      drawdown: parseFloat((peak - cumPnl).toFixed(2)),
    }
  })

  const totalReturn = totalInvestedAll > 0 ? ((finalPnl / totalInvestedAll) * 100).toFixed(1) : "0"
  const isPositive = finalPnl >= 0

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Module P&L</h2>
          <div className={cn("flex items-center gap-1 text-sm font-medium", isPositive ? "text-success" : "text-destructive")}>
            {isPositive ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
            {isPositive ? "+" : ""}{totalReturn}%
          </div>
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>Max DD: <span className="font-medium text-amber-400">{maxDrawdown.toFixed(1)}%</span></span>
          <span>Trades: <span className="font-medium text-foreground">{sortedTrades.length}</span></span>
          <span>Invested: <span className="font-medium text-foreground">${Math.round(totalInvestedAll)}</span></span>
        </div>
      </div>
      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="modulePnlGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={isPositive ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)"} stopOpacity={0.3} />
                <stop offset="95%" stopColor={isPositive ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)"} stopOpacity={0} />
              </linearGradient>
              <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="hsl(25, 95%, 53%)" stopOpacity={0.2} />
                <stop offset="95%" stopColor="hsl(25, 95%, 53%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `$${v}`} />
            <ReferenceLine y={0} stroke="hsl(215, 20%, 35%)" strokeDasharray="3 3" />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => `$${v.toFixed(2)}`} />
            <Area type="monotone" dataKey="drawdown" stroke="hsl(25, 95%, 53%)" fill="url(#drawdownGradient)" strokeWidth={1} strokeDasharray="3 3" />
            <Area type="monotone" dataKey="pnl" stroke={isPositive ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)"} fill="url(#modulePnlGradient)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">More trades needed for chart</div>
      )}
    </div>
  )
}
