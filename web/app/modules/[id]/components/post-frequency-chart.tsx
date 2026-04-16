"use client"

import { ComposedChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface HourlyEntry { hour_label: string; count: number; price?: number }

export function PostFrequencyChart({ hourlyData, title = "Post Frequency vs Market Price" }: { hourlyData: HourlyEntry[]; title?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h2>
      <p className="mb-4 text-xs text-muted-foreground">Rolling hourly post count vs market price</p>
      {hourlyData && hourlyData.length > 1 ? (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={hourlyData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <XAxis dataKey="hour_label" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `${(v * 100).toFixed(0)}¢`} />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line yAxisId="left" type="monotone" dataKey="count" stroke="hsl(142, 71%, 45%)" strokeWidth={2} dot={false} name="Posts/hr" />
            <Line yAxisId="right" type="monotone" dataKey="price" stroke="hsl(200, 70%, 55%)" strokeWidth={2} dot={false} strokeDasharray="3 3" name="Price" />
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">Insufficient data</div>
      )}
    </div>
  )
}
