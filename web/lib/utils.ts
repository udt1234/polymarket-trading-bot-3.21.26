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
