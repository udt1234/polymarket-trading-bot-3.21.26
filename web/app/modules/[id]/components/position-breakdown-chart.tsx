"use client"

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts"

interface Position { bracket: string; size: number; avg_price: number; status: string }

function bracketCategory(bracket: string): string {
  const match = bracket.match(/(\d+)/)
  if (!match) return "Other"
  const n = parseInt(match[1])
  if (n < 50) return "Low (<50)"
  if (n < 100) return "Mid (50-100)"
  if (n < 150) return "High (100-150)"
  return "Very High (150+)"
}

const COLORS: Record<string, string> = {
  "Low (<50)": "hsl(200, 70%, 55%)",
  "Mid (50-100)": "hsl(142, 71%, 45%)",
  "High (100-150)": "hsl(45, 93%, 55%)",
  "Very High (150+)": "hsl(0, 84%, 60%)",
  "Other": "hsl(215, 20%, 55%)",
}

export function PositionBreakdownChart({ positions }: { positions: Position[] }) {
  const open = positions.filter((p) => p.status === "open")
  const byCat: Record<string, number> = {}
  for (const p of open) {
    const cat = bracketCategory(p.bracket)
    const cost = p.size * p.avg_price
    byCat[cat] = (byCat[cat] || 0) + cost
  }
  const data = Object.entries(byCat).map(([name, value]) => ({ name, value: parseFloat(value.toFixed(2)) }))

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Position Breakdown</h2>
      <p className="mb-4 text-xs text-muted-foreground">Open positions by bracket category</p>
      {data.length > 0 ? (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie data={data} cx="50%" cy="50%" outerRadius={80} dataKey="value" label={(e: any) => `${e.name}: $${e.value.toFixed(0)}`}>
              {data.map((d, i) => (
                <Cell key={i} fill={COLORS[d.name] || COLORS["Other"]} />
              ))}
            </Pie>
            <Tooltip contentStyle={{ background: "hsl(217, 33%, 17%)", border: "none", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => `$${v.toFixed(2)}`} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
          </PieChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">No open positions</div>
      )}
    </div>
  )
}
