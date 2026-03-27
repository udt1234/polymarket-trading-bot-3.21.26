import { cn } from "@/lib/utils"

const statusStyles: Record<string, string> = {
  active: "bg-success/20 text-success",
  paused: "bg-yellow-500/20 text-yellow-500",
  paper: "bg-blue-500/20 text-blue-500",
  scaffold: "bg-muted text-muted-foreground",
  error: "bg-destructive/20 text-destructive",
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", statusStyles[status] || statusStyles.scaffold)}>
      {status}
    </span>
  )
}
