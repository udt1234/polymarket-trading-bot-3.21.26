"use client"

import { useApi } from "@/lib/hooks"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface BookSnapshot {
  bracket: string
  best_bid: number
  best_ask: number
  bid_depth_5: number
  ask_depth_5: number
  spread: number
  midpoint: number
  snapshot_at: string
}

export function OrderBookDepthChart({ moduleId }: { moduleId: string }) {
  const { data } = useApi<{ snapshots: BookSnapshot[] }>(moduleId ? `/api/modules/${moduleId}/order-book-depth` : null)
  const snapshots = (data?.snapshots || []).sort((a, b) => {
    const na = parseInt(a.bracket.match(/\d+/)?.[0] || "0")
    const nb = parseInt(b.bracket.match(/\d+/)?.[0] || "0")
    return na - nb
  })

  const chartData = snapshots.map((s) => ({
    bracket: s.bracket,
    bidDepth: -(s.bid_depth_5 || 0),
    askDepth: s.ask_depth_5 || 0,
    spread: s.spread ? (s.spread * 100).toFixed(1) + "¢" : "—",
  }))

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Order Book Depth</h2>
      <p className="mb-4 text-xs text-muted-foreground">Bid (left, green) vs ask (right, red) depth per bracket</p>
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} layout="vertical" margin={{ top: 5, right: 10, left: 40, bottom: 5 }}>
            <XAxis type="number" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `$${Math.abs(v).toFixed(0)}`} />
            <YAxis type="category" dataKey="bracket" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" width={60} />
            <Tooltip
              contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }}
              formatter={(v: number) => `$${Math.abs(v).toFixed(2)}`}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="bidDepth" fill="hsl(142, 71%, 45%)" name="Bid depth" stackId="a" />
            <Bar dataKey="askDepth" fill="hsl(0, 84%, 60%)" name="Ask depth" stackId="a" />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">No order book data — snapshot job runs every 5min</div>
      )}
    </div>
  )
}
