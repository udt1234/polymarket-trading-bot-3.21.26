"use client"

import { useEffect, useState } from "react"
import { ChevronDown, ChevronUp, Save, Settings } from "lucide-react"
import { useApi, useMutation } from "@/lib/hooks"

interface SpikeRiderConfig {
  entry_size_usd: number
  entry_min_price: number
  entry_max_price: number
  max_open_positions: number
  max_open_per_auction: number
  elapsed_max_pct: number
  focus_brackets: string[]
  sell_rule_type: "multi_stage" | "target_multiplier" | "trailing_stop"
  sell_multi_stage_targets: number[]
  sell_target_multiplier: number
  sell_trail_pct: number
  sell_min_gain_pct: number
  fee_pct: number
  slippage_pct: number
  enabled: boolean
  auto_pause_after_losses: number
}

const DEFAULTS: SpikeRiderConfig = {
  entry_size_usd: 10,
  entry_min_price: 0.02,
  entry_max_price: 0.40,
  max_open_positions: 5,
  max_open_per_auction: 3,
  elapsed_max_pct: 0.50,
  focus_brackets: [],
  sell_rule_type: "multi_stage",
  sell_multi_stage_targets: [2, 3, 5],
  sell_target_multiplier: 2.0,
  sell_trail_pct: 0.30,
  sell_min_gain_pct: 0.50,
  fee_pct: 0.02,
  slippage_pct: 0.05,
  enabled: true,
  auto_pause_after_losses: 5,
}

