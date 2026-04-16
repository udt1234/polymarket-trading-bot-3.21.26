"use client"

import { useApi } from "@/lib/hooks"
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface PriceSeries { bracket: string; price: number; volume?: number; snapshot_hour: string }

export function VolumePriceChart({ moduleId }: { moduleId: string }) {
  const { data } = useApi<{ series: PriceSeries[] }>(moduleId ? `/api/modules/${moduleId}/price-history?limit=200` : null)
  const rows = data?.series || []

  const byBracket: Record<string, { price: number; volume: number }> = {}
  for (const r of rows) {
    if (!byBracket[r.bracket] || r.snapshot_hour > (byBracket[r.bracket] as any).snapshot_hour) {
      byBracket[r.bracket] = { price: r.price, volume: r.volume || 0 }
    }
  }
  const chartData = Object.entries(byBracket)
    .map(([bracket, v]) => ({ bracket, price: v.price, volume: v.volume }))
    .sort((a, b) => {
      const na = parseInt(a.bracket.match(/\d+/)?.[0] || "0")
      const nb = parseInt(b.bracket.match(/\d+/)?.[0] || "0")
      return na - nb
    })

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Volume vs Price</h2>
      <p className="mb-4 text-xs text-muted-foreground">Current volume and price per bracket</p>
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <XAxis dataKey="bracket" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `${(v * 100).toFixed(0)}¢`} domain={[0, 1]} />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar yAxisId="left" dataKey="volume" fill="hsl(215, 20%, 55%)" name="Volume" />
            <Line yAxisId="right" type="monotone" dataKey="price" stroke="hsl(200, 70%, 55%)" strokeWidth={2} dot={{ r: 3 }} name="Price" />
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">No volume data yet</div>
      )}
    </div>
  )
}
