"use client"

import { useState } from "react"
import { apiFetch } from "@/lib/api"
import { cn, formatCurrency } from "@/lib/utils"
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  BarChart, Bar,
} from "recharts"
import { Search, FlaskConical, Loader2, TrendingUp, TrendingDown, Target, BarChart3 } from "lucide-react"

interface GammaMarket {
  group_item_title: string
  outcome_prices: string
  clob_token_ids: string
  condition_id: string
  slug: string
}

interface GammaEvent {
  id: string
  title: string
  slug: string
  end_date: string
  volume: number
  markets: GammaMarket[]
}

interface BacktestTrade {
  timestamp: string
  side: string
  size: number
  entry_price: number
  exit_price: number
  pnl: number
  edge: number
  kelly_pct: number
  model_prob: number
  market_price: number
}

interface BacktestResponse {
  id: string
  slug: string
  title: string
  strategy: string
  bankroll: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  pnl_pct: number
  max_drawdown: number
  sharpe: number
  sortino: number
  profit_factor: number
  avg_edge: number
  start_date: string
  end_date: string
  equity_curve: { timestamp: number; value: number }[]
  daily_pnl: { date: string; pnl: number }[]
  trades: BacktestTrade[]
}

const STRATEGIES = [
  { value: "mean_reversion", label: "Mean Reversion" },
  { value: "momentum", label: "Momentum" },
  { value: "ensemble", label: "Ensemble (MR + Mom)" },
]