export function SpikeRiderSettings({ moduleId }: { moduleId: string }) {
  const [open, setOpen] = useState(true)
  const { data: config, refetch } = useApi<SpikeRiderConfig>(
    moduleId ? `/api/modules/${moduleId}/config` : null
  )
  const { mutate: saveConfig, loading: saving } = useMutation(
    moduleId ? `/api/modules/${moduleId}/config` : "", "PUT"
  )
  const [local, setLocal] = useState<SpikeRiderConfig>(DEFAULTS)

  useEffect(() => {
    if (config) setLocal({ ...DEFAULTS, ...config })
  }, [config])

  const handleSave = async () => {
    await saveConfig(local)
    refetch()
  }

  const update = <K extends keyof SpikeRiderConfig>(k: K, v: SpikeRiderConfig[K]) =>
    setLocal({ ...local, [k]: v })

  const targetsStr = (local.sell_multi_stage_targets || []).join(", ")

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-6 py-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground hover:bg-accent/50"
      >
        <span className="flex items-center gap-2">
          <Settings className="h-4 w-4" />
          Spike Rider Configuration
        </span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>
      {open && (
        <div className="border-t border-border px-6 py-4">
          <details className="mb-4 rounded-md border border-border/60 bg-muted/20 px-4 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-foreground">
              How Spike Rider works
            </summary>
            <div className="mt-3 space-y-2 text-xs leading-relaxed text-muted-foreground">
              <p>
                Buys cheap brackets early in the auction, rides the hype spike, exits per the sell rule.
                Sized at fixed dollars per entry — no Kelly. Skips brackets outside the entry price band
                and stops opening new positions past the elapsed cutoff.
              </p>
              <p>
                <strong>Sell rule (current: {local.sell_rule_type}):</strong>{" "}
                {local.sell_rule_type === "multi_stage" && (
                  <>sells in 1/N tranches at {targetsStr} times entry. Trailing stop {(local.sell_trail_pct * 100).toFixed(0)}% off peak (after +{(local.sell_min_gain_pct * 100).toFixed(0)}%) acts as backup.</>
                )}
                {local.sell_rule_type === "target_multiplier" && (
                  <>sells the full position at {local.sell_target_multiplier}x entry, with trailing stop backup.</>
                )}
                {local.sell_rule_type === "trailing_stop" && (
                  <>sells when price drops {(local.sell_trail_pct * 100).toFixed(0)}% off peak (only after +{(local.sell_min_gain_pct * 100).toFixed(0)}% gain).</>
                )}
              </p>
              <p>
                Defaults match the offline simulator winner. Re-run <code>scripts/simulate_sell_rules.py</code>
                after a new auction series to retune.
              </p>
            </div>
          </details>

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-4">
            <label className="space-y-1" title="Fixed dollar amount to buy each bracket entry">
              <span className="text-xs text-muted-foreground">Entry Size ($)</span>
              <input
                type="number" min={1} step={1}
                value={local.entry_size_usd}
                onChange={(e) => update("entry_size_usd", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Skip brackets priced below this — too thin for real fills">
              <span className="text-xs text-muted-foreground">Min Entry Price</span>
              <input
                type="number" min={0} max={1} step={0.01}
                value={local.entry_min_price}
                onChange={(e) => update("entry_min_price", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Skip brackets already pricier than this — past entry edge">
              <span className="text-xs text-muted-foreground">Max Entry Price</span>
              <input
                type="number" min={0} max={1} step={0.01}
                value={local.entry_max_price}
                onChange={(e) => update("entry_max_price", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Stop opening new positions past this fraction of auction elapsed">
              <span className="text-xs text-muted-foreground">Elapsed Max (%)</span>
              <input
                type="number" min={0} max={1} step={0.05}
                value={local.elapsed_max_pct}
                onChange={(e) => update("elapsed_max_pct", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Total open positions ceiling across all auctions">
              <span className="text-xs text-muted-foreground">Max Open Positions</span>
              <input
                type="number" min={1} max={50} step={1}
                value={local.max_open_positions}
                onChange={(e) => update("max_open_positions", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Max open positions in a single auction">
              <span className="text-xs text-muted-foreground">Max Per Auction</span>
              <input
                type="number" min={1} max={20} step={1}
                value={local.max_open_per_auction}
                onChange={(e) => update("max_open_per_auction", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Sell strategy: multi-stage tranches, single target, or trailing stop">
              <span className="text-xs text-muted-foreground">Sell Rule</span>
              <select
                value={local.sell_rule_type}
                onChange={(e) => update("sell_rule_type", e.target.value as any)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              >
                <option value="multi_stage">multi_stage</option>
                <option value="target_multiplier">target_multiplier</option>
                <option value="trailing_stop">trailing_stop</option>
              </select>
            </label>
            <label className="space-y-1" title="For target_multiplier: sell full position when price hits this many times entry">
              <span className="text-xs text-muted-foreground">Target Multiplier</span>
              <input
                type="number" min={1.1} max={20} step={0.1}
                value={local.sell_target_multiplier}
                onChange={(e) => update("sell_target_multiplier", +e.target.value)}
                disabled={local.sell_rule_type !== "target_multiplier"}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm disabled:opacity-40"
              />
            </label>
            <label className="space-y-1 col-span-2" title="For multi_stage: comma-separated multipliers (sells 1/N at each)">
              <span className="text-xs text-muted-foreground">Multi-Stage Targets</span>
              <input
                type="text"
                value={targetsStr}
                onChange={(e) => {
                  const parts = e.target.value.split(",").map((s) => parseFloat(s.trim())).filter((n) => !isNaN(n) && n > 1)
                  update("sell_multi_stage_targets", parts)
                }}
                disabled={local.sell_rule_type !== "multi_stage"}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm disabled:opacity-40"
                placeholder="2, 3, 5"
              />
            </label>
            <label className="space-y-1" title="Trailing-stop trigger: how far price must drop from peak">
              <span className="text-xs text-muted-foreground">Trail %</span>
              <input
                type="number" min={0.05} max={0.95} step={0.05}
                value={local.sell_trail_pct}
                onChange={(e) => update("sell_trail_pct", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Minimum gain before trailing stop arms">
              <span className="text-xs text-muted-foreground">Min Gain %</span>
              <input
                type="number" min={0} max={5} step={0.05}
                value={local.sell_min_gain_pct}
                onChange={(e) => update("sell_min_gain_pct", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Estimated Polymarket fee per leg">
              <span className="text-xs text-muted-foreground">Fee % (per leg)</span>
              <input
                type="number" min={0} max={0.10} step={0.005}
                value={local.fee_pct}
                onChange={(e) => update("fee_pct", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="space-y-1" title="Slippage tolerance per leg">
              <span className="text-xs text-muted-foreground">Slippage % (per leg)</span>
              <input
                type="number" min={0} max={0.20} step={0.005}
                value={local.slippage_pct}
                onChange={(e) => update("slippage_pct", +e.target.value)}
                className="w-full rounded border border-border bg-background px-3 py-1.5 text-sm"
              />
            </label>
            <label className="flex items-center gap-2 col-span-2" title="Master enable switch">
              <input
                type="checkbox" checked={local.enabled}
                onChange={(e) => update("enabled", e.target.checked)}
              />
              <span className="text-xs text-muted-foreground">Strategy enabled</span>
            </label>
          </div>

          <div className="mt-4 flex justify-end">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <Save className="h-4 w-4" />
              {saving ? "Saving..." : "Save Configuration"}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
