import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number): string {
  const rounded = Math.round(value * 100) / 100
  if (rounded === Math.floor(rounded)) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(rounded)
  }
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rounded)
}

/**
 * Polymarket per-share price renderer (always raw dollars, never cents).
 *
 * Polymarket prices are stored as fractions of a dollar between 0.00 and 1.00.
 * Each share pays $1.00 if YES resolves, so the price IS the per-share dollar
 * cost. We render in dollars to avoid the cents-vs-tenths-of-a-cent confusion
 * (e.g. "0.80¢" being misread as 80 cents).
 *
 * Adaptive precision (Option B):
 *   - sub-cent (price < 0.01): 3 decimals  -> $0.003
 *   - 1c to 99c (price < 1.00): 2 decimals -> $0.05, $0.32, $0.95
 *   - >= $1.00: 2 decimals (defensive — should never occur in book prices)
 */
export function fmtPrice(price: number | null | undefined): string {
  if (price == null || isNaN(price)) return "—"
  const abs = Math.abs(price)
  const sign = price < 0 ? "-" : ""
  if (abs < 0.01) return `${sign}$${abs.toFixed(3)}`
  return `${sign}$${abs.toFixed(2)}`
}

export function formatPercent(value: number): string {
  const clean = parseFloat(value.toFixed(1)).toString()
  return `${value >= 0 ? "+" : ""}${clean}%`
}

export function formatDate(dateStr: string): string {
  if (!dateStr) return ""
  const d = new Date(dateStr + (dateStr.includes("T") ? "" : "T00:00:00"))
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

export function formatDateShort(dateStr: string): string {
  if (!dateStr) return ""
  const d = new Date(dateStr + (dateStr.includes("T") ? "" : "T00:00:00"))
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

/**
 * Numeric-aware bracket sort. Polymarket bracket labels are strings like
 * "<40", "40-64", "65-89", ..., "240+". JS .sort() puts numerics before "<"
 * so "115-139" lands before "<40". This helper sorts by the bracket's
 * lower-edge numeric value, with "<N" ranked first and "N+" ranked last.
 */
export function bracketSortKey(b: string): number {
  // "<N" always sorts first (Number.NEGATIVE_INFINITY would also work but
  // we keep ordering predictable: <40 ranks before <80 if both ever exist).
  if (b.startsWith("<")) return -1_000_000 + Number(b.slice(1) || 0)
  // "N+" always sorts last for the same reason.
  if (b.endsWith("+")) return 1_000_000 + Number(b.slice(0, -1) || 0)
  const m = b.match(/^(\d+)/)
  return m ? Number(m[1]) : Number.POSITIVE_INFINITY
}

export function sortBrackets(brackets: string[]): string[] {
  return [...brackets].sort((a, b) => bracketSortKey(a) - bracketSortKey(b))
}
