"use client"

import { useApi } from "@/lib/hooks"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts"

interface Bucket { bucket: string; count: number }
interface LatencyData { buckets: Bucket[]; sample_count: number; avg_latency_s: number; median_latency_s: number }

const BUCKET_COLORS: Record<string, string> = {
  "<1s": "hsl(142, 71%, 45%)",
  "1-5s": "hsl(142, 50%, 50%)",
  "5-30s": "hsl(45, 93%, 55%)",
  "30-60s": "hsl(25, 95%, 53%)",
  ">60s": "hsl(0, 84%, 60%)",
}

export function LatencyHistogramChart({ moduleId }: { moduleId: string }) {
  const { data } = useApi<LatencyData>(moduleId ? `/api/modules/${moduleId}/latency-histogram` : null)

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Signal-to-Fill Latency</h2>
          <p className="text-xs text-muted-foreground">Time between post detection and order fill</p>
        </div>
        {data && data.sample_count > 0 && (
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span>Avg: <span className="text-foreground font-medium">{data.avg_latency_s.toFixed(1)}s</span></span>
            <span>Median: <span className="text-foreground font-medium">{data.median_latency_s.toFixed(1)}s</span></span>
            <span>n={data.sample_count}</span>
          </div>
        )}
      </div>
      {data && data.sample_count > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data.buckets} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <XAxis dataKey="bucket" tick={{ fontSize: 11 }} stroke="hsl(215, 20%, 65%)" />
            <YAxis tick={{ fontSize: 10 }} stroke="hsl(215, 20%, 65%)" />
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} />
            <Bar dataKey="count">
              {data.buckets.map((b, i) => (
                <Cell key={i} fill={BUCKET_COLORS[b.bucket] || "hsl(215, 20%, 55%)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
          No latency data yet — need new signals after deploy
        </div>
      )}
    </div>
  )
}
