"use client"

import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts"

interface PriceSeries { bracket: string; price: number; snapshot_hour: string }
interface Trade { bracket: string; side: string; price: number; executed_at: string }

export function PriceOverTimeChart({ moduleId, brackets }: { moduleId: string; brackets: string[] }) {
  const [selected, setSelected] = useState<string>(brackets[0] || "")
  const { data } = useApi<{ series: PriceSeries[]; trades: Trade[] }>(
    moduleId && selected ? `/api/modules/${moduleId}/price-history?bracket=${encodeURIComponent(selected)}&limit=200` : null,
    [selected]
  )

  const chartData = (data?.series || []).map((s) => ({
    label: new Date(s.snapshot_hour).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "numeric" }),
    price: s.price,
    snapshot_hour: s.snapshot_hour,
  }))

  const trades = data?.trades || []

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Price Over Time</h2>
          <p className="text-xs text-muted-foreground">Bracket price history with trade markers</p>
        </div>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1 text-xs"
        >
          {brackets.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
      </div>
      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `${(v * 100).toFixed(0)}¢`} domain={[0, 1]} />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => `${(v * 100).toFixed(2)}¢`} />
            {trades.map((t, i) => {
              const matchingPt = chartData.find((d) => d.snapshot_hour >= t.executed_at)
              if (!matchingPt) return null
              return (
                <ReferenceLine
                  key={i}
                  x={matchingPt.label}
                  stroke={t.side === "BUY" ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)"}
                  strokeDasharray="3 3"
                  label={{ value: t.side[0], fontSize: 9, fill: t.side === "BUY" ? "hsl(142, 71%, 45%)" : "hsl(0, 84%, 60%)" }}
                />
              )
            })}
            <Line type="monotone" dataKey="price" stroke="hsl(200, 70%, 55%)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">No price history for this bracket</div>
      )}
    </div>
  )
}
