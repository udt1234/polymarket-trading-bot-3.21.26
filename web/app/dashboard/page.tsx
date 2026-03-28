"use client"

import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { MetricCard } from "@/components/dashboard/metric-card"
import { PerformanceChart } from "@/components/dashboard/performance-chart"
import { Activity, DollarSign, TrendingUp, BarChart3, Wallet, ChevronDown, ChevronRight } from "lucide-react"
import { formatCurrency, formatDate, cn } from "@/lib/utils"

interface Metrics {
  portfolio_value: number
  total_invested?: number
  total_pnl: number
  win_rate: number
  wins?: number
  losses?: number
  active_modules: number
  open_positions: number
  closed_positions?: number
  wallet_address?: string
  source: string
}

interface EngineStatus {
  running: boolean
  cycle_count: number
  active_modules: number
  circuit_breaker: boolean
}

interface Bid {
  title: string
  outcome: string
  size: number
  avg_price: number
  cur_price: number
  market_value: number
  cost: number
  pnl: number
  pnl_pct: number
}

interface Auction {
  slug: string
  title: string
  status: "open" | "won" | "lost"
  end_date: string
  total_cost: number
  total_value: number
  total_pnl: number
  bid_count: number
  bids: Bid[]
}

interface Signal {
  bracket: string
  edge: number
  model_prob: number
  market_price: number
  kelly_pct: number
  approved: boolean
  market_id?: string
  module_id?: string
  created_at?: string
}

const STATUS_STYLES = {
  open: "bg-primary/20 text-primary",
  won: "bg-success/20 text-success",
  lost: "bg-destructive/20 text-destructive",
}

