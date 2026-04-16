"use client"

import { useApi } from "@/lib/hooks"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface KellyRow { bracket: string; recommended: number; actual: number; created_at: string }

export function KellyTrackerChart({ moduleId }: { moduleId: string }) {
  const { data } = useApi<{ rows: KellyRow[] }>(moduleId ? `/api/modules/${moduleId}/kelly-tracker?limit=20` : null)
  const rows = data?.rows || []

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Kelly Sizing Tracker</h2>
      <p className="mb-4 text-xs text-muted-foreground">Recommended vs actual order size (last 20 signals)</p>
      {rows.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={rows} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <XAxis dataKey="bracket" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" tickFormatter={(v) => `$${v}`} />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => `$${v.toFixed(2)}`} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="recommended" fill="hsl(200, 70%, 55%)" name="Recommended" />
            <Bar dataKey="actual" fill="hsl(142, 71%, 45%)" name="Actual" />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">No signal data yet</div>
      )}
    </div>
  )
}
