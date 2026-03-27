"use client"

import { useParams } from "next/navigation"
import { useState, useEffect, useCallback } from "react"
import { useApi, useMutation } from "@/lib/hooks"
import { formatCurrency, cn } from "@/lib/utils"
import { StatusBadge } from "@/components/shared/status-badge"
import {
  ChevronDown, ChevronUp, RefreshCw, Pause, Play, Power,
  TrendingUp, TrendingDown, Minus, ArrowUpRight, ArrowDownRight,
  Save, Settings,
} from "lucide-react"

interface ModuleData {
  id: string
  name: string
  market_slug: string
  strategy: string
  budget: number
  max_position_pct: number
  status: string
  auto_pause: boolean
  resolution_date: string | null
  created_at: string
}

interface Signal {
  bracket: string
  side: string
  edge: number
  model_prob: number
  market_price: number
  kelly_pct: number
  approved: boolean
  rejection_reason?: string
  created_at: string
  market_id?: string
  module_id?: string
}

interface Trade {
  bracket: string
  side: string
  size: number
  price: number
  executor: string
  executed_at: string
}

interface Position {
  bracket: string
  side: string
  size: number
  avg_price: number
  realized_pnl: number
  unrealized_pnl: number
  status: string
  module_id?: string
}

interface PacingRow {
  date: string
  day: string
  daily_posts: number
  running_total: number
  dow_avg: number
  dow_weight: number
  deviation: number
  status: "ahead" | "behind" | "on_pace"
  is_today: boolean
  is_future: boolean
}

interface PacingData {
  rows: PacingRow[]
  dow_averages?: {
    overall: { day: string; avg: number; std: number; n: number }[]
    regime?: { day: string; avg: number; std: number; n: number }[]
  }
  acceleration?: {
    current_rate: number
    prior_rate: number
    label: "accelerating" | "decelerating" | "steady"
  }
  confidence_bands?: { bracket: string; probability: number; cumulative: number; rank: number; confidence?: number }[]
  ensemble?: {
    models: { name: string; projection: number; weight: number; contribution: number }[]
    ensemble_avg: number
  }
  current_auction?: AuctionInfo
  next_auction?: AuctionInfo
}

interface AuctionInfo {
  period_start: string
  period_end: string
  auction_type: string
  running_total: number
  days_elapsed: number
  days_left: number
  regime_label: string
  zscore: number
  projected_winner: string
  market_implied_winner: string
  edge: number
}

interface ModuleConfig {
  historical_periods: number
  recency_half_life: number
  regime_conditional: boolean
  parquet_model: boolean
  dow_weights_source: "recency" | "equal" | "regime"
  auto_optimize_periods: boolean
}

interface AuctionTab {
  tracking_id: string
  title: string
  start_date: string
  end_date: string
  elapsed_days: number
  remaining_days: number
  status: "active" | "past" | "future"
  is_active: boolean
}

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

function fmt(n: number, decimals = 1): string {
  return parseFloat(n.toFixed(decimals)).toString()
}


