"use client"

import { useApi } from "@/lib/hooks"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid } from "recharts"
import { cn } from "@/lib/utils"

interface SeriesPoint {
  captured_at: string
  xtracker?: number | null
  truthsocial_direct?: number | null
  xtracker_error?: string
  truthsocial_direct_error?: string
}

interface PostCountHistory {
  series: SeriesPoint[]
  latest: {
    xtracker: number | null
    truthsocial_direct: number | null
    diff: number | null
    captured_at: string | null
  }
  row_count: number
}

const ALERT_THRESHOLD = 5

export function PostCountDivergenceChart({ moduleId, trackingId }: { moduleId: string; trackingId?: string | null }) {
  const url = trackingId
    ? `/api/modules/${moduleId}/post-count-history?tracking_id=${encodeURIComponent(trackingId)}&limit=500`
    : `/api/modules/${moduleId}/post-count-history?limit=500`
  const { data, isLoading } = useApi<PostCountHistory>(moduleId ? url : null, [trackingId])

  const series = data?.series || []
  const latest = data?.latest

  const chartData = series.map((p) => ({
    label: new Date(p.captured_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
    captured_at: p.captured_at,
    xTracker: p.xtracker ?? null,
    truthSocial: p.truthsocial_direct ?? null,
    diff: (p.xtracker != null && p.truthsocial_direct != null) ? (p.truthsocial_direct - p.xtracker) : null,
  }))

  const isDiverging = latest?.diff != null && Math.abs(latest.diff) >= ALERT_THRESHOLD

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">xTracker vs Truth Social Direct</h2>
          <p className="text-xs text-muted-foreground">Post count divergence over time. Captured every 5 min.</p>
        </div>
        {latest && (latest.xtracker != null || latest.truthsocial_direct != null) && (
          <div className="flex gap-3 text-xs">
            <div className="text-right">
              <div className="text-muted-foreground">xTracker</div>
              <div className="font-bold">{latest.xtracker ?? "—"}</div>
            </div>
            <div className="text-right">
              <div className="text-muted-foreground">Truth Social</div>
              <div className="font-bold">{latest.truthsocial_direct ?? "—"}</div>
            </div>
            <div className="text-right">
              <div className="text-muted-foreground">Diff</div>
              <div className={cn(
                "font-bold rounded px-1.5",
                latest.diff == null ? "text-muted-foreground" :
                isDiverging ? "bg-destructive/20 text-destructive" :
                Math.abs(latest.diff) >= 2 ? "text-warning" :
                "text-success"
              )}>
                {latest.diff == null ? "—" : (latest.diff > 0 ? `+${latest.diff}` : latest.diff)}
              </div>
            </div>
          </div>
        )}
      </div>

      {isDiverging && (
        <div className="mb-3 rounded-md bg-destructive/10 border border-destructive/30 px-3 py-2 text-xs text-destructive">
          <strong>Divergence alert:</strong> Sources differ by {Math.abs(latest!.diff!)} posts. Check the source-of-truth before placing trades.
        </div>
      )}

      {isLoading ? (
        <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">Loading…</div>
      ) : chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid stroke="hsl(217, 33%, 22%)" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" minTickGap={40} />
            <YAxis tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <Tooltip
              contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }}
              formatter={(v: any, name: string) => [v ?? "—", name]}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="xTracker" stroke="hsl(200, 70%, 55%)" strokeWidth={2} dot={false} connectNulls />
            <Line type="monotone" dataKey="truthSocial" stroke="hsl(280, 70%, 60%)" strokeWidth={2} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">
          No snapshots yet. The bot captures both sources every 5 minutes — check back shortly.
        </div>
      )}

      <div className="mt-3 text-[10px] text-muted-foreground/60">
        {data?.row_count ? `${data.row_count} snapshots loaded` : ""}
        {" · "}xTracker (blue) is Polymarket's tracker. Truth Social (purple) is fetched directly from truthsocial.com.
      </div>
    </div>
  )
}
