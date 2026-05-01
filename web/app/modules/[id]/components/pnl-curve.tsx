"use client"

// Build-tag: pnl-curve-v3 (bar chart + range selector, replaces v2 area chart)
import { useState, useMemo } from "react"
import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Cell } from "recharts"

interface Trade { bracket: string; side: string; size: number; price: number; executed_at: string }
interface Position { bracket: string; size: number; avg_price: number; realized_pnl: number; status: string; closed_at?: string | null }

type RangeKey = "7d" | "30d" | "90d" | "all"

function fmtMoney(n: number): string {
  const s = n < 0 ? "-" : n > 0 ? "+" : ""
  const abs = Math.abs(n)
  return `${s}$${abs >= 100 ? Math.round(abs).toLocaleString() : abs.toFixed(2)}`
}

function dayKey(d: Date): string {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`
}

export function PnlCurve({ trades, openPositions, closedPositions, marketPrices }: {
  trades: Trade[]
  openPositions: Position[]
  closedPositions: Position[]
  marketPrices?: Record<string, number>
}) {
  const [range, setRange] = useState<RangeKey>("30d")

  const totalCostBasis = useMemo(
    () => trades.filter((t) => (t.side || "").toUpperCase() === "BUY").reduce((s, t) => s + t.size * t.price, 0),
    [trades],
  )
  const realizedPnl = useMemo(
    () => closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0),
    [closedPositions],
  )
  const unrealizedPnl = useMemo(
    () => openPositions.reduce(
      (s, p) => s + (p.size * (marketPrices?.[p.bracket] ?? p.avg_price)) - (p.size * p.avg_price),
      0,
    ),
    [openPositions, marketPrices],
  )
  const totalPnl = realizedPnl + unrealizedPnl

  const denominator = totalCostBasis > 0 ? totalCostBasis : (
    closedPositions.reduce((s, p) => s + p.size * p.avg_price, 0) +
    openPositions.reduce((s, p) => s + p.size * p.avg_price, 0)
  )
  const totalReturnPct = denominator > 0 ? (totalPnl / denominator) * 100 : 0

  // Build per-day P&L bars from closed positions. Each closed position
  // contributes its realized_pnl to its closed_at date (or created_at as fallback).
  const allBars = useMemo(() => {
    const byDay = new Map<string, { date: Date; pnl: number }>()
    for (const p of closedPositions) {
      const dateStr = p.closed_at || (p as any).created_at
      if (!dateStr) continue
      const d = new Date(dateStr)
      if (isNaN(d.getTime())) continue
      const key = dayKey(d)
      const existing = byDay.get(key)
      if (existing) existing.pnl += p.realized_pnl || 0
      else byDay.set(key, { date: d, pnl: p.realized_pnl || 0 })
    }
    return Array.from(byDay.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([_k, v]) => ({
        label: v.date.toLocaleString("en-US", { month: "short", day: "numeric" }),
        date: v.date,
        pnl: parseFloat(v.pnl.toFixed(2)),
      }))
  }, [closedPositions])

  // Filter by range. "all" returns everything; otherwise last N days from now.
  const chartData = useMemo(() => {
    if (range === "all") return allBars
    const days = range === "7d" ? 7 : range === "30d" ? 30 : 90
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - days)
    return allBars.filter((b) => b.date >= cutoff)
  }, [allBars, range])

  if (!trades.length && !closedPositions.length && !openPositions.length) return null

  const sign = totalPnl > 0 ? "positive" : totalPnl < 0 ? "negative" : "flat"
  const trendClass = sign === "positive" ? "text-success" : sign === "negative" ? "text-destructive" : "text-muted-foreground"
  const TrendIcon = sign === "positive" ? TrendingUp : sign === "negative" ? TrendingDown : Minus

  const RANGE_OPTIONS: { key: RangeKey; label: string }[] = [
    { key: "7d", label: "7d" },
    { key: "30d", label: "30d" },
    { key: "90d", label: "90d" },
    { key: "all", label: "All" },
  ]

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
        <div className="flex items-center gap-3">
          <div className="flex gap-4 text-xs text-muted-foreground">
            <span>Realized: <span className={cn("font-medium", realizedPnl >= 0 ? "text-success" : "text-destructive")}>{fmtMoney(realizedPnl)}</span></span>
            <span>Unrealized: <span className={cn("font-medium", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>{fmtMoney(unrealizedPnl)}</span></span>
            <span>Trades: <span className="font-medium text-foreground">{trades.length}</span></span>
          </div>
          <div className="flex rounded-md border border-border overflow-hidden">
            {RANGE_OPTIONS.map((r) => (
              <button
                key={r.key}
                onClick={() => setRange(r.key)}
                className={cn(
                  "px-2.5 py-1 text-xs transition-colors",
                  range === r.key
                    ? "bg-primary text-primary-foreground"
                    : "bg-background text-muted-foreground hover:bg-accent/50",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 5 }}>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10 }}
              stroke="hsl(215, 20%, 65%)"
              minTickGap={20}
              interval="preserveStartEnd"
            />
            <YAxis tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `$${v}`} />
            <ReferenceLine y={0} stroke="hsl(215, 20%, 35%)" />
            <Tooltip
              contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }}
              formatter={(v: number) => [`${v >= 0 ? "+" : ""}$${v.toFixed(2)}`, "Realized P&L"]}
              cursor={{ fill: "hsl(215, 20%, 25%)", opacity: 0.2 }}
            />
            <Bar dataKey="pnl" name="Daily P&L">
              {chartData.map((d, idx) => (
                <Cell
                  key={idx}
                  fill={d.pnl >= 0 ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          No closed trades in the last {range === "all" ? "all time" : range}.
        </div>
      )}
    </div>
  )
}
