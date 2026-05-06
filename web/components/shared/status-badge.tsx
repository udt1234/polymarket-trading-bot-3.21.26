import { cn } from "@/lib/utils"

// Three operational states the dashboard cares about. Old values (paused,
// killed, scaffold) are collapsed into 'inactive' on the API.
const BADGE_STYLES: Record<string, string> = {
  real_trading: "bg-success/20 text-success",
  paper_trading: "bg-muted text-muted-foreground",
  inactive: "bg-destructive/20 text-destructive",
}

const BADGE_LABELS: Record<string, string> = {
  real_trading: "Real $Trades",
  paper_trading: "Paper Trades",
  inactive: "Inactive",
}

interface StatusBadgeProps {
  // Preferred: pass display_badge from the API directly.
  displayBadge?: string
  // Legacy fallback: status from the modules table.
  status?: string
  inactiveReasonHuman?: string | null
}

function statusToBadge(status?: string): string {
  if (!status) return "paper_trading"
  const s = status.toLowerCase()
  if (s === "inactive") return "inactive"
  if (s === "active" || s === "paper") return "paper_trading"
  // Legacy values that may still be in the wild during migration
  if (["paused", "killed", "scaffold"].includes(s)) return "inactive"
  return "paper_trading"
}

export function StatusBadge({ displayBadge, status, inactiveReasonHuman }: StatusBadgeProps) {
  const key = displayBadge && BADGE_STYLES[displayBadge] ? displayBadge : statusToBadge(status)
  const title = key === "inactive" && inactiveReasonHuman
    ? `Inactive — ${inactiveReasonHuman}`
    : BADGE_LABELS[key]
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        BADGE_STYLES[key],
      )}
    >
      {key === "paper_trading" && (
        <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/70" aria-hidden />
      )}
      {BADGE_LABELS[key]}
    </span>
  )
}
