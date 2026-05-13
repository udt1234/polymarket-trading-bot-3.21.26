"use client"

/**
 * 🐋 Whale Watching card.
 *
 * Spec: _ImportantConfigFiles/WHALE_BRACKET_CARDS_SPEC.md Phase 2.
 *
 * Reads /api/modules/{id}/whales for archetype breakdown, top wallets, and
 * fill-behavior grid. Filter changes refetch (no client-side aggregation).
 * Module-id-driven, no per-module branching.
 */
import { useState } from "react"
import { useApi } from "@/lib/hooks"
import { CardHeadline } from "./card-headline"
import { WhaleArchetypeBar, type ArchetypeRow } from "./whale-archetype-bar"
import { WhaleTopTable, type TopWallet } from "./whale-top-table"
import { WhaleGrid, type GridRow } from "./whale-grid"
import { WhaleWalletDetail } from "./whale-wallet-detail"

interface WhalesResponse {
  headline: { lines: string[] }
  archetype_breakdown: Record<string, ArchetypeRow>
  top_wallets: TopWallet[]
  grid_metrics: GridRow[]
  n_auctions: number
  data_quality: "ok" | "insufficient"
  config: { window: string; cohort: string }
}

type Window = "last_5" | "last_10" | "all_time"
type Cohort = "all" | "persistent" | "profitable"

export function WhaleWatchingCard({ moduleId }: { moduleId: string }) {
  const [window, setWindow] = useState<Window>("last_5")
  const [cohort, setCohort] = useState<Cohort>("persistent")
  const [expanded, setExpanded] = useState<string | null>(null)
  const [showAllWallets, setShowAllWallets] = useState(false)

  const url = `/api/modules/${moduleId}/whales?window=${window}&cohort=${cohort}`
  const { data, loading } = useApi<WhalesResponse>(url, [window, cohort])

  const wallets = data?.top_wallets || []
  const visibleWallets = showAllWallets ? wallets : wallets.slice(0, 5)

  return (
    <div>
      <CardHeadline
        emoji="🐋"
        title="Whale Watching"
        lines={data?.headline?.lines || []}
      />

      <div className="rounded-lg border border-border bg-card p-4">
        {/* Filter row */}
        <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border pb-3">
          <div className="flex items-center gap-1 text-xs">
            <span className="text-muted-foreground">Window:</span>
            <select
              value={window}
              onChange={(e) => setWindow(e.target.value as Window)}
              className="rounded border border-border bg-background px-2 py-1"
            >
              <option value="last_5">Last 5</option>
              <option value="last_10">Last 10</option>
              <option value="all_time">All time</option>
            </select>
          </div>
          <div className="flex items-center gap-1 text-xs">
            <span className="text-muted-foreground">Cohort:</span>
            <select
              value={cohort}
              onChange={(e) => setCohort(e.target.value as Cohort)}
              className="rounded border border-border bg-background px-2 py-1"
            >
              <option value="all">All</option>
              <option value="persistent">Persistent (≥3 auctions)</option>
              <option value="profitable">Profitable (ROI &gt; 0)</option>
            </select>
          </div>
          <div className="ml-auto text-xs text-muted-foreground">
            N = {data?.n_auctions ?? 0}
            {data?.data_quality === "insufficient" && (
              <span className="ml-2 text-amber-400">(insufficient — need ≥5)</span>
            )}
          </div>
        </div>

        {loading && <p className="text-xs text-muted-foreground">Loading whale data...</p>}

        {!loading && data?.data_quality === "insufficient" && (
          <p className="text-xs text-muted-foreground">
            Not enough closed auctions yet. Whale snapshots refresh nightly.
          </p>
        )}

        {!loading && data?.data_quality === "ok" && (
          <div className="space-y-4">
            {/* Archetype breakdown */}
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Archetype Breakdown — Bot Mix in This Market
              </p>
              <WhaleArchetypeBar breakdown={data.archetype_breakdown} />
            </div>

            {/* Top wallets */}
            <div className="border-t border-border pt-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Top Whales — Window
              </p>
              <WhaleTopTable
                wallets={visibleWallets}
                expandedWallet={expanded}
                onExpand={setExpanded}
              />
              {expanded && (
                <div className="mt-2">
                  <WhaleWalletDetail moduleId={moduleId} wallet={expanded} />
                </div>
              )}
              {wallets.length > 5 && (
                <button
                  type="button"
                  onClick={() => setShowAllWallets((v) => !v)}
                  className="mt-2 text-[11px] text-muted-foreground hover:text-foreground"
                >
                  {showAllWallets ? "▲ Show top 5" : `▼ Show ${wallets.length - 5} more`}
                </button>
              )}
            </div>

            {/* Fill-behavior grid */}
            <div className="border-t border-border pt-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                The Grid — Fill Behavior by Archetype
              </p>
              <WhaleGrid rows={data.grid_metrics} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
