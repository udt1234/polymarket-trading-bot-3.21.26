import Link from "next/link"
import { StatusBadge } from "@/components/shared/status-badge"
import { HealthBadge } from "@/components/shared/health-badge"
import { formatCurrency } from "@/lib/utils"

interface ModuleCardProps {
  name: string
  strategy: string
  status: string
  displayBadge?: string
  inactiveReasonHuman?: string | null
  pnl: number
  positions: number
  realtimeHealth?: {
    badge?: string
    reason?: string
    trades_24h?: number
    errors_1h?: number
    last_cycle_at?: string | null
  } | null
}

export function ModuleCard({
  name,
  strategy,
  status,
  displayBadge,
  inactiveReasonHuman,
  pnl,
  positions,
  realtimeHealth,
}: ModuleCardProps) {
  return (
    <Link
      href={`/modules/${name.toLowerCase().replace(/\s+/g, "-")}`}
      className="block rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold">{name}</h3>
        <div className="flex flex-col items-end gap-1">
          <StatusBadge
            displayBadge={displayBadge}
            status={status}
            inactiveReasonHuman={inactiveReasonHuman}
          />
          <HealthBadge health={realtimeHealth} />
        </div>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{strategy}</p>
      {realtimeHealth?.reason && (
        <p className="mt-1 text-xs text-muted-foreground line-clamp-2" title={realtimeHealth.reason}>
          {realtimeHealth.reason}
        </p>
      )}
      <div className="mt-3 flex gap-4 text-sm">
        <div>
          <span className="text-muted-foreground">P&L: </span>
          <span className={pnl >= 0 ? "text-success" : "text-destructive"}>{formatCurrency(pnl)}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Positions: </span>
          <span>{positions}</span>
        </div>
      </div>
    </Link>
  )
}
