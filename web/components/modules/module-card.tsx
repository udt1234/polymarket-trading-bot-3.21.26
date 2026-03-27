import Link from "next/link"
import { StatusBadge } from "@/components/shared/status-badge"
import { formatCurrency } from "@/lib/utils"

interface ModuleCardProps {
  name: string
  strategy: string
  status: string
  pnl: number
  positions: number
}

export function ModuleCard({ name, strategy, status, pnl, positions }: ModuleCardProps) {
  return (
    <Link
      href={`/modules/${name.toLowerCase().replace(/\s+/g, "-")}`}
      className="block rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50"
    >
      <div className="flex items-start justify-between">
        <h3 className="font-semibold">{name}</h3>
        <StatusBadge status={status} />
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{strategy}</p>
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
