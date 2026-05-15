"use client"

import { cn } from "@/lib/utils"

export interface TopWallet {
  wallet: string
  wallet_short: string
  archetype: string
  archetype_secondary: string | null
  dollars_flowed: number
  auctions_seen: number
  is_us: boolean
  name_or_pseudonym: string | null
  roi_pct: number | null
  portfolio_value: number | null
  win_rate_pct: number | null
}

const ARCHETYPE_LABEL: Record<string, string> = {
  market_maker: "Market-Maker",
  tail_scooper: "Tail Scooper",
  spike_trader: "Spike Trader",
  pace_chaser: "Pace Chaser",
  tail_punter: "Tail Punter",
  unknown: "Unknown",
}

export function WhaleTopTable({
  wallets,
  expandedWallet,
  onExpand,
}: {
  wallets: TopWallet[]
  expandedWallet: string | null
  onExpand: (wallet: string | null) => void
}) {
  if (wallets.length === 0) {
    return <p className="text-xs text-muted-foreground">No wallets match the cohort filter.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-2 py-1.5 text-left">Wallet</th>
            <th className="px-2 py-1.5 text-left">Archetype</th>
            <th className="px-2 py-1.5 text-right">Auctions</th>
            <th className="px-2 py-1.5 text-right">ROI%</th>
            <th className="px-2 py-1.5 text-right">$ Flowed</th>
            <th className="px-2 py-1.5 text-right">Win rate</th>
          </tr>
        </thead>
        <tbody>
          {wallets.map((w) => {
            const isOpen = expandedWallet === w.wallet
            return (
              <tr
                key={w.wallet}
                onClick={() => onExpand(isOpen ? null : w.wallet)}
                className={cn(
                  "cursor-pointer border-t border-border/40 transition-colors hover:bg-muted/30",
                  isOpen && "bg-muted/40",
                )}
                title="Click for detail"
              >
                <td className="px-2 py-1.5">
                  <span className={cn("font-mono", w.is_us && "font-bold text-primary")}>
                    {w.wallet_short}
                  </span>
                  {w.is_us && <span className="ml-1 text-[10px] text-primary">us</span>}
                  {w.name_or_pseudonym && (
                    <span className="ml-2 text-[10px] text-muted-foreground/70">
                      {w.name_or_pseudonym}
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-muted-foreground">
                  {ARCHETYPE_LABEL[w.archetype] || w.archetype}
                  {w.archetype_secondary && (
                    <span className="ml-1 text-[10px] text-muted-foreground/60">
                      +{ARCHETYPE_LABEL[w.archetype_secondary] || w.archetype_secondary}
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                  {w.auctions_seen}
                </td>
                <td
                  className={cn(
                    "px-2 py-1.5 text-right tabular-nums",
                    w.roi_pct === null
                      ? "text-muted-foreground/60"
                      : w.roi_pct > 0
                      ? "text-success"
                      : w.roi_pct < 0
                      ? "text-destructive"
                      : "text-muted-foreground",
                  )}
                >
                  {w.roi_pct !== null
                    ? `${w.roi_pct > 0 ? "+" : ""}${Math.round(w.roi_pct)}%`
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                  ${Math.round(w.dollars_flowed).toLocaleString()}
                </td>
                <td className="px-2 py-1.5 text-right text-muted-foreground tabular-nums">
                  {w.win_rate_pct !== null ? `${Math.round(w.win_rate_pct)}%` : "—"}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
