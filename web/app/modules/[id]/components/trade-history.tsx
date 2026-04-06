import { formatCurrency } from "@/lib/utils"

function fmt(n: number, decimals = 1): string {
  return parseFloat(n.toFixed(decimals)).toString()
}

interface Trade {
  bracket: string
  side: string
  size: number
  price: number
  executor: string
  executed_at: string
}

export function TradeHistory({ trades }: { trades: { data: Trade[]; total: number } | null }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Trade History ({trades?.total || 0})
        </h2>
        <p className="mt-1 mb-3 text-xs text-muted-foreground">Log of every trade the bot has executed for this module.</p>
      </div>
      {trades?.data && trades.data.length > 0 ? (
        <div className="max-h-[400px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                <th className="px-6 py-2 text-left">Time</th>
                <th className="px-6 py-2 text-left">Bracket</th>
                <th className="px-6 py-2 text-left">Side</th>
                <th className="px-6 py-2 text-right">Shares</th>
                <th className="px-6 py-2 text-right">Price</th>
                <th className="px-6 py-2 text-right">Cost</th>
                <th className="px-6 py-2 text-right">Executor</th>
              </tr>
            </thead>
            <tbody>
              {trades.data.map((t, i) => (
                <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/50">
                  <td className="px-6 py-2.5 text-xs text-muted-foreground">{new Date(t.executed_at).toLocaleString()}</td>
                  <td className="px-6 py-2.5 font-medium">{t.bracket}</td>
                  <td className="px-6 py-2.5">
                    <span className={t.side === "BUY" ? "text-success" : "text-destructive"}>{t.side}</span>
                  </td>
                  <td className="px-6 py-2.5 text-right">{fmt(t.size)}</td>
                  <td className="px-6 py-2.5 text-right">{fmt(t.price * 100)}&cent;</td>
                  <td className="px-6 py-2.5 text-right">{formatCurrency(t.size * t.price)}</td>
                  <td className="px-6 py-2.5 text-right text-xs text-muted-foreground">{t.executor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-6 py-8 text-center text-sm text-muted-foreground">No trades yet</p>
      )}
    </div>
  )
}
