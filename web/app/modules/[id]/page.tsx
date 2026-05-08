"use client"

import { useParams } from "next/navigation"
import { useState, useEffect, useCallback } from "react"
import { useApi, useMutation } from "@/lib/hooks"
import { apiFetch } from "@/lib/api"
import { formatCurrency, formatDate, formatDateShort, cn } from "@/lib/utils"
import {
  ChevronDown, ChevronUp, RefreshCw,
  Save, Settings,
} from "lucide-react"
import { DailyPacingTable } from "./components/daily-pacing-table"
import { DowHeatmap, HourlyHeatmap, ConfidenceBands, EnsembleBreakdown } from "./components/pacing-analysis"
import { BracketAnalysisCard } from "./components/bracket-analysis-card"
import { PriceByDowHourHeatmap, PriceByElapsedDayHeatmap } from "./components/price-heatmaps"
import { PositionsTable } from "./components/positions-table"
import { SignalsTable } from "./components/signals-table"
import { TradeHistory } from "./components/trade-history"
import { AuctionDeepDive } from "./components/auction-deep-dive"
import { PnlCurve } from "./components/pnl-curve"
import { BotHealthBanner } from "./components/bot-health-banner"
import { LiveStatusBadge } from "./components/live-status-badge"
import { StatusDropdown } from "./components/status-dropdown"
import { DynamicConfigForm, type ConfigSchemaField } from "./components/dynamic-config-form"
import { BiddingStrategyPanel } from "./components/bidding-strategy-panel"
import { AuctionTypesEditor } from "./components/auction-types-editor"
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
  stop_loss_pct: number
  take_profit_pct: number
  trailing_stop_pct: number
  max_brackets_per_cycle: number
  min_edge_threshold: number
  floor_brackets_by_running_total: boolean
  auction_aggregate_price_ceiling: number
  historical_blend_weight: number
  historical_winner_half_life_weeks: number
  low_window_kelly_boost: number
  pre_auction_buying_enabled: boolean
  divergence_alerts_enabled: boolean
  divergence_market_price_min: number
  divergence_model_prob_max: number
  divergence_cooldown_hours: number
  manual_regime_override: string
  manual_regime_override_expires_at: string
  manual_regime_override_default_hours: number
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
  market_ids?: string[]
}

function fmt(n: number, decimals = 1): string {
  return parseFloat(n.toFixed(decimals)).toString()
}


