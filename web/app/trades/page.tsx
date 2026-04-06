"use client"

import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { DataTable } from "@/components/shared/data-table"
import { TabToggle } from "@/components/shared/tab-toggle"

function exportCsv(columns: string[], rows: Record<string, any>[], filename: string) {
  const header = columns.join(",")
  const body = rows.map((r) =>
    columns.map((c) => {
      const val = String(r[c] ?? "")
      return val.includes(",") || val.includes('"') ? `"${val.replace(/"/g, '""')}"` : val
    }).join(",")
  ).join("\n")
  const csv = header + "\n" + body
  const blob = new Blob([csv], { type: "text/csv" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export default function TradesPage() {
  const [view, setView] = useState("bot")
  const { data } = useApi<{ data: any[]; total: number }>("/api/trades/")
  const { data: walletTrades } = useApi<any>("/api/dashboard/wallet/trades", [view])

  const botColumns = ["Time", "Module", "Market", "Bracket", "Side", "Size", "Price", "Executor"]
  const botRows = (data?.data || []).map((t: any) => ({
    Time: t.executed_at ? new Date(t.executed_at).toLocaleString() : "\u2014",
    Module: t.module_id?.slice(0, 8) || "\u2014",
    Market: t.market_id || "\u2014",
    Bracket: t.bracket || "\u2014",
    Side: t.side,
    Size: t.size?.toFixed(2),
    Price: t.price?.toFixed(4),
    Executor: t.executor || "paper",
  }))

  const walletItems = walletTrades?.trades || walletTrades?.data || walletTrades || []
  const walletColumns = ["Time", "Market", "Side", "Size", "Price", "Type"]
  const walletRows = (Array.isArray(walletItems) ? walletItems : []).map((t: any) => ({
    Time: (t.timestamp || t.executed_at) ? new Date(t.timestamp || t.executed_at).toLocaleString() : "\u2014",
    Market: t.market || t.market_id || t.title || "\u2014",
    Side: t.side || t.outcome || "\u2014",
    Size: (t.size || t.amount || 0).toFixed(2),
    Price: (t.price || 0).toFixed(4),
    Type: t.type || t.trade_type || "\u2014",
  }))

  const currentColumns = view === "bot" ? botColumns : walletColumns
  const currentRows = view === "bot" ? botRows : walletRows
  const total = view === "bot" ? data?.total : walletRows.length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Trades {total ? `(${total})` : ""}</h1>
        <div className="flex items-center gap-3">
          <TabToggle
            value={view}
            onChange={setView}
            options={[
              { label: "Bot Trades", value: "bot" },
              { label: "Wallet Trades", value: "wallet" },
            ]}
          />
          <button
            onClick={() => exportCsv(currentColumns, currentRows, `${view}-trades.csv`)}
            disabled={currentRows.length === 0}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          >
            Export CSV
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card p-6">
        <DataTable
          columns={currentColumns}
          rows={currentRows}
          emptyMessage={view === "bot" ? "No trades yet" : "No wallet trades found"}
        />
      </div>
    </div>
  )
}