export default function ModuleDetailPage() {
  const params = useParams()
  const moduleId = params.id as string

  const { data: modules } = useApi<ModuleData[]>("/api/modules/")
  const module = modules?.find(
    (m) => m.id === moduleId || m.name.toLowerCase().replace(/\s+/g, "-") === moduleId
  )
  const id = module?.id

  const { data: moduleSignals } = useApi<Signal[]>(
    id ? `/api/dashboard/recent-signals?limit=30` : null
  )
  const { data: trades } = useApi<{ data: Trade[]; total: number }>(
    id ? `/api/trades/?module_id=${id}&limit=20` : null
  )
  const { data: positions } = useApi<Position[]>(
    id ? `/api/portfolio/positions?status=all` : null
  )
  const [activeTrackingId, setActiveTrackingId] = useState<string | null>(null)

  const { data: auctions } = useApi<AuctionTab[]>(
    id ? `/api/modules/${id}/auctions` : null
  )
  const { data: regime } = useApi<any>("/api/analytics/regime")
  const pacingUrl = id
    ? `/api/modules/${id}/pacing${activeTrackingId ? `?tracking_id=${activeTrackingId}` : ""}`
    : null
  const { data: pacing, refetch: refetchPacing } = useApi<PacingData>(
    pacingUrl, [activeTrackingId], 60000
  )
  const { data: config, refetch: refetchConfig } = useApi<ModuleConfig>(
    id ? `/api/modules/${id}/config` : null
  )

  const [lastRefresh, setLastRefresh] = useState(new Date())
  const [configOpen, setConfigOpen] = useState(false)
  const [localConfig, setLocalConfig] = useState<ModuleConfig>({
    historical_periods: 9,
    recency_half_life: 4.0,
    regime_conditional: false,
    parquet_model: false,
    dow_weights_source: "recency",
    auto_optimize_periods: false,
  })

  useEffect(() => {
    if (config) setLocalConfig(config)
  }, [config])

  useEffect(() => {
    const interval = setInterval(() => setLastRefresh(new Date()), 60000)
    return () => clearInterval(interval)
  }, [])

  const { mutate: saveConfig, loading: savingConfig } = useMutation(
    id ? `/api/modules/${id}/config` : "", "PUT"
  )
  const { mutate: togglePause } = useMutation(
    id ? `/api/modules/${id}/toggle` : "", "POST"
  )
  const { mutate: killSwitch } = useMutation(
    id ? `/api/modules/${id}/kill` : "", "POST"
  )

  const handleSaveConfig = useCallback(async () => {
    await saveConfig(localConfig)
    refetchConfig()
    refetchPacing()
  }, [localConfig, saveConfig, refetchConfig, refetchPacing])

  const mySignals = (moduleSignals || []).filter((s: any) => s.module_id === id)
  const myPositions = (positions || []).filter((p: any) => p.module_id === id)
  const openPositions = myPositions.filter((p) => p.status === "open")
  const closedPositions = myPositions.filter((p) => p.status === "closed")

  const totalInvested = openPositions.reduce((s, p) => s + (p.size * p.avg_price), 0)
  const totalPnl = myPositions.reduce((s, p) => s + (p.realized_pnl || 0) + (p.unrealized_pnl || 0), 0)
  const potentialWin = openPositions.reduce((s, p) => s + (p.size * (1 - p.avg_price)), 0)
  const wins = closedPositions.filter((p) => (p.realized_pnl || 0) > 0).length
  const winRate = closedPositions.length > 0 ? (wins / closedPositions.length) * 100 : 0

  if (!module) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading module...
      </div>
    )
  }

  const accel = pacing?.pace_acceleration
  const bands = pacing?.confidence_bands
  const ensemble = pacing?.ensemble_breakdown
  const dowAvg = pacing?.dow_heatmap

  return (
    <div className="space-y-6">
      {/* Top Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{module.name}</h1>
          <StatusBadge status={module.status} />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            Updated {lastRefresh.toLocaleTimeString()}
          </span>
          <button
            onClick={() => { refetchPacing(); setLastRefresh(new Date()) }}
            className="rounded-md border border-border p-1.5 hover:bg-accent"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => togglePause()}
            className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
          >
            {module.status === "active" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {module.status === "active" ? "Pause" : "Resume"}
          </button>
          <button
            onClick={() => { if (confirm("Kill this module? All positions will be closed.")) killSwitch() }}
            className="flex items-center gap-1.5 rounded-md border border-destructive px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
          >
            <Power className="h-3.5 w-3.5" />
            Kill Switch
          </button>
        </div>
      </div>

      {/* Config Panel */}
      <div className="rounded-lg border border-border bg-card">
        <button
          onClick={() => setConfigOpen(!configOpen)}
          className="flex w-full items-center justify-between px-6 py-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground hover:bg-accent/50"
        >
          <span className="flex items-center gap-2">
            <Settings className="h-4 w-4" />
            Pacing Configuration
          </span>
          {configOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {configOpen && (
          <div className="border-t border-border px-6 py-4">
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">Historical Periods</span>
                <input
                  type="number" min={1} max={52}
                  value={localConfig.historical_periods}
                  onChange={(e) => setLocalConfig({ ...localConfig, historical_periods: +e.target.value })}
                  className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">Recency Half-Life</span>
                <input
                  type="number" min={0.5} max={20} step={0.5}
                  value={localConfig.recency_half_life}
                  onChange={(e) => setLocalConfig({ ...localConfig, recency_half_life: +e.target.value })}
                  className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs text-muted-foreground">DOW Weights Source</span>
                <select
                  value={localConfig.dow_weights_source}
                  onChange={(e) => setLocalConfig({ ...localConfig, dow_weights_source: e.target.value as any })}
                  className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                >
                  <option value="recency">Recency-Weighted</option>
                  <option value="equal">Equal Weight</option>
                  <option value="regime">Regime-Conditional</option>
                </select>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5">
                <input
                  type="checkbox" checked={localConfig.regime_conditional}
                  onChange={(e) => setLocalConfig({ ...localConfig, regime_conditional: e.target.checked })}
                  className="rounded border-border"
                />
                <span className="text-sm">Regime-Conditional</span>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5">
                <input
                  type="checkbox" checked={localConfig.parquet_model}
                  onChange={(e) => setLocalConfig({ ...localConfig, parquet_model: e.target.checked })}
                  className="rounded border-border"
                />
                <span className="text-sm">Parquet Model</span>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5">
                <input
                  type="checkbox" checked={localConfig.auto_optimize_periods}
                  onChange={(e) => setLocalConfig({ ...localConfig, auto_optimize_periods: e.target.checked })}
                  className="rounded border-border"
                />
                <span className="text-sm">Auto-Optimize</span>
              </label>
            </div>
            <div className="mt-4 flex justify-end">
              <button
                onClick={handleSaveConfig}
                disabled={savingConfig}
                className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                <Save className="h-3.5 w-3.5" />
                {savingConfig ? "Saving..." : "Save Config"}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Current Value</p>
          <p className="mt-1 text-2xl font-bold">{formatCurrency(totalInvested)}</p>
          <p className="text-xs text-muted-foreground">{openPositions.length} open positions</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Potential Win</p>
          <p className="mt-1 text-2xl font-bold text-success">{formatCurrency(potentialWin)}</p>
          <p className="text-xs text-muted-foreground">If all positions resolve YES</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Bot P&L</p>
          <p className={cn("mt-1 text-2xl font-bold", totalPnl >= 0 ? "text-success" : "text-destructive")}>
            {formatCurrency(totalPnl)}
          </p>
          <p className="text-xs text-muted-foreground">Paper trades only</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Win Rate</p>
          <p className="mt-1 text-2xl font-bold">{fmt(winRate)}%</p>
          <p className="text-xs text-muted-foreground">{wins}W / {closedPositions.length - wins}L</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Budget</p>
          <p className="mt-1 text-2xl font-bold">{formatCurrency(module.budget)}</p>
          <p className="text-xs text-muted-foreground">Max: {(module.max_position_pct * 100).toFixed(0)}% per bracket</p>
        </div>
      </div>

      {/* Auction Tabs */}
      {auctions && auctions.length > 0 && (
        <div className="flex gap-2 overflow-x-auto rounded-lg border border-border bg-card p-2">
          {auctions.map((a) => {
            const isSelected = activeTrackingId
              ? activeTrackingId === a.tracking_id
              : (pacing as any)?.tracking_id === a.tracking_id
            const isPast = a.status === "past"
            return (
              <button
                key={a.tracking_id}
                onClick={() => setActiveTrackingId(a.tracking_id)}
                className={cn(
                  "flex-shrink-0 rounded-md px-4 py-2 text-sm font-medium transition-colors",
                  isSelected
                    ? "bg-primary text-primary-foreground"
                    : isPast
                      ? "text-muted-foreground/60 hover:bg-accent hover:text-foreground border border-dashed border-border"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )}
              >
                <span className="flex items-center gap-1.5">
                  {isPast && <span className="text-[9px] rounded bg-muted px-1 py-0.5 uppercase">Past</span>}
                  {a.start_date.slice(5)} → {a.end_date.slice(5)}
                </span>
                <span className="block text-[10px] opacity-75">
                  {isPast
                    ? "Resolved"
                    : `${a.elapsed_days.toFixed(0)}d elapsed / ${a.remaining_days.toFixed(0)}d left`
                  }
                </span>
              </button>
            )
          })}
        </div>
      )}

      {/* Daily Pacing Table */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Daily Pacing
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Day-by-day breakdown of posting activity for this auction. Shows actual posts vs what we'd expect based on historical patterns.</p>
        </div>
        {pacing?.daily_table && pacing.daily_table.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-4 py-2 text-left">Date</th>
                  <th className="px-4 py-2 text-left">Day</th>
                  <th className="px-4 py-2 text-right">Daily Posts</th>
                  <th className="px-4 py-2 text-right">Running Total</th>
                  <th className="px-4 py-2 text-right">DOW Avg</th>
                  <th className="px-4 py-2 text-right">DOW Weight</th>
                  <th className="px-4 py-2 text-right">Deviation</th>
                  <th className="px-4 py-2 text-center">Status</th>
                </tr>
              </thead>
              <tbody>
                {pacing.daily_table.map((row: any, i: number) => (
                  <tr
                    key={i}
                    className={cn(
                      "border-b border-border last:border-0",
                      row.is_today && "bg-primary/5 font-medium",
                      row.is_future && "text-muted-foreground italic"
                    )}
                  >
                    <td className="px-4 py-2">{row.date}</td>
                    <td className="px-4 py-2">{row.day}</td>
                    <td className="px-4 py-2 text-right">{row.daily_posts ?? "—"}</td>
                    <td className="px-4 py-2 text-right">{row.running_total ?? "—"}</td>
                    <td className="px-4 py-2 text-right">{(row.dow_avg ?? 0).toFixed(1)}</td>
                    <td className="px-4 py-2 text-right">{(row.dow_weight ?? 0).toFixed(3)}</td>
                    <td className={cn(
                      "px-4 py-2 text-right font-mono",
                      row.status === "ahead" && "text-success",
                      row.status === "behind" && "text-destructive",
                      row.status === "on_pace" && "text-muted-foreground",
                    )}>
                      {row.deviation != null ? `${row.deviation > 0 ? "+" : ""}${row.deviation.toFixed(1)}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-center">
                      {row.status === "ahead" && <span className="text-success">&#9650;</span>}
                      {row.status === "behind" && <span className="text-destructive">&#9660;</span>}
                      {row.status === "on_pace" && <span className="text-muted-foreground">&#9679;</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-6 py-8 text-center text-sm text-muted-foreground">No pacing data yet</p>
        )}
      </div>

      {/* DOW Averages Heatmap + Pace Acceleration */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* DOW Heatmap */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            DOW Averages Heatmap
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Historical average posts per day of the week. Greener = more posts typically. Based on recency-weighted data — recent weeks count more than older ones.</p>
          {dowAvg && Array.isArray(dowAvg) && dowAvg.length > 0 ? (
            <div className="space-y-4">
              <div>
                <div className="grid grid-cols-7 gap-1.5">
                  {dowAvg.map((d: any, i: number) => {
                    const maxAvg = Math.max(...dowAvg.map((x: any) => x.avg || 0))
                    const minAvg = Math.min(...dowAvg.map((x: any) => x.avg || 0))
                    const range = maxAvg - minAvg || 1
                    const intensity = ((d.avg || 0) - minAvg) / range
                    return (
                      <div
                        key={i}
                        className="rounded border border-border p-2 text-center"
                        style={{
                          backgroundColor: `hsl(${120 * intensity}, 40%, ${15 + intensity * 10}%)`,
                        }}
                      >
                        <p className="text-xs font-semibold">{d.day}</p>
                        <p className="mt-0.5 text-lg font-bold">{fmt(d.avg || 0)}</p>
                        <p className="text-[10px] text-muted-foreground">&sigma;{fmt(d.std || 0)} n={d.samples || 0}</p>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">No DOW data yet</p>
          )}
        </div>

        {/* Pace Acceleration */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Pace Acceleration
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Is posting speeding up or slowing down compared to earlier in the period? Compares the recent hourly rate to the prior rate.</p>
          {accel ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-muted-foreground">Current Rate</p>
                  <p className="text-2xl font-bold">{accel.current_rate.toFixed(2)}</p>
                  <p className="text-xs text-muted-foreground">posts/hr</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Prior Rate</p>
                  <p className="text-2xl font-bold">{accel.prior_rate.toFixed(2)}</p>
                  <p className="text-xs text-muted-foreground">posts/hr</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                {accel.momentum === "accelerating" && <ArrowUpRight className="h-6 w-6 text-success" />}
                {accel.momentum === "decelerating" && <ArrowDownRight className="h-6 w-6 text-destructive" />}
                {accel.momentum === "steady" && <Minus className="h-6 w-6 text-muted-foreground" />}
                <span className={cn(
                  "text-lg font-semibold capitalize",
                  accel.momentum === "accelerating" && "text-success",
                  accel.momentum === "decelerating" && "text-destructive",
                  accel.momentum === "steady" && "text-muted-foreground",
                )}>
                  {accel.momentum}
                </span>
              </div>
              {/* Momentum bar */}
              <div>
                <p className="mb-1 text-xs text-muted-foreground">Momentum</p>
                <div className="h-3 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      accel.momentum === "accelerating" ? "bg-success" :
                      accel.momentum === "decelerating" ? "bg-destructive" : "bg-muted-foreground"
                    )}
                    style={{
                      width: `${Math.min(100, Math.max(5, (accel.current_rate / Math.max(accel.prior_rate, 0.01)) * 50))}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">No acceleration data yet</p>
          )}
        </div>
      </div>

      {/* Confidence Bands + Ensemble Breakdown */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Confidence Bands */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Confidence Bands
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Our model's best guess at which bracket will win, ranked by probability. The wider the gap between #1 and #2, the more confident the prediction.</p>
          {bands && bands.length > 0 ? (
            <div className="space-y-4">
              <div className="rounded border border-primary/30 bg-primary/5 p-3 text-center">
                <p className="text-xs text-muted-foreground">Projected Winner</p>
                <p className="text-xl font-bold text-primary">{bands[0]?.bracket}</p>
                <p className="text-sm text-muted-foreground">
                  Confidence: {fmt((bands[0]?.confidence || bands[0]?.probability || 0) * 100)}%
                </p>
              </div>
              <div className="space-y-2">
                {bands
                  .slice(0, 3)
                  .map((b, i) => {
                    const pct = (b.probability * 100)
                    return (
                      <div key={i} className="space-y-0.5">
                        <div className="flex items-center justify-between text-sm">
                          <span className="font-medium">{b.bracket}</span>
                          <span className="font-mono text-muted-foreground">{fmt(pct)}%</span>
                        </div>
                        <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary transition-all"
                            style={{ width: `${Math.min(pct * 2, 100)}%` }}
                          />
                        </div>
                      </div>
                    )
                  })}
              </div>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">No confidence data yet</p>
          )}
        </div>

        {/* Ensemble Sub-Model Breakdown */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Ensemble Sub-Model Breakdown
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Four prediction models each estimate the final post count. Their outputs are blended using weights that shift as the week progresses — early week trusts history, late week trusts current pace.</p>
          {ensemble && Array.isArray(ensemble) && ensemble.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground">
                    <th className="py-2 text-left">Model</th>
                    <th className="py-2 text-right">Projection</th>
                    <th className="py-2 text-right">Weight</th>
                    <th className="py-2 text-right">Contribution</th>
                  </tr>
                </thead>
                <tbody>
                  {ensemble.map((m: any, i: number) => (
                    <tr key={i} className="border-b border-border last:border-0">
                      <td className="py-2 font-medium">{m.model}</td>
                      <td className="py-2 text-right font-mono">{fmt(m.projection || 0)}</td>
                      <td className="py-2 text-right font-mono">{fmt(m.weight || 0)}%</td>
                      <td className="py-2 text-right font-mono">{fmt(m.contribution || 0)}</td>
                    </tr>
                  ))}
                  <tr className="bg-muted/30 font-semibold">
                    <td className="py-2">Ensemble Average</td>
                    <td className="py-2 text-right font-mono">{fmt(pacing?.ensemble_avg || 0)}</td>
                    <td className="py-2 text-right font-mono">100%</td>
                    <td className="py-2 text-right font-mono">{fmt(pacing?.ensemble_avg || 0)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">No ensemble data yet</p>
          )}
        </div>
      </div>

      {/* Current + Future Auction Cards */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {[
          { label: "Current Auction", data: pacing?.current_auction, desc: "Live stats for the active auction period. Shows running total, pace, regime, and which bracket the model vs the market thinks will win." },
          { label: "Next Auction", data: pacing?.next_auction, desc: "Upcoming auction period. Shows running total, pace, regime, and which bracket the model vs the market thinks will win." },
        ].map(({ label, data, desc }) => (
          <div key={label} className="rounded-lg border border-border bg-card p-6">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              {label}
            </h2>
            <p className="mt-1 mb-3 text-xs text-muted-foreground">{desc}</p>
            {data ? (
              <div className="space-y-3 text-sm">
                {data.period && (
                  <div className="flex justify-between border-b border-border pb-2">
                    <span className="text-muted-foreground">Period</span>
                    <span className="font-mono text-xs">{data.period}</span>
                  </div>
                )}
                {data.title && (
                  <div className="flex justify-between border-b border-border pb-2">
                    <span className="text-muted-foreground">Market</span>
                    <span className="text-xs max-w-[250px] truncate">{data.title}</span>
                  </div>
                )}
                <div className="flex justify-between border-b border-border pb-2">
                  <span className="text-muted-foreground">Running Total</span>
                  <span className="font-bold">{data.running_total ?? 0}</span>
                </div>
                <div className="flex justify-between border-b border-border pb-2">
                  <span className="text-muted-foreground">Days</span>
                  <span>{data.days_elapsed ?? 0} elapsed / {data.days_remaining ?? 7} left</span>
                </div>
                {data.regime && (
                  <div className="flex justify-between border-b border-border pb-2">
                    <span className="text-muted-foreground">Regime</span>
                    <span className={cn(
                      "rounded px-1.5 py-0.5 text-xs font-medium",
                      data.regime?.label === "HIGH" || data.regime?.label === "SURGE" ? "bg-success/20 text-success" :
                      data.regime?.label === "LOW" || data.regime?.label === "QUIET" ? "bg-destructive/20 text-destructive" :
                      "bg-muted text-muted-foreground"
                    )}>
                      {data.regime?.label || "NORMAL"} (z={data.regime?.zscore?.toFixed(2) ?? 0})
                    </span>
                  </div>
                )}
                {data.projected_winner && (
                  <div className="flex justify-between border-b border-border pb-2">
                    <span className="text-muted-foreground">Projected Winner</span>
                    <span className="font-semibold text-primary">{data.projected_winner}</span>
                  </div>
                )}
                {data.market_implied_winner && (
                  <div className="flex justify-between border-b border-border pb-2">
                    <span className="text-muted-foreground">Market-Implied</span>
                    <span>{data.market_implied_winner}</span>
                  </div>
                )}
                {data.ensemble_avg != null && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Ensemble Avg</span>
                    <span className="font-bold">{data.ensemble_avg} posts</span>
                  </div>
                )}
              </div>
            ) : (
              <p className="py-4 text-center text-sm text-muted-foreground">No data yet</p>
            )}
          </div>
        ))}
      </div>

      {/* Open Positions */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Open Positions ({openPositions.length})
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Your active bets in this auction. Shows what you'd win if each position resolves YES — each share pays out $1.00.</p>
        </div>
        {openPositions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-6 py-2 text-left">Side</th>
                  <th className="px-6 py-2 text-left">Bracket</th>
                  <th className="px-6 py-2 text-right">Shares</th>
                  <th className="px-6 py-2 text-right">Avg Price</th>
                  <th className="px-6 py-2 text-right">Cost</th>
                  <th className="px-6 py-2 text-right">Potential Payout</th>
                  <th className="px-6 py-2 text-right">Potential Profit</th>
                  <th className="px-6 py-2 text-right">ROI</th>
                  <th className="px-6 py-2 text-right">Optimal Entry</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((p, i) => {
                  const cost = p.size * p.avg_price
                  const payout = p.size * 1.0
                  const profit = payout - cost
                  const roi = cost > 0 ? (profit / cost) * 100 : 0
                  return (
                    <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/50">
                      <td className="px-6 py-3">
                        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${p.side === "BUY" ? "bg-success/20 text-success" : "bg-destructive/20 text-destructive"}`}>
                          {p.side}
                        </span>
                      </td>
                      <td className="px-6 py-3 font-medium">{p.bracket}</td>
                      <td className="px-6 py-3 text-right">{fmt(p.size)}</td>
                      <td className="px-6 py-3 text-right">{fmt(p.avg_price * 100)}&cent;</td>
                      <td className="px-6 py-3 text-right">{formatCurrency(cost)}</td>
                      <td className="px-6 py-3 text-right text-success">{formatCurrency(payout)}</td>
                      <td className="px-6 py-3 text-right font-medium text-success">+{formatCurrency(profit)}</td>
                      <td className="px-6 py-3 text-right font-medium text-success">+{roi.toFixed(0)}%</td>
                      <td className="px-6 py-3 text-right text-xs text-muted-foreground">--</td>
                    </tr>
                  )
                })}
                <tr className="bg-muted/30 font-medium">
                  <td className="px-6 py-3" colSpan={4}>Total</td>
                  <td className="px-6 py-3 text-right">{formatCurrency(totalInvested)}</td>
                  <td className="px-6 py-3 text-right text-success">{formatCurrency(openPositions.reduce((s, p) => s + p.size, 0))}</td>
                  <td className="px-6 py-3 text-right text-success">+{formatCurrency(potentialWin)}</td>
                  <td className="px-6 py-3 text-right text-success">
                    +{totalInvested > 0 ? ((potentialWin / totalInvested) * 100).toFixed(0) : 0}%
                  </td>
                  <td className="px-6 py-3" />
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-6 py-8 text-center text-sm text-muted-foreground">No open positions</p>
        )}
      </div>

      {/* Signals */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Recent Signals ({mySignals.length})
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Trade signals generated by the 4-model ensemble. Each signal shows the model's probability vs the market price, the edge (difference), and the Kelly-sized bet amount.</p>
        </div>
        {mySignals.length > 0 ? (
          <div className="max-h-[400px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-6 py-2 text-left">Status</th>
                  <th className="px-6 py-2 text-left">Bracket</th>
                  <th className="px-6 py-2 text-left">Model</th>
                  <th className="px-6 py-2 text-right">Ensemble Prob</th>
                  <th className="px-6 py-2 text-right">Market Price</th>
                  <th className="px-6 py-2 text-right">Edge</th>
                  <th className="px-6 py-2 text-right">Kelly %</th>
                </tr>
              </thead>
              <tbody>
                {mySignals.map((s, i) => (
                  <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/50">
                    <td className="px-6 py-2.5">
                      <span className={`h-2 w-2 inline-block rounded-full ${s.approved ? "bg-success" : "bg-muted-foreground"}`} />
                      <span className="ml-2 text-xs">{s.approved ? "Executed" : "Pending"}</span>
                    </td>
                    <td className="px-6 py-2.5 font-medium">{s.bracket}</td>
                    <td className="px-6 py-2.5">
                      <span className="rounded bg-muted px-1.5 py-0.5 text-xs">4-Model Ensemble</span>
                    </td>
                    <td className="px-6 py-2.5 text-right">{(s.model_prob * 100).toFixed(1)}%</td>
                    <td className="px-6 py-2.5 text-right">{(s.market_price * 100).toFixed(1)}%</td>
                    <td className={cn("px-6 py-2.5 text-right font-medium", s.edge > 0.05 ? "text-success" : "text-muted-foreground")}>
                      +{(s.edge * 100).toFixed(1)}%
                    </td>
                    <td className="px-6 py-2.5 text-right">{(s.kelly_pct * 100).toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-6 py-8 text-center text-sm text-muted-foreground">No signals for this module yet</p>
        )}
      </div>

      {/* Trade History */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Trade History ({trades?.total || 0})
          </h2>
          <p className="mt-1 mb-3 text-xs text-muted-foreground">Log of every trade the bot has executed for this module.</p>
        </div>
        {trades?.data && trades.data.length > 0 ? (
          <div className="max-h-[400px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-6 py-2 text-left">Time</th>
                  <th className="px-6 py-2 text-left">Bracket</th>
                  <th className="px-6 py-2 text-left">Side</th>
                  <th className="px-6 py-2 text-right">Shares</th>
                  <th className="px-6 py-2 text-right">Price</th>
                  <th className="px-6 py-2 text-right">Cost</th>
                  <th className="px-6 py-2 text-right">Executor</th>
                </tr>
              </thead>
              <tbody>
                {trades.data.map((t, i) => (
                  <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/50">
                    <td className="px-6 py-2.5 text-xs text-muted-foreground">{new Date(t.executed_at).toLocaleString()}</td>
                    <td className="px-6 py-2.5 font-medium">{t.bracket}</td>
                    <td className="px-6 py-2.5">
                      <span className={t.side === "BUY" ? "text-success" : "text-destructive"}>{t.side}</span>
                    </td>
                    <td className="px-6 py-2.5 text-right">{fmt(t.size)}</td>
                    <td className="px-6 py-2.5 text-right">{fmt(t.price * 100)}&cent;</td>
                    <td className="px-6 py-2.5 text-right">{formatCurrency(t.size * t.price)}</td>
                    <td className="px-6 py-2.5 text-right text-xs text-muted-foreground">{t.executor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="px-6 py-8 text-center text-sm text-muted-foreground">No trades yet</p>
        )}
      </div>
    </div>
  )
}
