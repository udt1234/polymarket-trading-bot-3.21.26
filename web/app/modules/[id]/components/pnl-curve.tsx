"use client"

// Build-tag: pnl-curve-v2 (forces Railway to pick up new chunk hash)
import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts"

interface Trade { bracket: string; side: string; size: number; price: number; executed_at: string }
interface Position { bracket: string; size: number; avg_price: number; realized_pnl: number; status: string; closed_at?: string | null }

function fmtMoney(n: number): string {
  const s = n < 0 ? "-" : n > 0 ? "+" : ""
  const abs = Math.abs(n)
  return `${s}$${abs >= 100 ? Math.round(abs).toLocaleString() : abs.toFixed(2)}`
}

export function PnlCurve({ trades, openPositions, closedPositions, marketPrices }: {
  trades: Trade[]
  openPositions: Position[]
  closedPositions: Position[]
  marketPrices?: Record<string, number>
}) {
  if (!trades.length && !closedPositions.length && !openPositions.length) return null

  const sortedTrades = [...trades].sort((a, b) => a.executed_at.localeCompare(b.executed_at))

  const totalCostBasis = sortedTrades
    .filter((t) => (t.side || "").toUpperCase() === "BUY")
    .reduce((s, t) => s + t.size * t.price, 0)

  const realizedPnl = closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0)
  const unrealizedPnl = openPositions.reduce(
    (s, p) => s + (p.size * (marketPrices?.[p.bracket] ?? p.avg_price)) - (p.size * p.avg_price),
    0,
  )
  const totalPnl = realizedPnl + unrealizedPnl

  const denominator = totalCostBasis > 0 ? totalCostBasis : (closedPositions.reduce((s, p) => s + p.size * p.avg_price, 0) + openPositions.reduce((s, p) => s + p.size * p.avg_price, 0))
  const totalReturnPct = denominator > 0 ? (totalPnl / denominator) * 100 : 0

  let cumCostBasis = 0
  const chartData = sortedTrades.map((t, idx) => {
    const isBuy = (t.side || "").toUpperCase() === "BUY"
    if (isBuy) cumCostBasis += t.size * t.price
    const pnlAtPoint = idx === sortedTrades.length - 1 ? totalPnl : 0
    return {
      idx: idx + 1,
      label: new Date(t.executed_at).toLocaleString("en-US", {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      }),
      costBasis: parseFloat(cumCostBasis.toFixed(2)),
      pnl: parseFloat(pnlAtPoint.toFixed(2)),
    }
  })

  const sign = totalPnl > 0 ? "positive" : totalPnl < 0 ? "negative" : "flat"
  const trendClass = sign === "positive" ? "text-success" : sign === "negative" ? "text-destructive" : "text-muted-foreground"
  const TrendIcon = sign === "positive" ? TrendingUp : sign === "negative" ? TrendingDown : Minus

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold">Module P&L</h2>
          <div className={cn("flex items-center gap-1 text-sm font-medium", trendClass)}>
            <TrendIcon className="h-4 w-4" />
            {fmtMoney(totalPnl)}
            {denominator > 0 && (
              <span className="ml-1 text-xs text-muted-foreground">({totalReturnPct >= 0 ? "+" : ""}{totalReturnPct.toFixed(1)}%)</span>
            )}
          </div>
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>Realized: <span className={cn("font-medium", realizedPnl >= 0 ? "text-success" : "text-destructive")}>{fmtMoney(realizedPnl)}</span></span>
          <span>Unrealized: <span className={cn("font-medium", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>{fmtMoney(unrealizedPnl)}</span></span>
          <span>Trades: <span className="font-medium text-foreground">{sortedTrades.length}</span></span>
          <span>Cost Basis: <span className="font-medium text-foreground">${totalCostBasis.toFixed(2)}</span></span>
        </div>
      </div>
      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="costBasisGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="hsl(215, 25%, 50%)" stopOpacity={0.25} />
                <stop offset="95%" stopColor="hsl(215, 25%, 50%)" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={sign === "negative" ? "hsl(0, 84%, 60%)" : "hsl(142, 71%, 45%)"} stopOpacity={0.3} />
                <stop offset="95%" stopColor={sign === "negative" ? "hsl(0, 84%, 60%)" : "hsl(142, 71%, 45%)"} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10 }}
              stroke="hsl(215, 20%, 65%)"
              minTickGap={40}
              interval="preserveStartEnd"
            />
            <YAxis tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `$${v}`} />
            <ReferenceLine y={0} stroke="hsl(215, 20%, 35%)" strokeDasharray="3 3" />
            <Tooltip
              contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }}
              formatter={(v: number, name: string) => [`$${v.toFixed(2)}`, name === "costBasis" ? "Cost Basis" : "P&L"]}
            />
            <Area type="stepAfter" dataKey="costBasis" name="costBasis" stroke="hsl(215, 25%, 50%)" fill="url(#costBasisGradient)" strokeWidth={1.5} />
            <Area type="monotone" dataKey="pnl" name="pnl" stroke={sign === "negative" ? "hsl(0, 84%, 60%)" : "hsl(142, 71%, 45%)"} fill="url(#pnlGradient)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">More trades needed for chart</div>
      )}
    </div>
  )
}
