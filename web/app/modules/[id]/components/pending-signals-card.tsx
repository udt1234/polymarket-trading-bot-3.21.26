"use client"

import { useApi } from "@/lib/hooks"
import { apiFetch } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Clock, X } from "lucide-react"

interface PendingSignal {
  id: string
  bracket: string
  side: string
  original_price: number
  target_price: number
  abandon_if_price_above: number
  wait_until: string
  expected_drop_pct: number
  analog_count: number
  created_at: string
}

export function PendingSignalsCard({ moduleId }: { moduleId: string }) {
  const { data, refetch } = useApi<{ rows: PendingSignal[] }>(moduleId ? `/api/modules/${moduleId}/pending-signals?status=waiting` : null, [], 30000)
  const rows = data?.rows || []

  if (rows.length === 0) return null

  const handleCancel = async (id: string) => {
    if (!confirm("Cancel this pending signal? The bot will not buy this bracket.")) return
    try {
      await apiFetch(`/api/modules/${moduleId}/pending-signals/${id}`, { method: "DELETE" })
      refetch()
    } catch (e) {
      alert("Cancel failed")
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-3 flex items-center gap-2">
        <Clock className="h-4 w-4 text-amber-400" />
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Pending Entries ({rows.length})</h2>
      </div>
      <p className="mb-4 text-xs text-muted-foreground">Waiting for historical price dips before buying</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 pr-3">Bracket</th>
              <th className="py-2 pr-3">Side</th>
              <th className="py-2 pr-3 text-right">Original</th>
              <th className="py-2 pr-3 text-right">Target</th>
              <th className="py-2 pr-3 text-right">Abandon</th>
              <th className="py-2 pr-3 text-right">Est. Drop</th>
              <th className="py-2 pr-3 text-right">Expires</th>
              <th className="py-2 pr-3 text-right">Analogs</th>
              <th className="py-2 pr-0 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const waitUntil = new Date(r.wait_until)
              const now = new Date()
              const hoursRemaining = Math.max(0, (waitUntil.getTime() - now.getTime()) / 3600000)
              const timeLabel = hoursRemaining < 1 ? `${Math.round(hoursRemaining * 60)}m` : hoursRemaining < 24 ? `${hoursRemaining.toFixed(1)}h` : `${(hoursRemaining / 24).toFixed(1)}d`
              return (
                <tr key={r.id} className="border-b border-border/50 last:border-0">
                  <td className="py-2 pr-3 font-medium">{r.bracket}</td>
                  <td className="py-2 pr-3">
                    <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", r.side === "BUY" ? "bg-success/20 text-success" : "bg-destructive/20 text-destructive")}>
                      {r.side}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right font-mono">{(r.original_price * 100).toFixed(1)}¢</td>
                  <td className="py-2 pr-3 text-right font-mono text-success">{(r.target_price * 100).toFixed(1)}¢</td>
                  <td className="py-2 pr-3 text-right font-mono text-destructive">{(r.abandon_if_price_above * 100).toFixed(1)}¢</td>
                  <td className="py-2 pr-3 text-right font-mono">{(r.expected_drop_pct * 100).toFixed(1)}%</td>
                  <td className="py-2 pr-3 text-right text-muted-foreground">{timeLabel}</td>
                  <td className="py-2 pr-3 text-right text-muted-foreground">{r.analog_count}</td>
                  <td className="py-2 pr-0 text-right">
                    <button
                      onClick={() => handleCancel(r.id)}
                      className="rounded border border-border p-1 hover:bg-accent"
                      title="Cancel pending signal"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
