"use client"

import { useParams } from "next/navigation"
import { useState, useEffect, useCallback } from "react"
import { useApi, useMutation } from "@/lib/hooks"
import { formatCurrency, formatDate, formatDateShort, cn } from "@/lib/utils"
import { StatusBadge } from "@/components/shared/status-badge"
import {
  ChevronDown, ChevronUp, RefreshCw, Pause, Play, Power,
  Save, Settings,
} from "lucide-react"
import { DailyPacingTable } from "./components/daily-pacing-table"
import { DowHeatmap, HourlyHeatmap, PaceAcceleration, ConfidenceBands, EnsembleBreakdown } from "./components/pacing-analysis"
import { PriceByDowHourHeatmap, PriceByElapsedDayHeatmap } from "./components/price-heatmaps"
import { PositionsTable } from "./components/positions-table"
import { SignalsTable } from "./components/signals-table"
import { TradeHistory } from "./components/trade-history"

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
  const { data: dataSources } = useApi<any>(
    id ? `/api/modules/${id}/data-sources` : null
  )
  const pacingUrl = id
    ? `/api/modules/${id}/pacing${activeTrackingId ? `?tracking_id=${activeTrackingId}` : ""}`
    : null
  const { data: pacing, refetch: refetchPacing } = useApi<any>(
    pacingUrl, [activeTrackingId], 60000
  )
  const { data: config, refetch: refetchConfig } = useApi<ModuleConfig>(
    id ? `/api/modules/${id}/config` : null
  )
  const { data: priceHeatmaps } = useApi<any>(
    id ? `/api/modules/${id}/price-heatmaps` : null
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
  const wins = closedPositions.filter((p) => (p.realized_pnl || 0) > 0).length
  const winRate = closedPositions.length > 0 ? (wins / closedPositions.length) * 100 : 0

  const bestScenario = openPositions.reduce((best, winningPos) => {
    const winPayout = winningPos.size * 1.0
    const winCost = winningPos.size * winningPos.avg_price
    const othersCost = openPositions
      .filter((p) => p.bracket !== winningPos.bracket)
      .reduce((s, p) => s + (p.size * p.avg_price), 0)
    const netPnl = (winPayout - winCost) - othersCost
    return netPnl > best.netPnl ? { bracket: winningPos.bracket, netPnl, payout: winPayout } : best
  }, { bracket: "", netPnl: -Infinity, payout: 0 })

  const potentialWin = bestScenario.netPnl > -Infinity ? bestScenario.netPnl : 0
  const bestBracket = bestScenario.bracket

  if (!module) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Loading module...
      </div>
    )
  }

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
                <input type="checkbox" checked={localConfig.regime_conditional}
                  onChange={(e) => setLocalConfig({ ...localConfig, regime_conditional: e.target.checked })}
                  className="rounded border-border" />
                <span className="text-sm">Regime-Conditional</span>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5">
                <input type="checkbox" checked={localConfig.parquet_model}
                  onChange={(e) => setLocalConfig({ ...localConfig, parquet_model: e.target.checked })}
                  className="rounded border-border" />
                <span className="text-sm">Parquet Model</span>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5">
                <input type="checkbox" checked={localConfig.auto_optimize_periods}
                  onChange={(e) => setLocalConfig({ ...localConfig, auto_optimize_periods: e.target.checked })}
                  className="rounded border-border" />
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
      {(() => {
        const marketValue = openPositions.reduce((s, p) => s + p.size * (pacing?.market_prices?.[p.bracket] ?? p.avg_price), 0)
        const unrealizedPnl = marketValue - totalInvested
        const fmtDollars = (n: number) => `$${Math.round(Math.abs(n)).toLocaleString()}`
        const fmtDollarsSigned = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.round(Math.abs(n)).toLocaleString()}`
        return (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-6">
            <div className="rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Cost Basis</p>
              <p className="mt-1 text-2xl font-bold">{fmtDollars(totalInvested)}</p>
              <p className="text-xs text-muted-foreground">{openPositions.length} open position{openPositions.length !== 1 ? "s" : ""}</p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Current Value</p>
              <p className="mt-1 text-2xl font-bold">{fmtDollars(marketValue)}</p>
              <p className={cn("text-xs", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(unrealizedPnl)} unrealized
              </p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Best Outcome</p>
              <p className={cn("mt-1 text-2xl font-bold", potentialWin >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(potentialWin)}
              </p>
              <p className="text-xs text-muted-foreground">
                {bestBracket ? `If ${bestBracket} wins` : "No positions"}
              </p>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Bot P&L</p>
              <p className={cn("mt-1 text-2xl font-bold", totalPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(totalPnl)}
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
              <p className="mt-1 text-2xl font-bold">{fmtDollars(module.budget)}</p>
              <p className="text-xs text-muted-foreground">Max: {(module.max_position_pct * 100).toFixed(0)}% per bracket</p>
            </div>
          </div>
        )
      })()}

      {/* Auction Selector */}
      {auctions && auctions.length > 0 && (() => {
        const activeAuctions = auctions.filter((a) => a.status === "active" || a.status === "future")
        const pastAuctions = auctions.filter((a) => a.status === "past")
        const selectedId = activeTrackingId || (pacing as any)?.tracking_id
        const selected = auctions.find((a) => a.tracking_id === selectedId)
        return (
          <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Auction</span>
            <select
              value={selectedId || ""}
              onChange={(e) => setActiveTrackingId(e.target.value)}
              className="flex-1 rounded border border-border bg-background px-3 py-1.5 text-sm"
            >
              {activeAuctions.length > 0 && (
                <optgroup label="Active">
                  {activeAuctions.map((a) => (
                    <option key={a.tracking_id} value={a.tracking_id}>
                      {formatDateShort(a.start_date)} → {formatDateShort(a.end_date)}
                      {` (${a.elapsed_days.toFixed(0)}d elapsed / ${a.remaining_days.toFixed(0)}d left)`}
                    </option>
                  ))}
                </optgroup>
              )}
              {pastAuctions.length > 0 && (
                <optgroup label="Past (Resolved)">
                  {pastAuctions.map((a) => (
                    <option key={a.tracking_id} value={a.tracking_id}>
                      {formatDateShort(a.start_date)} → {formatDateShort(a.end_date)} — Resolved
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            {selected && (
              <span className={cn(
                "rounded px-2 py-0.5 text-xs font-medium",
                selected.status === "active" ? "bg-success/20 text-success" :
                selected.status === "past" ? "bg-muted text-muted-foreground" :
                "bg-primary/20 text-primary"
              )}>
                {selected.status === "active" ? "Active" : selected.status === "past" ? "Resolved" : "Upcoming"}
              </span>
            )}
          </div>
        )
      })()}

      {/* Auction Info + Confidence + Ensemble — 2x2 grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Top Left: Current Auction */}
        {(() => {
          const data = pacing?.current_auction
          return (
            <div className="rounded-lg border border-border bg-card p-6">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Current Auction</h2>
              {data ? (
                <div className="mt-3 space-y-3 text-sm">
                  {data.period && (
                    <div className="flex justify-between border-b border-border pb-2">
                      <span className="text-muted-foreground">Period</span>
                      <span className="text-xs">{data.period?.split(" to ").map((d: string) => formatDate(d.trim())).join(" → ")}</span>
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
          )
        })()}
        {/* Top Right: Confidence Bands */}
        <ConfidenceBands bands={pacing?.confidence_bands} />
        {/* Bottom Left: Next Auction */}
        {(() => {
          const data = pacing?.next_auction
          return (
            <div className="rounded-lg border border-border bg-card p-6">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Next Auction</h2>
              {data ? (
                <div className="mt-3 space-y-3 text-sm">
                  {data.period && (
                    <div className="flex justify-between border-b border-border pb-2">
                      <span className="text-muted-foreground">Period</span>
                      <span className="text-xs">{data.period?.split(" to ").map((d: string) => formatDate(d.trim())).join(" → ")}</span>
                    </div>
                  )}
                  {data.title && (
                    <div className="flex justify-between border-b border-border pb-2">
                      <span className="text-muted-foreground">Market</span>
                      <span className="text-xs max-w-[250px] truncate">{data.title}</span>
                    </div>
                  )}
                  <div className="flex justify-between border-b border-border pb-2">
                    <span className="text-muted-foreground">Days Remaining</span>
                    <span>{data.days_remaining ?? 7}</span>
                  </div>
                </div>
              ) : (
                <p className="py-4 text-center text-sm text-muted-foreground">No upcoming auction</p>
              )}
            </div>
          )
        })()}
        {/* Bottom Right: Ensemble Breakdown */}
        <EnsembleBreakdown ensemble={pacing?.ensemble_breakdown} ensembleAvg={pacing?.ensemble_avg || 0} />
      </div>

      {/* Open Positions (moved up) */}
      <PositionsTable
        openPositions={openPositions}
        totalInvested={totalInvested}
        potentialWin={potentialWin}
        bestBracket={bestBracket}
        marketPrices={pacing?.market_prices}
      />

      {/* Pacing & Heatmaps */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <DailyPacingTable pacing={pacing} />
        <HourlyHeatmap hourlyAvg={pacing?.hourly_heatmap} historicalHourly={pacing?.historical_hourly_heatmap} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <DowHeatmap dowAvg={pacing?.dow_heatmap} />
        <PaceAcceleration accel={pacing?.pace_acceleration} />
      </div>

      <PriceByDowHourHeatmap data={priceHeatmaps?.by_dow_hour} />

      <PriceByElapsedDayHeatmap data={priceHeatmaps?.by_elapsed_day} />

      <SignalsTable signals={mySignals} />

      <TradeHistory trades={trades} />

      {/* Data Sources */}
      <div className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-6 py-3">
          <span className="font-semibold">Data Sources & Context</span>
        </div>
        <div className="p-6 space-y-4">
          {dataSources?.historical_files && (
            <div>
              <p className="text-sm font-medium mb-2">Historical Data Files</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {Object.entries(dataSources.historical_files).map(([name, info]: [string, any]) => (
                  <div key={name} className={cn(
                    "rounded-md border p-2 text-xs",
                    info.exists ? "border-green-500/30 bg-green-500/5" : "border-border bg-accent/20"
                  )}>
                    <span className="font-mono text-[10px]">{name}</span>
                    {info.exists ? (
                      <span className="ml-1 text-green-400">({info.size_kb} KB)</span>
                    ) : (
                      <span className="ml-1 text-muted-foreground">(not imported)</span>
                    )}
                  </div>
                ))}
              </div>
              {dataSources.stats_summary?.total_posts > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Historical: {dataSources.stats_summary.total_posts.toLocaleString()} posts over {dataSources.stats_summary.total_days} days
                  ({dataSources.stats_summary.date_range?.start} to {dataSources.stats_summary.date_range?.end})
                </p>
              )}
            </div>
          )}

          {dataSources?.recent_signal_context && (
            <div>
              <p className="text-sm font-medium mb-2">
                Last Signal Context
                {dataSources.recent_signal_time && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {new Date(dataSources.recent_signal_time).toLocaleString()}
                  </span>
                )}
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {dataSources.recent_signal_context.regime && (
                  <div className="rounded-md bg-accent/30 p-2 text-xs">
                    <span className="text-muted-foreground">Regime:</span>{" "}
                    <span className="font-medium">{dataSources.recent_signal_context.regime}</span>
                    {dataSources.recent_signal_context.regime_override && (
                      <span className="text-yellow-400"> (AI override)</span>
                    )}
                  </div>
                )}
                {dataSources.recent_signal_context.running_total != null && (
                  <div className="rounded-md bg-accent/30 p-2 text-xs">
                    <span className="text-muted-foreground">Count:</span>{" "}
                    <span className="font-medium">{dataSources.recent_signal_context.running_total}</span>
                    <span className="text-muted-foreground"> / {dataSources.recent_signal_context.elapsed_days}d</span>
                  </div>
                )}
                {dataSources.recent_signal_context.signal_mod != null && (
                  <div className="rounded-md bg-accent/30 p-2 text-xs">
                    <span className="text-muted-foreground">Signal Mod:</span>{" "}
                    <span className="font-medium">{dataSources.recent_signal_context.signal_mod}x</span>
                  </div>
                )}
                {dataSources.recent_signal_context.momentum && (
                  <div className="rounded-md bg-accent/30 p-2 text-xs">
                    <span className="text-muted-foreground">Momentum:</span>{" "}
                    <span className="font-medium">{dataSources.recent_signal_context.momentum}</span>
                  </div>
                )}
              </div>

              {dataSources.recent_signal_context.news && (
                <div className="mt-2 rounded-md bg-accent/20 p-2">
                  <p className="text-xs font-medium mb-1">
                    News: {dataSources.recent_signal_context.news.headline_count} headlines,
                    conflict={dataSources.recent_signal_context.news.conflict_score}
                    {dataSources.recent_signal_context.news.schedule_events?.length > 0 && (
                      <>, events: {dataSources.recent_signal_context.news.schedule_events.join(", ")}</>
                    )}
                  </p>
                  {dataSources.recent_signal_context.news.top_headlines?.slice(0, 3).map((h: string, i: number) => (
                    <p key={i} className="text-[10px] text-muted-foreground truncate">{h}</p>
                  ))}
                </div>
              )}

              {dataSources.recent_signal_context.lunarcrush && (
                <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
                  <span>LunarCrush: vel={dataSources.recent_signal_context.lunarcrush.velocity}</span>
                  <span>dom={dataSources.recent_signal_context.lunarcrush.dominance}</span>
                  <span>interactions={dataSources.recent_signal_context.lunarcrush.interactions?.toLocaleString()}</span>
                </div>
              )}

              {dataSources.recent_signal_context.trends && (
                <div className="mt-1 text-xs text-muted-foreground">
                  Google Trends: {dataSources.recent_signal_context.trends.trend} ({dataSources.recent_signal_context.trends.change_pct > 0 ? "+" : ""}{dataSources.recent_signal_context.trends.change_pct}%)
                </div>
              )}

              {dataSources.recent_signal_context.count_divergence?.has_edge && (
                <div className="mt-1 text-xs text-yellow-400">
                  Count divergence: xTracker={dataSources.recent_signal_context.count_divergence.xtracker} vs CNN={dataSources.recent_signal_context.count_divergence.cnn} (diff: {dataSources.recent_signal_context.count_divergence.diff > 0 ? "+" : ""}{dataSources.recent_signal_context.count_divergence.diff})
                </div>
              )}

              {dataSources.recent_signal_context.model_outputs && (
                <div className="mt-2">
                  <p className="text-xs font-medium mb-1">Model Projections</p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(dataSources.recent_signal_context.model_outputs).map(([model, val]: [string, any]) => (
                      <div key={model} className="rounded-md bg-accent/30 px-2 py-1 text-[10px]">
                        <span className="text-muted-foreground">{model}:</span> <span className="font-medium">{Math.round(val)}</span>
                        {dataSources.recent_signal_context.weights?.[model] && (
                          <span className="text-muted-foreground"> ({(dataSources.recent_signal_context.weights[model] * 100).toFixed(0)}%)</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {!dataSources?.recent_signal_context && !dataSources?.historical_files && (
            <p className="text-sm text-muted-foreground">No data yet. Run the import scripts and start the engine.</p>
          )}
        </div>
      </div>
    </div>
  )
}
