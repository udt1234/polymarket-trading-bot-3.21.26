"use client"

import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { DataTable } from "@/components/shared/data-table"
import { formatCurrency } from "@/lib/utils"

function TabToggle({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { label: string; value: string }[] }) {
  return (
    <div className="inline-flex rounded-lg border border-border bg-card p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${value === o.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export default function PortfolioPage() {
  const [view, setView] = useState("bot")
  const { data: positions } = useApi<any[]>("/api/portfolio/positions")
  const { data: exposure } = useApi<any>("/api/portfolio/exposure")
  const { data: walletPositions } = useApi<any>("/api/dashboard/wallet/positions", [view])

  const botRows = (positions || []).map((p: any) => ({
    Module: p.module_id?.slice(0, 8) || "\u2014",
    Market: p.market_id || "\u2014",
    Bracket: p.bracket || "\u2014",
    Side: p.side,
    Size: p.size?.toFixed(2),
    "Avg Price": p.avg_price?.toFixed(4),
    "P&L": formatCurrency((p.realized_pnl || 0) + (p.unrealized_pnl || 0)),
  }))

  const walletData = walletPositions?.positions || walletPositions || []
  const grouped: Record<string, any[]> = {}
  walletData.forEach((p: any) => {
    const market = p.market || p.market_id || p.title || "Unknown"
    if (!grouped[market]) grouped[market] = []
    grouped[market].push(p)
  })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <TabToggle
          value={view}
          onChange={setView}
          options={[
            { label: "Bot Positions", value: "bot" },
            { label: "Wallet Positions", value: "wallet" },
          ]}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">Total Exposure</p>
          <p className="text-2xl font-bold">{formatCurrency(exposure?.total_exposure || 0)}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">Unrealized P&L</p>
          <p className="text-2xl font-bold">{formatCurrency((positions || []).reduce((s: number, p: any) => s + (p.unrealized_pnl || 0), 0))}</p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">Open Positions</p>
          <p className="text-2xl font-bold">{exposure?.position_count || 0}</p>
        </div>
      </div>

      {view === "bot" ? (
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="mb-4 text-lg font-semibold">Open Positions</h2>
          <DataTable
            columns={["Module", "Market", "Bracket", "Side", "Size", "Avg Price", "P&L"]}
            rows={botRows}
            emptyMessage="No open positions"
          />
        </div>
      ) : (
        <div className="space-y-4">
          {Object.keys(grouped).length === 0 && (
            <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground">
              No wallet positions found
            </div>
          )}
          {Object.entries(grouped).map(([market, items]) => {
            const totalValue = items.reduce((s: number, p: any) => s + (p.value || p.size || 0), 0)
            const totalPnl = items.reduce((s: number, p: any) => s + (p.pnl || p.realized_pnl || 0) + (p.unrealized_pnl || 0), 0)
            return (
              <div key={market} className="rounded-lg border border-border bg-card p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="font-semibold text-sm">{market}</h3>
                  <div className="flex gap-4 text-sm">
                    <span className="text-muted-foreground">Value: <span className="text-foreground font-medium">{formatCurrency(totalValue)}</span></span>
                    <span className="text-muted-foreground">P&L: <span className={totalPnl >= 0 ? "text-green-500 font-medium" : "text-red-500 font-medium"}>{formatCurrency(totalPnl)}</span></span>
                  </div>
                </div>
                <DataTable
                  columns={["Side", "Size", "Price", "Value", "P&L"]}
                  rows={items.map((p: any) => ({
                    Side: p.side || p.outcome || "\u2014",
                    Size: (p.size || p.amount || 0).toFixed(2),
                    Price: (p.avg_price || p.price || 0).toFixed(4),
                    Value: formatCurrency(p.value || p.size || 0),
                    "P&L": formatCurrency((p.pnl || p.realized_pnl || 0) + (p.unrealized_pnl || 0)),
                  }))}
                  emptyMessage="No positions"
                />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