function AuctionRow({ auction }: { auction: Auction }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="border-b border-border last:border-0">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-accent/50 transition-colors"
      >
        {open ? <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />}
        <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-xs font-medium uppercase", STATUS_STYLES[auction.status])}>
          {auction.status}
        </span>
        <span className="flex-1 truncate text-sm font-medium">{auction.title}</span>
        <span className="shrink-0 text-xs text-muted-foreground">{formatDate(auction.end_date)}</span>
        <span className="shrink-0 text-sm font-medium w-20 text-right">{formatCurrency(auction.total_cost)}</span>
        <span className={cn("shrink-0 text-sm font-medium w-20 text-right", auction.total_pnl >= 0 ? "text-success" : "text-destructive")}>
          {auction.total_pnl >= 0 ? "+" : ""}{formatCurrency(auction.total_pnl)}
        </span>
      </button>
      {open && (
        <div className="bg-muted/30 px-4 pb-3">
          <div className="rounded border border-border bg-card">
            <div className="flex items-center gap-3 border-b border-border px-3 py-1.5 text-xs font-medium text-muted-foreground">
              <span className="flex-1">Position</span>
              <span className="w-14 text-right">Shares</span>
              <span className="w-14 text-right">Avg</span>
              <span className="w-14 text-right">Current</span>
              <span className="w-16 text-right">Value</span>
              <span className="w-16 text-right">P&L</span>
            </div>
            {auction.bids.map((b, i) => (
              <div key={i} className="flex items-center gap-3 border-b border-border px-3 py-2 text-sm last:border-0">
                <span className="flex-1 truncate">
                  <span className="rounded bg-muted px-1 py-0.5 text-xs mr-1">{b.outcome}</span>
                  {b.title.length > 45 ? b.title.slice(0, 45) + "..." : b.title}
                </span>
                <span className="w-14 text-right">{b.size.toFixed(1)}</span>
                <span className="w-14 text-right">{(b.avg_price * 100).toFixed(0)}¢</span>
                <span className="w-14 text-right">{(b.cur_price * 100).toFixed(0)}¢</span>
                <span className="w-16 text-right">{formatCurrency(b.market_value)}</span>
                <span className={cn("w-16 text-right font-medium", b.pnl >= 0 ? "text-success" : "text-destructive")}>
                  {b.pnl >= 0 ? "+" : ""}{formatCurrency(b.pnl)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const { data: metrics } = useApi<Metrics>("/api/dashboard/metrics", [], 30000)
  const { data: engine } = useApi<EngineStatus>("/api/engine/status", [], 15000)
  const { data: auctions } = useApi<Auction[]>("/api/dashboard/auctions", [], 60000)
  const { data: signals } = useApi<Signal[]>("/api/dashboard/recent-signals?limit=10", [], 30000)
  const [filter, setFilter] = useState<"all" | "open" | "won" | "lost">("all")
  const [search, setSearch] = useState("")

  const isLive = metrics?.source === "live"
  const filteredAuctions = (auctions || [])
    .filter(a => filter === "all" || a.status === filter)
    .filter(a => !search || a.title.toLowerCase().includes(search.toLowerCase()) || a.slug.toLowerCase().includes(search.toLowerCase()))

  const openCount = auctions?.filter(a => a.status === "open").length || 0
  const wonCount = auctions?.filter(a => a.status === "won").length || 0
  const lostCount = auctions?.filter(a => a.status === "lost").length || 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">Dashboard</h1>
          {isLive && metrics?.wallet_address && (
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-mono text-primary">
              {metrics.wallet_address.slice(0, 6)}...{metrics.wallet_address.slice(-4)}
            </span>
          )}
        </div>
        {engine && (
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${engine.running ? "bg-success animate-pulse" : "bg-destructive"}`} />
            <span className="text-sm text-muted-foreground">
              {engine.running ? `Engine running (cycle ${engine.cycle_count})` : "Engine stopped"}
            </span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Open Positions Value"
          value={metrics ? formatCurrency(metrics.portfolio_value) : "$0.00"}
          change={isLive ? "Live" : "Paper"}
          icon={isLive ? Wallet : DollarSign}
        />
        <MetricCard
          title="Total Invested"
          value={metrics?.total_invested ? formatCurrency(metrics.total_invested) : "$0.00"}
          change={`${metrics?.open_positions || 0} open · ${metrics?.closed_positions || 0} closed`}
          icon={DollarSign}
        />
        <MetricCard
          title="Total P&L"
          value={metrics ? formatCurrency(metrics.total_pnl) : "$0.00"}
          change={metrics?.total_invested ? `${((metrics.total_pnl / metrics.total_invested) * 100).toFixed(1)}%` : "—"}
          icon={TrendingUp}
        />
        <MetricCard
          title="Win Rate"
          value={metrics ? `${metrics.win_rate.toFixed(1)}%` : "0%"}
          change={metrics?.wins !== undefined ? `${metrics.wins}W / ${metrics.losses}L` : `${metrics?.active_modules || 0} modules`}
          icon={BarChart3}
        />
      </div>

      <PerformanceChart />

      {/* Auctions */}
      <div className="rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3">
          <h2 className="text-lg font-semibold">Auctions</h2>
          <input
            type="text"
            placeholder="Search markets..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded-md border border-input bg-background px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring w-48"
          />
          <div className="ml-auto flex gap-1">
            {([
              { key: "all", label: `All (${auctions?.length || 0})` },
              { key: "open", label: `Open (${openCount})` },
              { key: "won", label: `Won (${wonCount})` },
              { key: "lost", label: `Lost (${lostCount})` },
            ] as const).map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium",
                  filter === f.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-3 border-b border-border px-4 py-1.5 text-xs font-medium text-muted-foreground">
          <span className="w-4" />
          <span className="w-14">Status</span>
          <span className="flex-1">Market</span>
          <span className="w-20 text-right">Date</span>
          <span className="w-20 text-right">Invested</span>
          <span className="w-20 text-right">P&L</span>
        </div>

        {filteredAuctions.length > 0 ? (
          <div className="max-h-[500px] overflow-y-auto">
            {filteredAuctions.map((a) => (
              <AuctionRow key={a.slug} auction={a} />
            ))}
          </div>
        ) : (
          <p className="p-6 text-center text-sm text-muted-foreground">No auctions</p>
        )}
      </div>

      {/* Signals */}
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="mb-4 text-lg font-semibold">Recent Bot Signals</h2>
        {signals && signals.length > 0 ? (
          <div className="space-y-2">
            {signals.map((s, i) => {
              const slug = s.market_id || ""
              const shortSlug = slug.replace(/-/g, " ").replace(/donald trump of truth social posts /i, "TS ").slice(0, 30)
              return (
                <div key={i} className="flex items-start justify-between border-b border-border pb-2 last:border-0">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${s.approved ? "bg-success" : "bg-muted-foreground"}`} />
                      <span className="text-sm font-medium">{s.bracket}</span>
                      <span className={`text-xs ${s.edge > 0.05 ? "text-success" : "text-muted-foreground"}`}>
                        +{(s.edge * 100).toFixed(1)}% edge
                      </span>
                    </div>
                    <div className="ml-4 mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="rounded bg-muted px-1 py-0.5">4-Model Ensemble</span>
                      {shortSlug && <span className="truncate">{shortSlug}</span>}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm">
                      Model: {(s.model_prob * 100).toFixed(1)}% vs Market: {(s.market_price * 100).toFixed(1)}%
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Kelly: {(s.kelly_pct * 100).toFixed(2)}% · {s.approved ? "Executed" : "Pending"}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No signals yet</p>
        )}
      </div>
    </div>
  )
}
