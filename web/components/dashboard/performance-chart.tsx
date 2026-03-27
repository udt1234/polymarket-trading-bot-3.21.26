"use client"

import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { cn } from "@/lib/utils"
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

const RANGES = ["24h", "7d", "30d", "90d", "all"] as const

export function PerformanceChart() {
  const [range, setRange] = useState<string>("7d")
  const { data } = useApi<{ data: any[] }>(`/api/dashboard/performance?range=${range}`, [range])

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Performance</h2>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={cn(
                "rounded-md px-2 py-1 text-xs font-medium",
                range === r ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"
              )}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      {data?.data && data.data.length > 0 ? (
        <ResponsiveContainer width="100%" height={256}>
          <AreaChart data={data.data}>
            <defs>
              <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="hsl(217, 91%, 60%)" stopOpacity={0.3} />
                <stop offset="95%" stopColor="hsl(217, 91%, 60%)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} />
            <Area type="monotone" dataKey="portfolio_value" stroke="hsl(217, 91%, 60%)" fill="url(#pnlGradient)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
          Chart will render here once trading data is available
        </div>
      )}
    </div>
  )
}