function StatCard({ label, value, sub, positive }: { label: string; value: string; sub?: string; positive?: boolean }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-xl font-bold", positive !== undefined && (positive ? "text-green-400" : "text-red-400"))}>
        {value}
      </p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

export default function BacktestPage() {
  const [query, setQuery] = useState("")
  const [events, setEvents] = useState<GammaEvent[]>([])
  const [searching, setSearching] = useState(false)
  const [selectedEvent, setSelectedEvent] = useState<GammaEvent | null>(null)
  const [selectedTokenId, setSelectedTokenId] = useState("")

  const [strategy, setStrategy] = useState("mean_reversion")
  const [bankroll, setBankroll] = useState(1000)
  const [kellyFraction, setKellyFraction] = useState(0.25)
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 30)
    return d.toISOString().split("T")[0]
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split("T")[0])

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResponse | null>(null)
  const [error, setError] = useState("")

  async function handleSearch() {
    if (!query.trim()) return
    setSearching(true)
    setError("")
    try {
      const res = await apiFetch<{ events: GammaEvent[] }>(`/api/backtest/search?q=${encodeURIComponent(query)}&limit=20`)
      setEvents(res.events)
      setSelectedEvent(null)
      setSelectedTokenId("")
      setResult(null)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSearching(false)
    }
  }

  function selectEvent(ev: GammaEvent) {
    setSelectedEvent(ev)
    setResult(null)
    if (ev.markets.length > 0) {
      try {
        const ids = JSON.parse(ev.markets[0].clob_token_ids || "[]")
        setSelectedTokenId(ids[0] || "")
      } catch {
        setSelectedTokenId("")
      }
    }
  }

  async function handleRun() {
    if (!selectedEvent || !selectedTokenId) {
      setError("Select a market first")
      return
    }
    setRunning(true)
    setError("")
    try {
      const res = await apiFetch<BacktestResponse>("/api/backtest/run", {
        method: "POST",
        body: JSON.stringify({
          slug: selectedEvent.slug,
          title: selectedEvent.title,
          clob_token_id: selectedTokenId,
          strategy,
          start_date: startDate,
          end_date: endDate,
          bankroll,
          kelly_fraction: kellyFraction,
        }),
      })
      setResult(res)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRunning(false)
    }
  }

  const equityCurveData = result?.equity_curve.map((p) => ({
    time: new Date(p.timestamp * 1000).toLocaleDateString(),
    value: p.value,
  })) || []

  const dailyPnlData = result?.daily_pnl || []

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <FlaskConical className="h-6 w-6 text-primary" />
        <h1 className="text-2xl font-bold">Backtest</h1>
      </div>

      {/* Search */}
      <div className="rounded-lg border border-border bg-card p-4">
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search Polymarket events... (e.g. trump, bitcoin, election)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
          </button>
        </div>

        {events.length > 0 && (
          <div className="mt-3 max-h-64 space-y-1 overflow-y-auto">
            {events.map((ev) => (
              <button
                key={ev.id}
                onClick={() => selectEvent(ev)}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                  selectedEvent?.id === ev.id
                    ? "bg-primary/10 text-primary border border-primary/30"
                    : "hover:bg-accent"
                )}
              >
                <span className="flex-1 truncate font-medium">{ev.title}</span>
                <span className="ml-3 shrink-0 text-xs text-muted-foreground">
                  Vol: ${ev.volume >= 1000000 ? `${(ev.volume / 1000000).toFixed(1)}M` : ev.volume >= 1000 ? `${(ev.volume / 1000).toFixed(0)}K` : ev.volume.toFixed(0)}
                </span>
                {ev.end_date && (
                  <span className="ml-2 shrink-0 text-xs text-muted-foreground">
                    Ends: {new Date(ev.end_date).toLocaleDateString()}
                  </span>
                )}
                <span className="ml-2 shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs">
                  {ev.markets.length} market{ev.markets.length !== 1 ? "s" : ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Selected event + market picker */}
      {selectedEvent && selectedEvent.markets.length > 1 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="mb-2 text-sm font-medium">Select market outcome:</p>
          <div className="flex flex-wrap gap-2">
            {selectedEvent.markets.map((m, i) => {
              let tokenId = ""
              try { tokenId = JSON.parse(m.clob_token_ids || "[]")[0] || "" } catch {}
              return (
                <button
                  key={i}
                  onClick={() => setSelectedTokenId(tokenId)}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-sm",
                    selectedTokenId === tokenId
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-accent"
                  )}
                >
                  {m.group_item_title || m.slug || `Market ${i + 1}`}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Config panel */}
      {selectedEvent && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="mb-3 text-sm font-semibold">Backtest Configuration</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Strategy</label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {STRATEGIES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Bankroll ($)</label>
              <input
                type="number"
                value={bankroll}
                onChange={(e) => setBankroll(Number(e.target.value))}
                min={10}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">
                Kelly Fraction: {(kellyFraction * 100).toFixed(0)}%
              </label>
              <input
                type="range"
                min={0.05}
                max={1}
                step={0.05}
                value={kellyFraction}
                onChange={(e) => setKellyFraction(Number(e.target.value))}
                className="w-full accent-primary"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs text-muted-foreground">End Date</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          </div>
          <button
            onClick={handleRun}
            disabled={running || !selectedTokenId}
            className="mt-4 flex items-center gap-2 rounded-md bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}
            {running ? "Running Backtest..." : "Run Backtest"}
          </button>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="mb-1 text-lg font-semibold">{result.title || result.slug}</h2>
            <p className="text-xs text-muted-foreground">
              {result.strategy} strategy | {result.start_date} to {result.end_date} | Bankroll: {formatCurrency(result.bankroll)}
            </p>
          </div>

          {/* Summary Stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <StatCard
              label="Total P&L"
              value={formatCurrency(result.total_pnl)}
              sub={`${result.pnl_pct >= 0 ? "+" : ""}${result.pnl_pct}%`}
              positive={result.total_pnl >= 0}
            />
            <StatCard
              label="Win Rate"
              value={`${result.win_rate}%`}
              sub={`${result.winning_trades}W / ${result.losing_trades}L`}
              positive={result.win_rate >= 50}
            />
            <StatCard
              label="Sharpe Ratio"
              value={result.sharpe.toFixed(3)}
              positive={result.sharpe > 0}
            />
            <StatCard
              label="Max Drawdown"
              value={`${(result.max_drawdown * 100).toFixed(2)}%`}
              positive={result.max_drawdown < 0.1}
            />
            <StatCard
              label="Profit Factor"
              value={result.profit_factor >= 999 ? "Inf" : result.profit_factor.toFixed(2)}
              positive={result.profit_factor > 1}
            />
            <StatCard
              label="Avg Edge"
              value={`${(result.avg_edge * 100).toFixed(2)}%`}
              sub={`${result.total_trades} trades`}
              positive={result.avg_edge > 0}
            />
          </div>

          {/* Equity Curve */}
          {equityCurveData.length > 1 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-semibold">Equity Curve</h3>
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={equityCurveData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="time" tick={{ fontSize: 10 }} stroke="#555" />
                  <YAxis tick={{ fontSize: 10 }} stroke="#555" tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                  <Tooltip
                    contentStyle={{ background: "#1a1a2e", border: "1px solid #333", fontSize: 12 }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, "Balance"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke="#3b82f6"
                    fill="#3b82f633"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Daily PnL */}
          {dailyPnlData.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-4">
              <h3 className="mb-3 text-sm font-semibold">Daily P&L</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={dailyPnlData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#555" />
                  <YAxis tick={{ fontSize: 10 }} stroke="#555" tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
                  <Tooltip
                    contentStyle={{ background: "#1a1a2e", border: "1px solid #333", fontSize: 12 }}
                    formatter={(v: number) => [`$${v.toFixed(2)}`, "P&L"]}
                  />
                  <Bar
                    dataKey="pnl"
                    fill="#3b82f6"
                    radius={[2, 2, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Trade Log */}
          {result.trades.length > 0 && (
            <div className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <h3 className="text-sm font-semibold">Trade Log ({result.trades.length} trades)</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="px-4 py-2">Time</th>
                      <th className="px-4 py-2">Side</th>
                      <th className="px-4 py-2 text-right">Size</th>
                      <th className="px-4 py-2 text-right">Entry</th>
                      <th className="px-4 py-2 text-right">Exit</th>
                      <th className="px-4 py-2 text-right">Model</th>
                      <th className="px-4 py-2 text-right">Edge</th>
                      <th className="px-4 py-2 text-right">Kelly</th>
                      <th className="px-4 py-2 text-right">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.map((t, i) => (
                      <tr key={i} className="border-b border-border/50 last:border-0 hover:bg-accent/30">
                        <td className="px-4 py-2 text-xs">{t.timestamp}</td>
                        <td className="px-4 py-2">
                          <span className={cn(
                            "rounded px-1.5 py-0.5 text-xs font-medium",
                            t.side === "BUY" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                          )}>
                            {t.side}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right">{formatCurrency(t.size)}</td>
                        <td className="px-4 py-2 text-right">{(t.entry_price * 100).toFixed(1)}c</td>
                        <td className="px-4 py-2 text-right">{(t.exit_price * 100).toFixed(1)}c</td>
                        <td className="px-4 py-2 text-right">{(t.model_prob * 100).toFixed(1)}%</td>
                        <td className="px-4 py-2 text-right">{(t.edge * 100).toFixed(2)}%</td>
                        <td className="px-4 py-2 text-right">{(t.kelly_pct * 100).toFixed(1)}%</td>
                        <td className={cn("px-4 py-2 text-right font-medium", t.pnl >= 0 ? "text-green-400" : "text-red-400")}>
                          {t.pnl >= 0 ? "+" : ""}{formatCurrency(t.pnl)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {result.total_trades === 0 && (
            <div className="rounded-lg border border-border bg-card p-8 text-center">
              <p className="text-muted-foreground">No trades generated. Try a different date range, strategy, or market with more price movement.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
