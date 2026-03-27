import { type LucideIcon } from "lucide-react"

interface MetricCardProps {
  title: string
  value: string
  change: string
  icon: LucideIcon
}

export function MetricCard({ title, value, change, icon: Icon }: MetricCardProps) {
  const isPositive = change.startsWith("+")

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{title}</p>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="mt-2 text-2xl font-bold">{value}</p>
      <p className={`mt-1 text-xs ${isPositive ? "text-success" : "text-muted-foreground"}`}>
        {change}
      </p>
    </div>
  )
}
