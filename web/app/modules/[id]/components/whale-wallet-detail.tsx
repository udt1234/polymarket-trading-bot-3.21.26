"use client"

import { useApi } from "@/lib/hooks"

interface AuctionRow {
  slug: string
  end_date: string
  archetype: string
  dollars_flowed: number
}

interface DetailResponse {
  wallet: string
  auctions: AuctionRow[]
  total_dollars_flowed: number
  data_quality: "ok" | "insufficient"
}

export function WhaleWalletDetail({
  moduleId,
  wallet,
}: {
  moduleId: string
  wallet: string
}) {
  const url = `/api/modules/${moduleId}/whales/wallets/${wallet}`
  const { data, loading } = useApi<DetailResponse>(url, [wallet])

  if (loading) {
    return <p className="text-xs text-muted-foreground">Loading wallet detail...</p>
  }
  if (!data || data.data_quality === "insufficient") {
    return (
      <p className="text-xs text-muted-foreground">
        No detail available for this wallet in our snapshots yet.
      </p>
    )
  }

  return (
    <div className="space-y-2 rounded border border-border bg-background/40 p-3">
      <div className="flex items-center justify-between gap-2 text-xs">
        <div>
          <span className="font-mono text-foreground">{wallet}</span>
          <button
            type="button"
            onClick={() => {
              if (typeof navigator !== "undefined" && navigator.clipboard) {
                navigator.clipboard.writeText(wallet).catch(() => undefined)
              }
            }}
            className="ml-2 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground"
            title="Copy full address"
          >
            copy
          </button>
        </div>
        <span className="text-muted-foreground">
          Total ${Math.round(data.total_dollars_flowed).toLocaleString()} across {data.auctions.length} auctions
        </span>
      </div>

      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-2 py-1 text-left">Auction</th>
            <th className="px-2 py-1 text-left">Archetype</th>
            <th className="px-2 py-1 text-right">$ Flowed</th>
            <th className="px-2 py-1 text-right">End</th>
          </tr>
        </thead>
        <tbody>
          {data.auctions.map((a) => (
            <tr key={a.slug} className="border-t border-border/40">
              <td className="px-2 py-1 font-mono text-[10px]">{a.slug}</td>
              <td className="px-2 py-1 text-muted-foreground">{a.archetype}</td>
              <td className="px-2 py-1 text-right text-muted-foreground tabular-nums">
                ${Math.round(a.dollars_flowed).toLocaleString()}
              </td>
              <td className="px-2 py-1 text-right text-muted-foreground">
                {a.end_date?.slice(0, 10)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
