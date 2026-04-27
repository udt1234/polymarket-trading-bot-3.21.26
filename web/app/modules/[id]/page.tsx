"use client"

import { useParams } from "next/navigation"
import { useState, useEffect, useCallback } from "react"
import { useApi, useMutation } from "@/lib/hooks"
import { apiFetch } from "@/lib/api"
import { formatCurrency, formatDate, formatDateShort, cn } from "@/lib/utils"
import { StatusBadge } from "@/components/shared/status-badge"
import {
  ChevronDown, ChevronUp, RefreshCw, Pause, Play, Power,
  Save, Settings,
} from "lucide-react"
import { DailyPacingTable } from "./components/daily-pacing-table"
import { DowHeatmap, HourlyHeatmap, ConfidenceBands, EnsembleBreakdown } from "./components/pacing-analysis"
import { PriceByDowHourHeatmap, PriceByElapsedDayHeatmap } from "./components/price-heatmaps"
import { PositionsTable } from "./components/positions-table"
import { SignalsTable } from "./components/signals-table"
import { TradeHistory } from "./components/trade-history"
import { AuctionDeepDive } from "./components/auction-deep-dive"
import { PnlCurve } from "./components/pnl-curve"
import { LastAuctionsPnl } from "./components/last-auctions-pnl"
import { PendingSignalsCard } from "./components/pending-signals-card"
import { PostTimingGrid } from "./components/post-timing-grid"
import { PositionBreakdownChart } from "./components/position-breakdown-chart"
import { KellyTrackerChart } from "./components/kelly-tracker-chart"
import { PostFrequencyChart } from "./components/post-frequency-chart"
import { PriceOverTimeChart } from "./components/price-over-time-chart"
import { VolumePriceChart } from "./components/volume-price-chart"
import { OrderBookDepthChart } from "./components/order-book-depth-chart"
import { LatencyHistogramChart } from "./components/latency-histogram-chart"
import { PostCountDivergenceChart } from "./components/post-count-divergence-chart"
import { CollapsibleCard } from "./components/collapsible-card"
import { BotStatusTimeline } from "./components/bot-status-timeline"

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
  closed_at?: string | null
}