export default function ModuleDetailPage() {
  const params = useParams()
  const moduleId = params.id as string

  const { data: modules, refetch: refetchModules } = useApi<ModuleData[]>("/api/modules/")
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
  const [autoSelectedOnce, setAutoSelectedOnce] = useState(false)

  const { data: auctions } = useApi<AuctionTab[]>(
    id ? `/api/modules/${id}/auctions` : null
  )

  // Auto-select a sensible default tracking when the page first loads.
  // Without this, the backend defaults to fetch_active_tracking(handle,...)
  // which picks the earliest-active tracking — for Elon that's the monthly,
  // even when the user is looking at the Spike module that targets 2-day.
  // Priority: active 2-day > active 7-day > the soonest future 2-day > whatever's first.
  // Only runs ONCE per page load so the user can manually override.
  useEffect(() => {
    if (autoSelectedOnce) return
    if (!auctions || auctions.length === 0) return
    if (activeTrackingId) { setAutoSelectedOnce(true); return }
    const dur = (a: any) => {
      try {
        const s = new Date(a.start_date).getTime()
        const e = new Date(a.end_date).getTime()
        return (e - s) / 86400000
      } catch { return 999 }
    }
    const isShortActive = (a: any) => a.status === "active" && dur(a) <= 8
    const isShortFuture = (a: any) => a.status === "future" && dur(a) <= 8
    const pick =
      auctions.find(isShortActive) ||
      auctions.sort((x, y) => x.start_date.localeCompare(y.start_date)).find(isShortFuture) ||
      auctions.find((a: any) => a.status === "active") ||
      auctions[0]
    if (pick?.tracking_id) {
      setActiveTrackingId(pick.tracking_id)
    }
    setAutoSelectedOnce(true)
  }, [auctions, activeTrackingId, autoSelectedOnce])
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
  const { data: configSchema } = useApi<ConfigSchemaField[]>(
    id ? `/api/modules/${id}/config-schema` : null
  )
  const { data: strategyMetadata } = useApi<any[]>(
    id ? `/api/modules/${id}/strategy-metadata` : null
  )
  const { data: priceHeatmaps } = useApi<any>(
    id ? `/api/modules/${id}/price-heatmaps${activeTrackingId ? `?tracking_id=${activeTrackingId}` : ""}` : null,
    [activeTrackingId]
  )
  const { data: auctionHistory } = useApi<any[]>(
    id ? `/api/modules/${id}/auction-history?limit=20` : null,
    [id], 60000,
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
  const MODEL_DESCRIPTIONS: Record<string, string> = {
    pace: "Linear projection: extrapolate current pace to end of week. Best when posting is steady.",
    bayesian: "Bayesian update: blends current pace with historical mean, weighted by elapsed time. Best mid-week.",
    dow: "Day-of-week pacing: weights remaining hours by historical posts-per-(dow,hour) averages.",
    historical: "Plain historical mean of past N weeks. Stable anchor.",
    hawkes: "Self-exciting process: detects post bursts where one post triggers more. Best in SURGE regimes.",
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
    stop_loss_pct: 0.30,
    take_profit_pct: 0.0,
    trailing_stop_pct: 0.30,
    max_brackets_per_cycle: 5,
    min_edge_threshold: 0.02,
    floor_brackets_by_running_total: true,
    auction_aggregate_price_ceiling: 0.65,
    historical_blend_weight: 0.70,
    historical_winner_half_life_weeks: 8.0,
    low_window_kelly_boost: 1.30,
    pre_auction_buying_enabled: false,
    divergence_alerts_enabled: true,
    divergence_market_price_min: 0.20,
    divergence_model_prob_max: 0.05,
    divergence_cooldown_hours: 6.0,
    manual_regime_override: "",
    manual_regime_override_expires_at: "",
    manual_regime_override_default_hours: 1,
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
  // Status changes go through the unified /set-status endpoint via
  // <StatusDropdown />; legacy /toggle and /kill endpoints removed from UI
  // (kill API still exists server-side as an emergency tool).

  const handleSaveConfig = useCallback(async () => {
    await saveConfig(localConfig)
    refetchConfig()
    refetchPacing()
  }, [localConfig, saveConfig, refetchConfig, refetchPacing])

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
  // Numeric Polymarket market_ids that fired during this auction's window.
  // Used to filter paper positions and signals so the Holdings, Why,
  // Activity, and Confidence Bands cards all reflect ONLY the auction
  // selected in the dropdown.
  const selectedMarketIds = new Set<string>(selectedAuction?.market_ids || [])
  const filterByAuction = selectedMarketIds.size > 0

  // Signals scoped to the selected auction (falls back to all when no
  // market_ids are known yet, e.g. brand-new auction with no signals).
  const mySignals = filterByAuction
    ? (moduleSignals || []).filter((s: any) => selectedMarketIds.has(String(s.market_id || "")))
    : (moduleSignals || [])

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

  // Paper positions scoped to the selected auction's markets when known.
  const paperForModule = (paperPositions || []).filter((p: any) => p.module_id === id)
  const paperForSelectedAuction = filterByAuction
    ? paperForModule.filter((p: any) => selectedMarketIds.has(String(p.market_id || "")))
    : paperForModule
  const myPositions = isLive ? filteredPositions : paperForSelectedAuction
  const allPositions = isLive ? walletPositions : paperForModule
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
          <LiveStatusBadge
            displayBadge={(module as any).display_badge}
            inactiveReasonHuman={(module as any).inactive_reason_human}
            inactiveDetail={(module as any).inactive_detail}
          />
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
          <StatusDropdown
            moduleId={module.id}
            currentStatus={module.status}
            displayBadge={(module as any).display_badge}
            onChange={() => { refetchModules(); refetchPacing(); }}
          />
        </div>
      </div>

      {/* Inactive reason banner — when module is inactive, surface why */}
      {module.status === "inactive" && (
        <div className="rounded-lg border border-destructive bg-destructive/10 px-4 py-3">
          <p className="text-sm font-semibold text-destructive">
            Module Inactive
            {(module as any).inactive_reason_human && (
              <span className="font-normal text-foreground/80">
                {" — "}{(module as any).inactive_reason_human}
              </span>
            )}
          </p>
          {(module as any).inactive_detail && (
            <p className="mt-1 text-xs text-muted-foreground">
              {(module as any).inactive_detail}
            </p>
          )}
          {(module as any).inactive_since && (
            <p className="mt-1 text-xs text-muted-foreground">
              Since {new Date((module as any).inactive_since).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {/* Bot Health Banner — always visible, single-glance status */}
      <BotHealthBanner moduleId={module.id} />

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

      {/* Config Panel — for non-ensemble modules, sit side-by-side with the
          Bidding Strategy panel at 1/2 width each. The Configuration panel
          internally still spans full-width when expanded (the dropdown has
          its own grid that uses the inner container's full width). */}
      <div className={!Array.isArray((localConfig as any).enabled_models)
        ? "grid grid-cols-1 lg:grid-cols-2 gap-6 items-start"
        : ""}>
      <div className="rounded-lg border border-border bg-card">
        <button
          onClick={() => setConfigOpen(!configOpen)}
          className="flex w-full items-center justify-between px-6 py-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground hover:bg-accent/50"
        >
          <span className="flex items-center gap-2">
            <Settings className="h-4 w-4" />
            {Array.isArray((localConfig as any).enabled_models) ? "Pacing Configuration" : "Configuration"}
          </span>
          {configOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {configOpen && !Array.isArray((localConfig as any).enabled_models) && (
          <div className="border-t border-border px-6 py-4 space-y-6">
            {/* Auction Types editor — for modules that support multi-auction
                multi-profile pluggable strategies (currently spike_trading).
                Surfaces only when the API returns strategy metadata. */}
            {Array.isArray(strategyMetadata) && strategyMetadata.length > 0 && Array.isArray((localConfig as any).auction_types) && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Auction Types &amp; Bracket Profiles
                </h3>
                <AuctionTypesEditor
                  moduleId={module.id}
                  initialValue={((localConfig as any).auction_types) || []}
                  strategies={strategyMetadata}
                  onSaved={() => { refetchConfig(); refetchPacing(); }}
                />
              </div>
            )}
            {/* Schema-driven config form — module-wide knobs (volume floor,
                bracket cap, max open positions, etc.). Falls back to read-only
                summary if no schema. */}
            {configSchema && configSchema.length > 0 ? (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Module-Wide Settings
                </h3>
                <DynamicConfigForm
                  moduleId={module.id}
                  schema={configSchema}
                  initialValues={(config as any) || {}}
                  onSaved={() => { refetchConfig(); refetchPacing(); }}
                />
              </div>
            ) : (
              <>
                <p className="text-xs text-muted-foreground mb-3">
                  No editable schema declared for this module — showing read-only summary.
                </p>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {Object.entries(localConfig as any)
                    .filter(([k]) => !k.startsWith("_"))
                    .map(([k, v]) => (
                      <div key={k} className="rounded border border-border/60 bg-muted/20 px-3 py-2 text-xs">
                        <div className="font-mono text-[10px] uppercase text-muted-foreground">{k}</div>
                        <div className="mt-0.5 break-words font-medium">
                          {typeof v === "boolean" ? (v ? "true" : "false")
                            : v === null || v === undefined ? <span className="text-muted-foreground">—</span>
                            : Array.isArray(v) ? `[${v.join(", ")}]`
                            : typeof v === "object" ? JSON.stringify(v)
                            : String(v)}
                        </div>
                      </div>
                    ))}
                </div>
              </>
            )}
          </div>
        )}
        {configOpen && Array.isArray((localConfig as any).enabled_models) && (
          <div className="border-t border-border px-6 py-4">
            <details className="mb-4 rounded-md border border-border/60 bg-muted/20 px-4 py-3">
              <summary className="cursor-pointer text-sm font-semibold text-foreground">
                How this bot works (plain English)
              </summary>
              <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
                <p>
                  Every cycle (~5 min), the bot pulls Trump's latest post count from xTracker, runs <strong>{(localConfig.enabled_models || []).length}</strong> forecasting
                  models (<em>{(localConfig.enabled_models || []).join(", ") || "none"}</em>), and blends them into a probability for each of the 11 brackets.
                </p>
                <p>
                  <strong>Floor by Running Total:</strong> brackets the post count has already passed get zeroed out (e.g. with 105 posts in,
                  "0-19" through "80-99" become impossible). The remaining mass is renormalized over the surviving brackets.
                </p>
                <p>
                  <strong>Bracket selection:</strong> the top <strong>{localConfig.max_brackets_per_cycle ?? 5}</strong> brackets by edge (model_prob &minus; market_price)
                  are considered each cycle. Brackets with edge below <strong>{((localConfig.min_edge_threshold ?? 0.02) * 100).toFixed(1)}%</strong> are rejected outright.
                </p>
                <p>
                  <strong>Position sizing:</strong> Kelly Criterion sizes each bid by <code>(model_prob &minus; market_price) / odds</code>, scaled by a
                  fractional Kelly (10-25% based on regime), and capped at the per-bracket exposure limit. The result is multiplied by your bankroll to get the order size.
                </p>
                <p>
                  <strong>Risk gate:</strong> 16 checks must all pass before any order is placed — circuit breaker, daily/weekly loss caps, drawdown,
                  portfolio exposure, single-market exposure, correlated exposure, aggregate negative-EV, duplicate, settlement decay, spread, and liquidity. A signal
                  that fails any one is logged and dropped.
                </p>
                <p>
                  <strong>Order placement:</strong> <em>limit orders only</em>, never market orders. The bot uses the order book to size at most 30% of available depth.
                </p>
                <p>
                  <strong>Exit rules:</strong>
                  {(localConfig.stop_loss_pct ?? 0) > 0
                    ? <> stop loss exits when price drops <strong>{((localConfig.stop_loss_pct ?? 0.30) * 100).toFixed(0)}%</strong> below cost.</>
                    : <> stop loss is <strong>disabled</strong> (set Stop Loss % to enable).</>}
                  {(localConfig.take_profit_pct ?? 0) > 0
                    ? <> Take profit exits at <strong>+{((localConfig.take_profit_pct ?? 0) * 100).toFixed(0)}%</strong> from cost.</>
                    : <> Take profit is <strong>disabled</strong> (winners run to settlement at $1).</>}
                  Time-decay exits trigger after 5 days with negative P&amp;L. Edge-reversal exits when market price overtakes the model probability.
                </p>
                <p>
                  <strong>Settings below</strong>: the top row tunes the <em>forecast</em> (how many past auctions, how to weight them, which models to blend).
                  The "Position & Exit Rules" row tunes <em>buy/sell behavior</em>. Hover any field for an explanation.
                </p>
              </div>
            </details>
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
              <label className="space-y-1" title="How many past weekly auctions feed the model. 9 ≈ 2 months of history. More = stable, fewer = adaptive to recent regime shifts.">
                <span className="text-xs text-muted-foreground">Historical Periods</span>
                <input
                  type="number" min={1} max={52}
                  value={localConfig.historical_periods}
                  onChange={(e) => setLocalConfig({ ...localConfig, historical_periods: +e.target.value })}
                  className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                />
              </label>
              <label className="space-y-1" title="Weeks until a past auction's weight halves. 4 = recent weeks dominate. Higher = treat all history more equally.">
                <span className="text-xs text-muted-foreground">Recency Half-Life</span>
                <input
                  type="number" min={0.5} max={20} step={0.5}
                  value={localConfig.recency_half_life}
                  onChange={(e) => setLocalConfig({ ...localConfig, recency_half_life: +e.target.value })}
                  className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                />
              </label>
              <label className="space-y-1" title="How day-of-week posting averages are computed. Recency = recent weeks weighted higher. Equal = all weeks equal. Regime = only weeks matching current regime.">
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
              <label className="flex items-center gap-2 self-end pb-1.5" title="When ON, day-of-week averages only use past weeks with the same regime (HIGH / NORMAL / QUIET / SURGE / TRANSITION) as right now.">
                <input type="checkbox" checked={localConfig.regime_conditional}
                  onChange={(e) => setLocalConfig({ ...localConfig, regime_conditional: e.target.checked })}
                  className="rounded border-border" />
                <span className="text-sm">Regime-Conditional</span>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5" title="5th ensemble model: compares current week's price pattern to historical winning patterns from cached parquet snapshots.">
                <input type="checkbox" checked={localConfig.parquet_model}
                  onChange={(e) => setLocalConfig({ ...localConfig, parquet_model: e.target.checked })}
                  className="rounded border-border" />
                <span className="text-sm">Parquet Model</span>
              </label>
              <label className="flex items-center gap-2 self-end pb-1.5" title="Automatically picks the best Historical Periods value based on past Brier scores (lower = better calibration).">
                <input type="checkbox" checked={localConfig.auto_optimize_periods}
                  onChange={(e) => setLocalConfig({ ...localConfig, auto_optimize_periods: e.target.checked })}
                  className="rounded border-border" />
                <span className="text-sm">Auto-Optimize</span>
              </label>
            </div>
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground font-semibold uppercase mb-2">Ensemble Models</p>
              <div className="flex flex-wrap items-center gap-4">
                <label className="space-y-1" title="Bundles of ensemble models. Full = all 5. Conservative = Pace + Bayesian only. Momentum = Pace + Hawkes + DOW for surge regimes.">
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
                  <label key={model} className="flex items-center gap-1.5" title={MODEL_DESCRIPTIONS[model] || ""}>
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
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground font-semibold uppercase mb-2">Position & Exit Rules</p>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">
                <label className="space-y-1" title="Exit a position when its price drops by this fraction below the average cost (0.30 = -30%). Set to 0 to disable the stop loss entirely.">
                  <span className="text-xs text-muted-foreground">Stop Loss %</span>
                  <input
                    type="number" min={0} max={1} step={0.05}
                    value={localConfig.stop_loss_pct}
                    onChange={(e) => setLocalConfig({ ...localConfig, stop_loss_pct: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Exit if price drops this much from cost (0 disables)</span>
                </label>
                <label className="space-y-1" title="Exit a position when its price rises by this fraction above the average cost (0.50 = +50%). Set to 0 to disable. Bracket markets pay $1 binary, so disabling can be optimal for high-conviction winners.">
                  <span className="text-xs text-muted-foreground">Take Profit %</span>
                  <input
                    type="number" min={0} max={5} step={0.05}
                    value={localConfig.take_profit_pct}
                    onChange={(e) => setLocalConfig({ ...localConfig, take_profit_pct: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Exit if price rises this much from cost (0 disables)</span>
                </label>
                <label className="space-y-1" title="Maximum number of top-ranked brackets considered per evaluation cycle. The bot still applies risk checks; higher = more diversification, lower = more concentration.">
                  <span className="text-xs text-muted-foreground">Max Brackets / Cycle</span>
                  <input
                    type="number" min={1} max={11} step={1}
                    value={localConfig.max_brackets_per_cycle}
                    onChange={(e) => setLocalConfig({ ...localConfig, max_brackets_per_cycle: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">How many top-ranked brackets to consider per cycle</span>
                </label>
                <label className="space-y-1" title="Minimum edge (model_prob - market_price) needed to approve a signal. Clamped to never drop below the global 2% floor.">
                  <span className="text-xs text-muted-foreground">Min Edge Threshold</span>
                  <input
                    type="number" min={0} max={0.5} step={0.005}
                    value={localConfig.min_edge_threshold}
                    onChange={(e) => setLocalConfig({ ...localConfig, min_edge_threshold: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Reject signals whose edge is below this (0.02 = 2%)</span>
                </label>
                <label className="space-y-1" title="Trailing stop: if a position's price has been at least 5% above cost (ran up) and then falls this fraction below the peak, exit. Locks in profit before the fixed Stop Loss fires deeper in the red. 0 disables.">
                  <span className="text-xs text-muted-foreground">Trailing Stop %</span>
                  <input
                    type="number" min={0} max={1} step={0.05}
                    value={localConfig.trailing_stop_pct}
                    onChange={(e) => setLocalConfig({ ...localConfig, trailing_stop_pct: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Sell at -X% off the peak after a runup (0 disables)</span>
                </label>
                <label className="flex items-center gap-2 self-end pb-1.5" title="When ON, brackets whose upper bound is below the current running post total are zeroed out (mathematically impossible). The remaining mass redistributes to surviving brackets.">
                  <input
                    type="checkbox"
                    checked={localConfig.floor_brackets_by_running_total}
                    onChange={(e) => setLocalConfig({ ...localConfig, floor_brackets_by_running_total: e.target.checked })}
                    className="rounded border-border"
                  />
                  <span className="text-sm">Floor by Running Total</span>
                </label>
              </div>
            </div>

            {/* Auction Cost & Historical Tilt */}
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground font-semibold uppercase mb-2">Auction Cost & Historical Tilt</p>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">
                <label className="space-y-1" title="Hard cap on the SUM of avg_prices across all brackets you hold in a single auction. In a mutually-exclusive bracket market, keeping this sum < ceiling guarantees a positive return when any one wins. Set to 0 to disable (a global floor of 0.65 still applies).">
                  <span className="text-xs text-muted-foreground">Auction $ Ceiling</span>
                  <input
                    type="number" min={0} max={1} step={0.05}
                    value={localConfig.auction_aggregate_price_ceiling}
                    onChange={(e) => setLocalConfig({ ...localConfig, auction_aggregate_price_ceiling: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Sum of avg_prices across held brackets must stay below this</span>
                </label>
                <label className="space-y-1" title="Blend weight between live ensemble and historical bracket-winner frequencies. 0.70 = 70% live ensemble + 30% historical prior. Lower = more reliance on past bracket frequencies.">
                  <span className="text-xs text-muted-foreground">Historical Blend</span>
                  <input
                    type="number" min={0.5} max={1} step={0.05}
                    value={localConfig.historical_blend_weight}
                    onChange={(e) => setLocalConfig({ ...localConfig, historical_blend_weight: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Live ensemble weight (rest goes to historical prior)</span>
                </label>
                <label className="space-y-1" title="Recency half-life for historical bracket-winner frequencies. 8 weeks = a winner from 8 weeks ago has half the weight of last week's. Higher = treat all weeks more equally.">
                  <span className="text-xs text-muted-foreground">Hist Half-Life (wks)</span>
                  <input
                    type="number" min={2} max={26} step={0.5}
                    value={localConfig.historical_winner_half_life_weeks}
                    onChange={(e) => setLocalConfig({ ...localConfig, historical_winner_half_life_weeks: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Half-life for past auction weight decay</span>
                </label>
                <label className="space-y-1" title="When (now.hour, now.dow) is in the historical bottom-quartile price window for a bracket, multiply Kelly by this factor. 1.30 = 30% bigger bet at empirically cheap times. Capped to the 15% per-position limit.">
                  <span className="text-xs text-muted-foreground">Low-Window Boost</span>
                  <input
                    type="number" min={1} max={2} step={0.05}
                    value={localConfig.low_window_kelly_boost}
                    onChange={(e) => setLocalConfig({ ...localConfig, low_window_kelly_boost: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Kelly multiplier in historical-low time windows (1.0 disables)</span>
                </label>
                <label className="flex items-center gap-2 self-end pb-1.5" title="When ON, the bot can also trade against UPCOMING auctions (not yet started). Useful for sniping early-listed brackets at low prices. The historical-blend prior carries the cycle when no live data exists.">
                  <input
                    type="checkbox"
                    checked={localConfig.pre_auction_buying_enabled}
                    onChange={(e) => setLocalConfig({ ...localConfig, pre_auction_buying_enabled: e.target.checked })}
                    className="rounded border-border"
                  />
                  <span className="text-sm">Pre-Auction Buying</span>
                </label>
              </div>
            </div>

            {/* Divergence Alerts */}
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground font-semibold uppercase mb-2">Divergence Alerts (Slack)</p>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-4">
                <label className="flex items-center gap-2 self-end pb-1.5" title="When ON, fire a Slack alert when the market thinks a bracket is likely (>= Market Price Min) but our model thinks it's unlikely (<= Model Prob Max). Alert-only — bot does not auto-trade on divergences.">
                  <input
                    type="checkbox"
                    checked={localConfig.divergence_alerts_enabled}
                    onChange={(e) => setLocalConfig({ ...localConfig, divergence_alerts_enabled: e.target.checked })}
                    className="rounded border-border"
                  />
                  <span className="text-sm">Enable Divergence Alerts</span>
                </label>
                <label className="space-y-1" title="Alert only when market_price for a bracket is at or above this. Lower = more sensitive (more alerts).">
                  <span className="text-xs text-muted-foreground">Market Price Min</span>
                  <input
                    type="number" min={0.05} max={0.5} step={0.05}
                    value={localConfig.divergence_market_price_min}
                    onChange={(e) => setLocalConfig({ ...localConfig, divergence_market_price_min: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Crowd-thinks-it's-likely floor (e.g. 0.20 = 20%)</span>
                </label>
                <label className="space-y-1" title="Alert only when model_prob for a bracket is at or below this. Higher = more sensitive (more alerts).">
                  <span className="text-xs text-muted-foreground">Model Prob Max</span>
                  <input
                    type="number" min={0.005} max={0.20} step={0.005}
                    value={localConfig.divergence_model_prob_max}
                    onChange={(e) => setLocalConfig({ ...localConfig, divergence_model_prob_max: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Model-thinks-it's-unlikely ceiling (e.g. 0.05 = 5%)</span>
                </label>
                <label className="space-y-1" title="Hours between repeat alerts on the same (module, market, bracket). Prevents Slack spam while a divergence persists across cycles.">
                  <span className="text-xs text-muted-foreground">Cooldown (hrs)</span>
                  <input
                    type="number" min={0.5} max={48} step={0.5}
                    value={localConfig.divergence_cooldown_hours}
                    onChange={(e) => setLocalConfig({ ...localConfig, divergence_cooldown_hours: +e.target.value })}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Min hours between repeat alerts on same bracket</span>
                </label>
              </div>
            </div>

            {/* Manual Regime Override */}
            <div className="mt-4 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground font-semibold uppercase mb-2">Manual Regime Override</p>
              <div className="flex flex-wrap items-end gap-4">
                <label className="space-y-1 min-w-[260px]" title="Forces the regime label when you disagree with the statistical detector. Auto-expires after Override Hours and reverts to the detector. Leave blank for no override.">
                  <span className="text-xs text-muted-foreground">Override regime</span>
                  <select
                    value={localConfig.manual_regime_override || ""}
                    onChange={(e) => {
                      const newRegime = e.target.value
                      // When the user picks an override, stamp an expiry
                      // (now + default_hours). When they clear it, also clear
                      // the expiry. This prevents stale "Force NORMAL" from
                      // running for weeks and silently distorting the bot.
                      let expiresAt = ""
                      if (newRegime) {
                        const hours = localConfig.manual_regime_override_default_hours || 24
                        const t = new Date(Date.now() + hours * 3600 * 1000)
                        expiresAt = t.toISOString()
                      }
                      setLocalConfig({
                        ...localConfig,
                        manual_regime_override: newRegime,
                        manual_regime_override_expires_at: expiresAt,
                      })
                    }}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  >
                    <option value="">No override (use detector)</option>
                    <option value="NORMAL">Force NORMAL (allow trading)</option>
                    <option value="QUIET">Force QUIET</option>
                    <option value="LOW">Force LOW</option>
                    <option value="HIGH">Force HIGH</option>
                    <option value="SURGE">Force SURGE</option>
                    <option value="TRANSITION">Force TRANSITION (block trading)</option>
                  </select>
                  <span className="text-[10px] text-muted-foreground">
                    Auto-expires after the duration below — bot reverts to detector.
                  </span>
                </label>
                <label className="space-y-1 min-w-[140px]" title="Hours an override stays active before auto-reverting to the detector. Picking 'Force NORMAL' now sets expiry to now + this many hours. Default 1h (minimum-blast-radius).">
                  <span className="text-xs text-muted-foreground">Override Hours</span>
                  <input
                    type="number" min={1} max={720} step={1}
                    // Show 1 as a placeholder/fallback if the value is empty,
                    // 0, or undefined so the user can never see a blank input
                    // that would silently round to 0 hours and expire instantly.
                    value={localConfig.manual_regime_override_default_hours || 1}
                    onChange={(e) => {
                      // Clamp the typed value to [1, 720] before storing.
                      // Empty / non-numeric / 0 falls back to 1 so we never
                      // build an expires_at = now and silently expire the
                      // override on the very next bot cycle.
                      const raw = parseFloat(e.target.value)
                      const clamped = (!Number.isFinite(raw) || raw < 1)
                        ? 1
                        : Math.min(raw, 720)
                      const updates: Partial<ModuleConfig> = {
                        manual_regime_override_default_hours: clamped,
                      }
                      if (localConfig.manual_regime_override) {
                        const t = new Date(Date.now() + clamped * 3600 * 1000)
                        updates.manual_regime_override_expires_at = t.toISOString()
                      }
                      setLocalConfig({ ...localConfig, ...updates })
                    }}
                    className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
                  />
                  <span className="text-[10px] text-muted-foreground">Default 1h, max 720 (30d)</span>
                </label>
                {localConfig.manual_regime_override && localConfig.manual_regime_override_expires_at && (
                  <div className="flex items-center gap-2 text-[11px] pb-1.5">
                    <span className="text-muted-foreground">Active until:</span>
                    <span className="font-medium text-amber-500">
                      {(() => {
                        try {
                          const d = new Date(localConfig.manual_regime_override_expires_at)
                          const remainingMs = d.getTime() - Date.now()
                          if (remainingMs <= 0) return "expired (will revert next cycle)"
                          const hrs = Math.floor(remainingMs / 3600000)
                          const mins = Math.floor((remainingMs % 3600000) / 60000)
                          return `${hrs}h ${mins}m remaining (${d.toLocaleString()})`
                        } catch { return "—" }
                      })()}
                    </span>
                    <button
                      type="button"
                      onClick={() => setLocalConfig({
                        ...localConfig,
                        manual_regime_override: "",
                        manual_regime_override_expires_at: "",
                      })}
                      className="text-xs underline text-muted-foreground hover:text-destructive"
                    >
                      Clear now
                    </button>
                  </div>
                )}
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
      {/* Bidding Strategy panel — only for non-ensemble modules. Reflects
          live config values; users see how their edits change the strategy. */}
      {!Array.isArray((localConfig as any).enabled_models) && (
        <BiddingStrategyPanel
          config={localConfig as any}
          moduleName={module.name}
        />
      )}
      </div>

      {/* Pending Signals */}
      <CollapsibleCard id="pending-signals" title="Pending Signals">
        <PendingSignalsCard moduleId={module.id} />
      </CollapsibleCard>

      {/* Last 3 Auctions P&L */}
      <CollapsibleCard id="auction-history" title="Auction History (Bot Performance)">
        <div className="rounded-lg border border-border bg-card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-4 py-2 text-left">Period</th>
                  <th className="px-4 py-2 text-left">Bot Held</th>
                  <th className="px-4 py-2 text-right">Cost</th>
                  <th className="px-4 py-2 text-left">Bot Pick</th>
                  <th className="px-4 py-2 text-right">Actual Posts</th>
                  <th className="px-4 py-2 text-left">Actual Bracket</th>
                  <th className="px-4 py-2 text-center">Result</th>
                  <th className="px-4 py-2 text-right">Net P&L</th>
                </tr>
              </thead>
              <tbody>
                {(auctionHistory || []).map((a: any, i: number) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    <td className="px-4 py-2 font-medium text-xs">{a.period}</td>
                    <td className="px-4 py-2 text-xs">
                      {a.no_bet ? <span className="text-muted-foreground italic">No bet</span>
                        : (a.brackets_held || []).join(", ")}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {a.total_cost > 0 ? `$${a.total_cost.toFixed(2)}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-primary">{a.projected_winner || "—"}</td>
                    <td className="px-4 py-2 text-right text-xs">{a.actual_total ?? "—"}</td>
                    <td className="px-4 py-2 text-xs">{a.actual_winner || "—"}</td>
                    <td className="px-4 py-2 text-center text-xs">
                      {a.no_bet
                        ? <span className="text-muted-foreground">—</span>
                        : a.won
                          ? <span className="text-success font-semibold">WON</span>
                          : <span className="text-destructive font-semibold">LOST</span>}
                    </td>
                    <td className={cn(
                      "px-4 py-2 text-right font-medium",
                      a.no_bet ? "text-muted-foreground" :
                      a.net_pnl > 0 ? "text-success" :
                      a.net_pnl < 0 ? "text-destructive" : "text-muted-foreground",
                    )}>
                      {a.no_bet ? "—" :
                       (a.net_pnl >= 0 ? "+" : "") + "$" + Math.abs(a.net_pnl).toFixed(2)}
                    </td>
                  </tr>
                ))}
                {(auctionHistory || []).length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-6 text-center text-muted-foreground text-xs">
                    No resolved auctions yet.
                  </td></tr>
                )}
              </tbody>
              {(auctionHistory || []).length > 0 && (
                <tfoot>
                  <tr className="bg-muted/30 font-medium">
                    <td className="px-4 py-2 text-xs" colSpan={2}>
                      Totals — {(auctionHistory || []).filter((a: any) => !a.no_bet).length} bet · {(auctionHistory || []).filter((a: any) => a.won).length} won
                    </td>
                    <td className="px-4 py-2 text-right">
                      ${(auctionHistory || []).reduce((s: number, a: any) => s + (a.total_cost || 0), 0).toFixed(2)}
                    </td>
                    <td colSpan={4}></td>
                    <td className={cn(
                      "px-4 py-2 text-right",
                      (auctionHistory || []).reduce((s: number, a: any) => s + (a.net_pnl || 0), 0) >= 0 ? "text-success" : "text-destructive",
                    )}>
                      {(() => {
                        const t = (auctionHistory || []).reduce((s: number, a: any) => s + (a.net_pnl || 0), 0)
                        return (t >= 0 ? "+" : "") + "$" + Math.abs(t).toFixed(2)
                      })()}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      </CollapsibleCard>

      <CollapsibleCard id="last-auctions-pnl" title="Recent Auctions P&L">
        <LastAuctionsPnl auctions={auctions || []} walletAuctions={relevantAuctions} />
      </CollapsibleCard>

      {/* Module P&L Curve — filtered to selected auction's markets when known */}
      <CollapsibleCard id="module-pnl" title="Module P&L">
        <PnlCurve
          trades={(trades?.data || []).filter((t: any) =>
            !filterByAuction || selectedMarketIds.has(String(t.market_id || ""))
          )}
          openPositions={openPositions}
          closedPositions={closedPositions}
          marketPrices={pacing?.market_prices}
        />
      </CollapsibleCard>

      {/* Summary Cards */}
      {(() => {
        const marketValue = openPositions.reduce((s, p) => s + p.size * (pacing?.market_prices?.[p.bracket] ?? p.avg_price), 0)
        const unrealizedPnl = marketValue - totalInvested
        // Total shares across all open positions + weighted avg cost per share.
        // size = shares; avg_price = $/share. So total $ / total shares = avg cost.
        const totalShares = openPositions.reduce((s, p) => s + (p.size || 0), 0)
        const avgCostPerShare = totalShares > 0 ? totalInvested / totalShares : 0
        const realizedPnl = closedPositions.reduce((s, p) => s + (p.realized_pnl || 0), 0)
        const fmtDollars = (n: number) => {
          const abs = Math.abs(n)
          if (abs < 1000) return `$${abs.toFixed(2)}`
          return `$${Math.round(abs).toLocaleString()}`
        }
        const fmtDollarsSigned = (n: number) => {
          const abs = Math.abs(n)
          const sign = n >= 0 ? "+" : "-"
          if (abs < 1000) return `${sign}$${abs.toFixed(2)}`
          return `${sign}$${Math.round(abs).toLocaleString()}`
        }
        const totalTrades = openPositions.length + closedPositions.length
        const accountBankroll = riskSettings?.bankroll || 1000
        const budgetPct = ((module.budget / accountBankroll) * 100).toFixed(0)

        const recentSignals = mySignals.slice(0, 10)
        const bestEdgeSignal = recentSignals.reduce((best: any, s: any) => (!best || (s.edge || 0) > (best.edge || 0)) ? s : best, null)
        const bestEdge = bestEdgeSignal?.edge ? `+${(bestEdgeSignal.edge * 100).toFixed(1)}%` : "—"
        const bestEdgeBracket = bestEdgeSignal?.bracket || ""

        const approvedCount = recentSignals.filter((s: any) => s.approved).length
        const spreadRejected = recentSignals.filter((s: any) => !s.approved && (s.rejection_reason || "").includes("spread")).length
        const spreadHealth = recentSignals.length === 0 ? "—" : spreadRejected === 0 ? "Good" : spreadRejected < recentSignals.length ? "Mixed" : "Dry"
        const spreadColor = spreadHealth === "Good" ? "text-success" : spreadHealth === "Mixed" ? "text-amber-400" : spreadHealth === "Dry" ? "text-destructive" : "text-muted-foreground"

        return (
          <div className="flex flex-wrap gap-4">
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Cost Basis</p>
              <p className="mt-1 text-2xl font-bold">{fmtDollars(totalInvested)}</p>
              {totalShares > 0 ? (
                <p className="text-xs text-muted-foreground">
                  {totalShares.toFixed(1)} shares across {openPositions.length} entr{openPositions.length !== 1 ? "ies" : "y"}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">{openPositions.length} open position{openPositions.length !== 1 ? "s" : ""}</p>
              )}
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Current Value</p>
              <p className="mt-1 text-2xl font-bold">{fmtDollars(marketValue)}</p>
              <p className={cn("text-xs", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(unrealizedPnl)} unrealized
              </p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Unrealized P&L</p>
              <p className={cn("mt-1 text-2xl font-bold", unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(unrealizedPnl)}
              </p>
              <p className="text-xs text-muted-foreground">
                {totalInvested > 0 ? `${((unrealizedPnl / totalInvested) * 100).toFixed(1)}% return` : "No positions"}
              </p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Realized P&L</p>
              <p className={cn("mt-1 text-2xl font-bold", realizedPnl >= 0 ? "text-success" : "text-destructive")}>
                {fmtDollarsSigned(realizedPnl)}
              </p>
              <p className="text-xs text-muted-foreground">{closedPositions.length} closed trade{closedPositions.length !== 1 ? "s" : ""}</p>
            </div>
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
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
                  <div className="flex-1 min-w-[180px] max-w-[230px] rounded-lg border border-border bg-card p-4 text-center">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Bankroll</p>
                    <div className="mt-1 flex items-center justify-center gap-0">
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
                        className="w-12 bg-transparent text-center text-2xl font-bold border-b border-transparent hover:border-border focus:border-primary focus:outline-none"
                      />
                      <span className="text-2xl font-bold">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground">${curBudget} of ${accountBankroll} account</p>
                  </div>
                  <div className="flex-1 min-w-[180px] max-w-[230px] rounded-lg border border-border bg-card p-4 text-center">
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">Bracket Cap</p>
                    <div className="mt-1 flex items-center justify-center gap-0">
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
                        className="w-12 bg-transparent text-center text-2xl font-bold border-b border-transparent hover:border-border focus:border-primary focus:outline-none"
                      />
                      <span className="text-2xl font-bold">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground">${curBracketDollars} of ${curBudget} bankroll</p>
                  </div>
                </>
              )
            })()}
            <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
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
              const label =
                momentum === "accelerating" ? "Accel ↑" :
                momentum === "decelerating" ? "Decel ↓" :
                momentum === "steady" ? "Steady" :
                "—"
              // Format posts/hr as "1 post x N.N hrs" (hours per post). E.g. 0.75 -> "1 post x 1.3 hrs"
              const fmtRate = (r?: number) => {
                if (r == null || r <= 0) return "—"
                const hrsPerPost = 1 / r
                return `1 post x ${hrsPerPost.toFixed(1)} hrs`
              }
              return (
                <div className="flex-1 min-w-[150px] max-w-[200px] rounded-lg border border-border bg-card p-4 text-center">
                  <p className="text-xs text-muted-foreground uppercase tracking-wide">Pacing</p>
                  <p className={cn("mt-1 text-2xl font-bold", momColor)}>{label}</p>
                  <p className="text-xs text-muted-foreground">
                    {cur != null && prior != null
                      ? `${fmtRate(cur)} now vs ${fmtRate(prior)} prior`
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
                          <span className="text-muted-foreground">
                            {data.is_complete ? "Actual Winner" : "Projected Winner"}
                          </span>
                          <span className="font-semibold text-primary">{data.projected_winner}</span>
                        </div>
                      )}
                      {data.ensemble_avg != null && (
                        <div className="flex justify-between border-b border-border pb-2">
                          <span className="text-muted-foreground">
                            {data.is_complete ? "Final Count" : "Ensemble Avg"}
                          </span>
                          <span className="font-bold">{data.ensemble_avg} posts</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {data.truth_social_direct && data.truth_social_direct.status !== "not_applicable" && (
                    <div className="pt-3">
                      <div
                        className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/70 mb-2 flex items-center gap-2"
                        title="Independent cross-check of Trump's Truth Social posts. Primary source is CNN's public archive (refreshed every 5 min); falls back to truthsocial.com/api/v1 if CNN is unavailable."
                      >
                        <span>Truth Social (Direct)</span>
                        {data.truth_social_direct.status === "ok" && data.truth_social_direct.source?.includes("cnn") && (
                          <span className="text-success normal-case font-normal">● live (CNN archive)</span>
                        )}
                        {data.truth_social_direct.status === "ok" && !data.truth_social_direct.source?.includes("cnn") && (
                          <span className="text-success normal-case font-normal">● live</span>
                        )}
                        {data.truth_social_direct.status === "stale" && <span className="text-amber-500 normal-case font-normal">● using cached snapshot</span>}
                        {data.truth_social_direct.status === "unavailable" && <span className="text-destructive normal-case font-normal">● unavailable</span>}
                        {data.truth_social_direct.status === "no_data" && <span className="text-muted-foreground normal-case font-normal">● no data</span>}
                      </div>
                      <div className="space-y-2">
                        <div className="flex justify-between border-b border-border pb-2">
                          <span className="text-muted-foreground">Direct Count</span>
                          <span className="font-bold">
                            {data.truth_social_direct.count != null ? data.truth_social_direct.count : "—"}
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
                        {data.truth_social_direct.captured_at && data.truth_social_direct.status === "stale" && (
                          <div className="flex justify-between border-b border-border pb-2">
                            <span className="text-muted-foreground">Snapshot taken</span>
                            <span className="text-xs">{new Date(data.truth_social_direct.captured_at).toLocaleString()}</span>
                          </div>
                        )}
                        {data.truth_social_direct.error && data.truth_social_direct.status !== "ok" && (
                          <div className="space-y-1">
                            <div className="text-[10px] text-amber-500/80 italic">
                              {data.truth_social_direct.status === "stale"
                                ? "Live source rate-limited — falling back to last snapshot. Snapshot job retries every 5 min."
                                : "Both CNN archive and direct truthsocial.com fetches failed. Snapshot job will retry every 5 min. xTracker is unaffected."}
                            </div>
                            <div className="text-[10px] text-muted-foreground/60">
                              Last error: {data.truth_social_direct.error}
                            </div>
                            {data.truth_social_direct.last_attempt_at && (
                              <div className="text-[10px] text-muted-foreground/60">
                                Last attempt: {new Date(data.truth_social_direct.last_attempt_at).toLocaleString()}
                              </div>
                            )}
                          </div>
                        )}
                        <div className="text-[10px] text-muted-foreground/60">Source: {data.truth_social_direct.source}</div>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <p className="py-4 text-center text-sm text-muted-foreground">No data yet</p>
              )}

              {/* Bot Status Timeline — replaces raw log dump with human-readable status */}
              <BotStatusTimeline
                decisionLog={(decisionLog || []).filter((row: any) => {
                  if (!filterByAuction) return true
                  // decision-log rows embed market_id in the message text;
                  // match any 6-8 digit number against the selected market_ids
                  const msg = String(row.message || "")
                  for (const mid of Array.from(selectedMarketIds)) {
                    if (msg.includes(mid)) return true
                  }
                  return false
                })}
                openPositions={openPositions}
                signals={mySignals}
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
          <ConfidenceBands
            bands={pacing?.confidence_bands}
            allProbs={pacing?.all_bracket_probs}
            marketPrices={pacing?.market_prices}
          />
        </CollapsibleCard>
      </div>

      {/* Bracket Analysis (per spec WHALE_BRACKET_CARDS_SPEC.md) — full width,
          generic across all modules. Headline above the card box. */}
      <CollapsibleCard id="bracket-analysis" title="Bracket Analysis">
        <BracketAnalysisCard moduleId={module.id} />
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
        const allSignals = mySignals.map((s: any) => s.bracket).filter(Boolean)
        const uniqueBrackets = Array.from(new Set(allSignals)) as string[]
        // Use hourly_heatmap (avg posts/hr by hour-of-day, returned by /pacing) since
        // raw hourly_counts isn't in the payload. Overlay with current market price for top bracket.
        const topBracketPrice = pacing?.confidence_bands?.[0]?.bracket
          ? pacing?.market_prices?.[pacing.confidence_bands[0].bracket]
          : undefined
        const fmtHr = (h: number) => h === 0 ? "12 AM" : h === 12 ? "12 PM" : h < 12 ? `${h} AM` : `${h - 12} PM`
        const hourlyData = (pacing?.hourly_heatmap || []).map((h: any) => ({
          hour_label: fmtHr(h.hour),
          count: h.avg ?? 0,
          price: topBracketPrice,
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
                <PriceOverTimeChart moduleId={module.id} brackets={uniqueBrackets} trackingId={activeTrackingId} />
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