interface ModuleConfig {
  historical_periods: number
  recency_half_life: number
  regime_conditional: boolean
  parquet_model: boolean
  dow_weights_source: "recency" | "equal" | "regime"
  auto_optimize_periods: boolean
  enabled_models: string[]
  strategy_preset: string
  weight_overrides?: Record<string, number>
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
  market_link?: string
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
    id ? `/api/dashboard/recent-signals?limit=50&module_id=${id}` : null
  )
  const { data: trades } = useApi<{ data: Trade[]; total: number }>(
    id ? `/api/trades/?module_id=${id}&limit=20` : null
  )
  const { data: walletAuctions } = useApi<any[]>(
    `/api/dashboard/auctions`
  )
  const { data: paperPositions } = useApi<Position[]>(
    id ? `/api/portfolio/positions?status=all&module_id=${id}` : null
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
  const { data: riskSettings } = useApi<any>("/api/settings/risk")
  const { data: cbState, refetch: refetchCbState } = useApi<{ tripped: boolean; consecutive_losses: number; cooldown_remaining_s: number }>("/api/settings/circuit-breaker", [], 15000)
  const { data: decisionLog } = useApi<any[]>(
    id ? `/api/dashboard/decision-log?module_id=${id}&limit=30` : null,
    [id], 30000
  )

  const [lastRefresh, setLastRefresh] = useState(new Date())
  const [bankrollPct, setBankrollPct] = useState<number | null>(null)
  const [bracketCapPct, setBracketCapPct] = useState<number | null>(null)
  const [configOpen, setConfigOpen] = useState(false)
  const ALL_MODELS = ["pace", "bayesian", "dow", "historical", "hawkes"]
  const PRESETS: Record<string, string[]> = {
    full: ["pace", "bayesian", "dow", "historical", "hawkes"],
    conservative: ["pace", "bayesian"],
    momentum: ["pace", "hawkes", "dow"],
  }
  const [localConfig, setLocalConfig] = useState<ModuleConfig>({
    historical_periods: 9,
    recency_half_life: 4.0,
    regime_conditional: false,
    parquet_model: false,
    dow_weights_source: "recency",
    auto_optimize_periods: false,
    enabled_models: ALL_MODELS,
    strategy_preset: "full",
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

  const mySignals = moduleSignals || []

  // Use real wallet data when available, fallback to paper positions
  const moduleName = module?.name?.toLowerCase() || ""
  const isLive = walletAuctions && walletAuctions.length > 0
  const relevantAuctions = (walletAuctions || []).filter((a: any) => {
    const slug = (a.slug || "").toLowerCase()
    if (moduleName.includes("truth") || moduleName.includes("trump")) {
      return slug.includes("truth-social") || slug.includes("trump")
    }
    if (moduleName.includes("elon")) {
      return slug.includes("elon") || slug.includes("tweets")
    }
    return false
  })

  // Get the selected auction's slug for filtering positions
  const selectedAuctionId = activeTrackingId || (pacing as any)?.tracking_id
  const selectedAuction = auctions?.find((a) => a.tracking_id === selectedAuctionId)
  const selectedSlug = selectedAuction?.market_link
    ? selectedAuction.market_link.split("/").pop()?.toLowerCase() || ""
    : ""

  // Flatten wallet auction bids into position-like objects, tagged with auction slug
  const walletPositions: (Position & { auction_slug?: string })[] = relevantAuctions.flatMap((a: any) =>
    (a.bids || []).map((b: any) => ({
      bracket: b.outcome || b.title?.match(/\d+-\d+|\d+\+|<\d+/)?.[0] || b.title || "",
      side: "BUY",
      size: b.size || 0,
      avg_price: b.avg_price || 0,
      realized_pnl: a.status !== "open" ? (b.pnl || 0) : 0,
      unrealized_pnl: a.status === "open" ? (b.pnl || 0) : 0,
      status: a.status === "open" ? "open" : "closed",
      auction_slug: (a.slug || "").toLowerCase(),
    }))
  )

  // Filter positions: if an auction is selected, show only that auction's positions
  const filteredPositions = selectedSlug && isLive
    ? walletPositions.filter((p) => (p as any).auction_slug === selectedSlug)
    : walletPositions

  const myPositions = isLive ? filteredPositions : (paperPositions || []).filter((p: any) => p.module_id === id)
  const allPositions = isLive ? walletPositions : (paperPositions || []).filter((p: any) => p.module_id === id)
  const openPositions = myPositions.filter((p) => p.status === "open")
  const closedPositions = myPositions.filter((p) => p.status !== "open")

  const totalInvested = openPositions.reduce((s, p) => s + (p.size * p.avg_price), 0)
  const allClosedPositions = allPositions.filter((p) => p.status !== "open")
  const totalPnl = allPositions.reduce((s, p) => s + (p.realized_pnl || 0) + (p.unrealized_pnl || 0), 0)
  const wins = allClosedPositions.filter((p) => (p.realized_pnl || 0) > 0).length
  const winRate = allClosedPositions.length > 0 ? (wins / allClosedPositions.length) * 100 : 0

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
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{module.name}</h1>
          <StatusBadge status={module.status} />
        </div>
        {auctions && auctions.length > 0 && (() => {
          const activeAuctions = auctions.filter((a) => a.status === "active" || a.status === "future")
          const pastAuctions = auctions.filter((a) => a.status === "past")
          const selectedId = activeTrackingId || (pacing as any)?.tracking_id
          const selected = auctions.find((a) => a.tracking_id === selectedId)
          return (
            <div className="flex items-center gap-2">
              <select
                value={selectedId || ""}
                onChange={(e) => setActiveTrackingId(e.target.value)}
                className="w-64 rounded border border-border bg-background px-2 py-1 text-xs"
              >
                {activeAuctions.length > 0 && (
                  <optgroup label="Active">
                    {activeAuctions.map((a) => (
                      <option key={a.tracking_id} value={a.tracking_id}>
                        {formatDateShort(a.start_date)} - {formatDateShort(a.end_date)} ({a.remaining_days.toFixed(0)}d left)
                      </option>
                    ))}
                  </optgroup>
                )}
                {pastAuctions.length > 0 && (
                  <optgroup label="Past">
                    {pastAuctions.map((a) => (
                      <option key={a.tracking_id} value={a.tracking_id}>
                        {formatDateShort(a.start_date)} - {formatDateShort(a.end_date)}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
              {selected?.market_link && (
                <a href={selected.market_link} target="_blank" rel="noopener noreferrer"
                  className="rounded border border-border px-2 py-1 text-xs text-primary hover:bg-accent">
                  Polymarket
                </a>
              )}
            </div>
          )
        })()}
        <div className="flex items-center gap-2">
          <button onClick={() => { refetchPacing(); setLastRefresh(new Date()) }}
            className="rounded-md border border-border p-1.5 hover:bg-accent">
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => togglePause()}
            className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1.5 text-xs hover:bg-accent">
            {module.status === "active" ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {module.status === "active" ? "Pause" : "Resume"}
          </button>
          <button
            onClick={() => { if (confirm("Kill this module?")) killSwitch() }}
            className="flex items-center gap-1 rounded-md border border-destructive px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10">
            <Power className="h-3 w-3" />
            Kill
          </button>
        </div>
      </div>

      {/* Circuit Breaker Banner */}
      {cbState?.tripped && (
        <div className="flex items-center justify-between rounded-lg border border-destructive bg-destructive/10 px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="text-lg">🚨</span>
            <div>
              <p className="text-sm font-semibold text-destructive">Circuit Breaker Tripped</p>
              <p className="text-xs text-muted-foreground">
                {cbState.consecutive_losses} consecutive losses · Cooldown: {Math.ceil(cbState.cooldown_remaining_s / 60)}m remaining · All new trades blocked
              </p>
            </div>
          </div>
          <button
            onClick={async () => {
              try {
                await apiFetch("/api/settings/circuit-breaker/reset", { method: "POST" })
                refetchCbState()
              } catch (e) {
                alert("Reset failed")
              }
            }}
            className="rounded-md bg-destructive px-3 py-1.5 text-xs font-medium text-destructive-foreground hover:bg-destructive/90"
          >
            Reset Now
          </button>
        </div>
      )}

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
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground font-semibold uppercase mb-2">Ensemble Models</p>
              <div className="flex flex-wrap items-center gap-4">
                <label className="space-y-1">
                  <span className="text-xs text-muted-foreground">Preset</span>
                  <select
                    value={localConfig.strategy_preset}
                    onChange={(e) => {
                      const preset = e.target.value
                      const models = PRESETS[preset] || ALL_MODELS
                      setLocalConfig({ ...localConfig, strategy_preset: preset, enabled_models: models })
                    }}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  >
                    <option value="full">Full (5 models)</option>
                    <option value="conservative">Conservative (Pace + Bayesian)</option>
                    <option value="momentum">Momentum (Pace + Hawkes + DOW)</option>
                  </select>
                </label>
                {ALL_MODELS.map((model) => (
                  <label key={model} className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={localConfig.enabled_models.includes(model)}
                      onChange={(e) => {
                        const models = e.target.checked
                          ? [...localConfig.enabled_models, model]
                          : localConfig.enabled_models.filter((m) => m !== model)
                        const matchedPreset = Object.entries(PRESETS).find(
                          ([, v]) => v.length === models.length && v.every((m) => models.includes(m))
                        )
                        setLocalConfig({
                          ...localConfig,
                          enabled_models: models,
                          strategy_preset: matchedPreset ? matchedPreset[0] : "custom",
                        })
                      }}
                      className="rounded border-border"
                    />
                    <span className="text-sm capitalize">{model}</span>
                  </label>
                ))}
              </div>
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

      {/* Pending Signals */}
      <CollapsibleCard id="pending-signals" title="Pending Signals">
        <PendingSignalsCard moduleId={module.id} />
      </CollapsibleCard>

      {/* Last 3 Auctions P&L */}
      <CollapsibleCard id="last-auctions-pnl" title="Recent Auctions P&L">
        <LastAuctionsPnl auctions={auctions || []} walletAuctions={relevantAuctions} />
      </CollapsibleCard>

      {/* Module P&L Curve */}
      <CollapsibleCard id="module-pnl" title="Module P&L">
        <PnlCurve
          trades={trades?.data || []}
          openPositions={openPositions}
          closedPositions={closedPositions}
          marketPrices={pacing?.market_prices}
        />
      </CollapsibleCard>

      {/* Summary Cards */}
      {(() => {
        const marketValue = openPositions.reduce((s, p) => s + p.size * (pacing?.market_prices?.[p.bracket] ?? p.avg_price), 0)
        const unrealizedPnl = marketValue - totalInvested
        const realizedPnl = closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0)
        const fmtDollars = (n: number) => `$${Math.round(Math.abs(n)).toLocaleString()}`
        const fmtDollarsSigned = (n: number) => `${n >= 0 ? "+" : "-"}$${Math.round(Math.abs(n)).toLocaleString()}`
        const totalTrades = openPositions.length + closedPositions.length
        const accountBankroll = riskSettings?.bankroll || 1000
        const budgetPct = ((module.budget / accountBankroll) * 100).toFixed(0)

        const recentSignals = (moduleSignals || []).slice(0, 10)
        const bestEdgeSignal = recentSignals.reduce((best: any, s: any) => (!best || (s.edge || 0) > (best.edge || 0)) ? s : best, null)
        const bestEdge = bestEdgeSignal?.edge ? `+${(bestEdgeSignal.edge * 100).toFixed(1)}%` : "—"
        const bestEdgeBracket = bestEdgeSignal?.bracket || ""

        const approvedCount = recentSignals.filter((s: any) => s.approved).length
        const spreadRejected = recentSignals.filter((s: any) => !s.approved && (s.rejection_reason || "").includes("spread")).length
        const spreadHealth = recentSignals.length === 0 ? "—" : spreadRejected === 0 ? "Good" : spreadRejected < recentSignals.length ? "Mixed" : "Dry"
        const spreadColor = spreadHealth === "Good" ? "text-success" : spreadHealth === "Mixed" ? "text-amber-400" : spreadHealth === "Dry" ? "text-destructive" : "text-muted-foreground"

        return (
          <div className="flex flex-wrap gap-4">
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Cost Basis</p>
              <p className="mt-1 text-2xl font-bold">{fmtDollars(totalInvested)}</p>
              <p className="text-xs text-muted-foreground">{openPositions.length} open position{openPositions.length !== 1 ? "s" : ""}</p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Current Value</p>
              <p className="mt-1 text-2xl font-bold">{fmtDollars(marketValue)}</p>
              <p className={cn("text-xs", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(unrealizedPnl)} unrealized
              </p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Unrealized P&L</p>
              <p className={cn("mt-1 text-2xl font-bold", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(unrealizedPnl)}
              </p>
              <p className="text-xs text-muted-foreground">
                {totalInvested > 0 ? `${((unrealizedPnl / totalInvested) * 100).toFixed(1)}% return` : "No positions"}
              </p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Realized P&L</p>
              <p className={cn("mt-1 text-2xl font-bold", realizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(realizedPnl)}
              </p>
              <p className="text-xs text-muted-foreground">{closedPositions.length} closed trade{closedPositions.length !== 1 ? "s" : ""}</p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Win Rate</p>
              <p className="mt-1 text-2xl font-bold">{fmt(winRate)}%</p>
              <p className="text-xs text-muted-foreground">{wins}W / {closedPositions.length - wins}L · {totalTrades} total</p>
            </div>
            {(() => {
              const curBankrollPct = bankrollPct ?? Math.round((module.budget / accountBankroll) * 100)
              const curBudget = Math.round(accountBankroll * curBankrollPct / 100)
              const curBracketPct = bracketCapPct ?? Math.round((module.max_position_pct || 0.15) * 100)
              const curBracketDollars = Math.round(curBudget * curBracketPct / 100)
              return (
                <>
                  <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Bankroll</p>
                    <div className="mt-1 flex items-center gap-0">
                      <input
                        type="number"
                        value={curBankrollPct}
                        onChange={(e) => setBankrollPct(parseFloat(e.target.value) || 0)}
                        onBlur={(e) => {
                          const pct = parseFloat(e.target.value)
                          if (pct > 0 && pct <= 100) {
                            const newBudget = Math.round(accountBankroll * pct / 100)
                            apiFetch(`/api/modules/${module.id}`, { method: "PUT", body: JSON.stringify({ budget: newBudget }) })
                          }
                        }}
                        className="w-10 bg-transparent text-2xl font-bold border-b border-transparent hover:border-border focus:border-primary focus:outline-none"
                      />
                      <span className="text-2xl font-bold">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground">${curBudget} of ${accountBankroll} account</p>
                  </div>
                  <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Bracket Cap</p>
                    <div className="mt-1 flex items-center gap-0">
                      <input
                        type="number"
                        value={curBracketPct}
                        onChange={(e) => setBracketCapPct(parseFloat(e.target.value) || 0)}
                        onBlur={(e) => {
                          const pct = parseFloat(e.target.value)
                          if (pct > 0 && pct <= 100) {
                            apiFetch(`/api/modules/${module.id}`, { method: "PUT", body: JSON.stringify({ max_position_pct: pct / 100 }) })
                          }
                        }}
                        className="w-10 bg-transparent text-2xl font-bold border-b border-transparent hover:border-border focus:border-primary focus:outline-none"
                      />
                      <span className="text-2xl font-bold">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground">${curBracketDollars} of ${curBudget} bankroll</p>
                  </div>
                </>
              )
            })()}
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Spread Health</p>
              <p className={cn("mt-1 text-2xl font-bold", spreadColor)}>{spreadHealth}</p>
              <p className="text-xs text-muted-foreground">
                {recentSignals.length > 0 ? `${approvedCount}/${recentSignals.length} passed` : "No data"}
              </p>
            </div>
            {(() => {
              const accel = pacing?.pace_acceleration as { current_rate?: number; prior_rate?: number; momentum?: string } | undefined
              const momentum = accel?.momentum || "—"
              const cur = accel?.current_rate
              const prior = accel?.prior_rate
              const momColor =
                momentum === "accelerating" ? "text-success" :
                momentum === "decelerating" ? "text-destructive" :
                momentum === "steady" ? "text-muted-foreground" :
                "text-muted-foreground"
              const label = momentum === "—" ? "—" : momentum.charAt(0).toUpperCase() + momentum.slice(1)
              return (
                <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Pace Acceleration</p>
                  <p className={cn("mt-1 text-2xl font-bold capitalize", momColor)}>{label}</p>
                  <p className="text-xs text-muted-foreground">
                    {cur != null && prior != null
                      ? `${cur.toFixed(2)} now vs ${prior.toFixed(2)} prior posts/hr`
                      : "No data"}
                  </p>
                </div>
              )
            })()}
          </div>
        )
      })()}

      {/* Top Analysis Row — Current Auction + Confidence Bands */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
        <CollapsibleCard id="current-auction" title="Current Auction">
        {(() => {
          const data = pacing?.current_auction
          const selectedAuc = auctions?.find((a) => a.tracking_id === (activeTrackingId || (pacing as any)?.tracking_id))
          // Active auctions = auctions where we currently have open positions (bids in unresolved auctions)
          const activeAucs = (auctions || []).filter((a) => {
            const aSlug = a.market_link?.split("/").pop()?.toLowerCase() || ""
            const walletAuc = relevantAuctions.find((wa: any) => {
              const waSlug = (wa.slug || "").toLowerCase()
              if (aSlug && waSlug === aSlug) return true
              if ((wa.end_date || "").slice(0, 10) === a.end_date) return true
              return false
            })
            return walletAuc?.status === "open" && (walletAuc?.bid_count || 0) > 0
          }).sort((a, b) => a.end_date.localeCompare(b.end_date))
          return (
            <div className="rounded-lg border border-border bg-card p-6 h-full">
              <div className="flex items-center gap-2 mb-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Current Auction</h2>
                {selectedAuc?.market_link && (
                  <a href={selectedAuc.market_link} target="_blank" rel="noopener noreferrer"
                    className="text-primary hover:text-primary/80 text-sm">
                    &#128279;
                  </a>
                )}
              </div>
              {data ? (
                <div className="space-y-3 text-sm">
                  {data.period && (
                    <div className="flex justify-between border-b border-border pb-2">
                      <span className="text-muted-foreground">Period</span>
                      <span className="text-xs">{data.period?.split(" to ").map((d: string) => formatDate(d.trim())).join(" -> ")}</span>
                    </div>
                  )}

                  <div className="pt-2">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70 mb-2">XTracker</div>
                    <div className="space-y-2">
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
                        <div className="flex justify-between border-b border-border pb-2">
                          <span className="text-muted-foreground">Ensemble Avg</span>
                          <span className="font-bold">{data.ensemble_avg} posts</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {data.truth_social_direct !== undefined && data.truth_social_direct !== null && (
                    <div className="pt-3">
                      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70 mb-2">Truth Social (Direct)</div>
                      <div className="space-y-2">
                        <div className="flex justify-between border-b border-border pb-2">
                          <span className="text-muted-foreground">Direct Count</span>
                          <span className="font-bold">
                            {data.truth_social_direct.count ?? "—"}
                          </span>
                        </div>
                        {data.truth_social_direct.diff_vs_xtracker != null && (
                          <div className="flex justify-between border-b border-border pb-2">
                            <span className="text-muted-foreground">Diff vs xTracker</span>
                            <span className={cn(
                              "font-medium",
                              data.truth_social_direct.diff_vs_xtracker === 0 ? "text-muted-foreground" :
                              Math.abs(data.truth_social_direct.diff_vs_xtracker) > 2 ? "text-destructive" :
                              "text-warning"
                            )}>
                              {data.truth_social_direct.diff_vs_xtracker > 0 ? "+" : ""}{data.truth_social_direct.diff_vs_xtracker}
                            </span>
                          </div>
                        )}
                        {data.truth_social_direct.latest_post_at && (
                          <div className="flex justify-between border-b border-border pb-2">
                            <span className="text-muted-foreground">Latest Post</span>
                            <span className="text-xs">{new Date(data.truth_social_direct.latest_post_at).toLocaleString()}</span>
                          </div>
                        )}
                        {data.truth_social_direct.error && (
                          <div className="text-xs text-destructive">Error: {data.truth_social_direct.error}</div>
                        )}
                        <div className="text-[10px] text-muted-foreground/60">Source: truthsocial.com/api/v1</div>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <p className="py-4 text-center text-sm text-muted-foreground">No data yet</p>
              )}

              {/* Bot Status Timeline — replaces raw log dump with human-readable status */}
              <BotStatusTimeline
                decisionLog={decisionLog || []}
                openPositions={openPositions}
                signals={moduleSignals || []}
                regimeLabel={data?.regime?.label}
                projectedWinner={data?.projected_winner}
                ensembleAvg={data?.ensemble_avg}
                marketPrices={pacing?.market_prices}
              />


              {/* Active Auctions — auctions where we currently hold open positions */}
              {activeAucs.length > 0 && (
                <div className="mt-4 pt-3 border-t border-border">
                  <p className="text-[10px] font-semibold uppercase text-muted-foreground mb-2">Active Auctions</p>
                  <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
                    {activeAucs.map((a) => {
                      const aSlug = a.market_link?.split("/").pop()?.toLowerCase() || ""
                      const walletAuc = relevantAuctions.find((wa: any) => {
                        const waSlug = (wa.slug || "").toLowerCase()
                        if (aSlug && waSlug === aSlug) return true
                        if ((wa.end_date || "").slice(0, 10) === a.end_date) return true
                        return false
                      })
                      const cost = (walletAuc?.bids || []).reduce((s: number, b: any) => s + (b.size || 0) * (b.avg_price || 0), 0)
                      const pnl = walletAuc?.unrealized_pnl ?? walletAuc?.total_pnl ?? 0
                      const bidCount = walletAuc?.bid_count || 0
                      const isSelected = (activeTrackingId || (pacing as any)?.tracking_id) === a.tracking_id
                      return (
                        <button
                          key={a.tracking_id}
                          onClick={() => setActiveTrackingId(a.tracking_id)}
                          className={cn(
                            "rounded border p-1.5 text-center text-[9px] transition-colors",
                            isSelected ? "border-primary bg-primary/10" : "border-border bg-muted/30",
                            "hover:opacity-80",
                          )}
                        >
                          <p className="font-semibold text-foreground">{formatDateShort(a.start_date).replace(/, \d{4}$/, "")}</p>
                          <p className="text-[8px] text-muted-foreground">{bidCount} bracket{bidCount === 1 ? "" : "s"}</p>
                          <p className={cn("font-bold", pnl > 0 ? "text-success" : pnl < 0 ? "text-destructive" : "text-muted-foreground")}>
                            {pnl !== 0 ? (pnl > 0 ? "+" : "") + formatCurrency(pnl) : `$${Math.round(cost)}`}
                          </p>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )
        })()}
        </CollapsibleCard>
        <CollapsibleCard id="confidence-bands" title="Confidence Bands">
          <ConfidenceBands bands={pacing?.confidence_bands} allProbs={pacing?.all_bracket_probs} />
        </CollapsibleCard>
      </div>

      {/* Second Analysis Row — Ensemble Breakdown (full width; Pace moved to KPI tile) */}
      <CollapsibleCard id="ensemble-breakdown" title="Ensemble Sub-Model Breakdown">
        <EnsembleBreakdown
          ensemble={pacing?.ensemble_breakdown}
          ensembleAvg={pacing?.ensemble_avg || 0}
          weightOverrides={config?.weight_overrides}
          onSaveWeights={async (overrides) => {
            if (!id) return
            await apiFetch(`/api/settings/module-configs/${id}`, {
              method: "PUT",
              body: JSON.stringify({ weight_overrides: overrides }),
            })
            refetchConfig()
          }}
        />
      </CollapsibleCard>

      {/* New Module Analytics Charts */}
      {(() => {
        const allSignals = (moduleSignals || []).map((s: any) => s.bracket).filter(Boolean)
        const uniqueBrackets = Array.from(new Set(allSignals)) as string[]
        const hourlyData = (pacing?.hourly_counts || []).map((h: any) => ({
          hour_label: h.hour_label || h.label || "",
          count: h.count || 0,
          price: pacing?.market_prices ? Object.values(pacing.market_prices)[0] as number : undefined,
        }))
        const timingData = (pacing?.dow_hour_heatmap || []).map((c: any) => ({
          dow: c.dow,
          hour: c.hour,
          count: c.avg || 0,
          samples: c.samples || 0,
        }))
        return (
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CollapsibleCard id="position-breakdown" title="Position Breakdown">
                <PositionBreakdownChart positions={[...openPositions, ...closedPositions]} />
              </CollapsibleCard>
              <CollapsibleCard id="kelly-tracker" title="Kelly Sizing Tracker">
                <KellyTrackerChart moduleId={module.id} />
              </CollapsibleCard>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <CollapsibleCard id="volume-price" title="Volume vs Price">
                <VolumePriceChart moduleId={module.id} />
              </CollapsibleCard>
              <CollapsibleCard id="order-book-depth" title="Order Book Depth">
                <OrderBookDepthChart moduleId={module.id} />
              </CollapsibleCard>
            </div>
            <CollapsibleCard id="latency-histogram" title="Signal-to-Fill Latency">
              <LatencyHistogramChart moduleId={module.id} />
            </CollapsibleCard>
            <CollapsibleCard id="post-timing-heatmap" title="Post Timing Heatmap">
              <PostTimingGrid data={timingData} />
            </CollapsibleCard>
            <CollapsibleCard id="post-frequency" title="Post Frequency">
              <PostFrequencyChart hourlyData={hourlyData} />
            </CollapsibleCard>
            {uniqueBrackets.length > 0 && (
              <CollapsibleCard id="price-over-time" title="Price Over Time">
                <PriceOverTimeChart moduleId={module.id} brackets={uniqueBrackets} />
              </CollapsibleCard>
            )}
            {(moduleName.includes("truth") || moduleName.includes("trump")) && (
              <CollapsibleCard id="post-count-divergence" title="xTracker vs Truth Social Direct">
                <PostCountDivergenceChart moduleId={module.id} trackingId={activeTrackingId || (pacing as any)?.tracking_id} />
              </CollapsibleCard>
            )}
          </div>
        )
      })()}

      {/* Pacing detail — Daily table + DOW heatmap */}
      <CollapsibleCard id="daily-pacing" title="Daily Pacing">
        <DailyPacingTable pacing={pacing} />
      </CollapsibleCard>
      <CollapsibleCard id="dow-heatmap" title="DOW Averages Heatmap">
        <DowHeatmap dowAvg={pacing?.dow_heatmap} />
      </CollapsibleCard>
      {/* Open Positions */}
      <CollapsibleCard id="open-positions" title="Open Positions">
        <PositionsTable
          openPositions={openPositions}
          totalInvested={totalInvested}
          potentialWin={potentialWin}
          bestBracket={bestBracket}
          marketPrices={pacing?.market_prices}
          auctionLabel={selectedAuction ? `${formatDateShort(selectedAuction.start_date)} - ${formatDateShort(selectedAuction.end_date)}` : undefined}
        />
      </CollapsibleCard>

      {/* Closed Positions */}
      {closedPositions.length > 0 && (
        <CollapsibleCard id="closed-positions" title={`Closed Positions (${closedPositions.length})`}>
        <div className="rounded-lg border border-border bg-card">
          <div className="border-b border-border px-6 py-4">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Closed Positions ({closedPositions.length})
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-6 py-2 text-left">Bracket</th>
                  <th className="px-6 py-2 text-right">Shares</th>
                  <th className="px-6 py-2 text-right">Avg Price</th>
                  <th className="px-6 py-2 text-right">Cost</th>
                  <th className="px-6 py-2 text-right">P&L</th>
                </tr>
              </thead>
              <tbody>
                {closedPositions.map((p, i) => {
                  const cost = p.size * p.avg_price
                  const pnl = p.realized_pnl || 0
                  return (
                    <tr key={i} className="border-b border-border last:border-0">
                      <td className="px-6 py-2 font-medium">{p.bracket}</td>
                      <td className="px-6 py-2 text-right">{fmt(p.size)}</td>
                      <td className="px-6 py-2 text-right">{fmt(p.avg_price * 100)}¢</td>
                      <td className="px-6 py-2 text-right">{formatCurrency(cost)}</td>
                      <td className={cn("px-6 py-2 text-right font-medium", pnl >= 0 ? "text-success" : "text-destructive")}>
                        {pnl >= 0 ? "+" : ""}{formatCurrency(pnl)}
                      </td>
                    </tr>
                  )
                })}
                <tr className="bg-muted/30 font-medium">
                  <td className="px-6 py-2" colSpan={4}>Total Realized</td>
                  <td className={cn("px-6 py-2 text-right",
                    closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0) >= 0 ? "text-success" : "text-destructive"
                  )}>
                    {formatCurrency(closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0))}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        </CollapsibleCard>
      )}

      {/* Hourly Heatmap */}
      <CollapsibleCard id="hourly-heatmap" title="Hourly Posts Heatmap">
        <HourlyHeatmap hourlyAvg={pacing?.hourly_heatmap} historicalHourly={pacing?.historical_hourly_heatmap} />
      </CollapsibleCard>

      <CollapsibleCard id="price-by-dow-hour" title="Price by DOW × Hour">
        <PriceByDowHourHeatmap data={priceHeatmaps?.by_dow_hour} />
      </CollapsibleCard>

      <CollapsibleCard id="price-by-elapsed-day" title="Price by Elapsed Day">
        <PriceByElapsedDayHeatmap data={priceHeatmaps?.by_elapsed_day} />
      </CollapsibleCard>

      <CollapsibleCard id="signals-table" title="Signals">
        <SignalsTable signals={mySignals} />
      </CollapsibleCard>

      <CollapsibleCard id="trade-history" title="Trade History">
        <TradeHistory trades={trades} />
      </CollapsibleCard>

      {id && <AuctionDeepDive moduleId={id} />}

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
