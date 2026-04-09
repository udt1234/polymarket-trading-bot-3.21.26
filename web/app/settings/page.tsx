"use client"

import { useState, useEffect, useRef, useCallback } from "react"
import { useApi, useMutation, useDebounce } from "@/lib/hooks"
import { apiFetch } from "@/lib/api"

function Toggle({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${checked ? "bg-primary" : "bg-muted"} ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    >
      <span className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-lg transition-transform ${checked ? "translate-x-5" : "translate-x-0"}`} />
    </button>
  )
}

function RiskField({ label, fieldKey, value, type, risk, onSave }: {
  label: string; fieldKey: string; value: any; type: "dollar" | "percent" | "multiplier"; risk: any; onSave: (key: string, val: number) => void
}) {
  const toDisplay = (v: any) => {
    if (type === "dollar") return String(v ?? 1000)
    if (type === "percent") return String(((v ?? 0) * 100).toFixed(1))
    return String(v ?? 0.25)
  }

  const [input, setInput] = useState(toDisplay(value))
  const [dirty, setDirty] = useState(false)
  const debounced = useDebounce(input, 800)

  useEffect(() => {
    if (!dirty) return
    let numVal: number
    if (type === "dollar") numVal = parseFloat(debounced) || 0
    else if (type === "percent") numVal = (parseFloat(debounced) || 0) / 100
    else numVal = parseFloat(debounced) || 0
    onSave(fieldKey, numVal)
    setDirty(false)
  }, [debounced])

  useEffect(() => {
    setInput(toDisplay(value))
  }, [value])

  const prefix = type === "dollar" ? "$" : ""
  const suffix = type === "percent" ? "%" : type === "multiplier" ? "x" : ""

  return (
    <div className="flex items-center justify-between border-b border-border pb-2 last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-center gap-1">
        {prefix && <span className="text-sm text-muted-foreground">{prefix}</span>}
        <input
          type="number"
          step="any"
          value={input}
          onChange={(e) => { setInput(e.target.value); setDirty(true) }}
          className="w-24 rounded border border-border bg-background px-2 py-1 text-right text-sm focus:border-primary focus:outline-none"
        />
        {suffix && <span className="text-sm text-muted-foreground">{suffix}</span>}
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const { data: risk, refetch: refetchRisk } = useApi<any>("/api/settings/risk")
  const { data: profileData, refetch: refetchProfiles } = useApi<any>("/api/settings/profiles")
  const { data: notifications, refetch: refetchNotifications } = useApi<any>("/api/settings/notifications")

  const { mutate: saveRisk } = useMutation<any>("/api/settings/risk", "PUT")
  const { mutate: saveNotifications } = useMutation<any>("/api/settings/notifications", "PUT")

  const [slackUrl, setSlackUrl] = useState("")
  const [slackSaving, setSlackSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [resetConfirm, setResetConfirm] = useState(false)

  const [showProfileForm, setShowProfileForm] = useState(false)
  const [newProfile, setNewProfile] = useState({ name: "", wallet_address: "", api_key: "", private_key: "", multi_exec: false })
  const [profileSaving, setProfileSaving] = useState(false)

  useEffect(() => {
    if (notifications?.slack_webhook) setSlackUrl(notifications.slack_webhook)
  }, [notifications])

  const riskFields = [
    { label: "Bankroll", key: "bankroll", type: "dollar" as const },
    { label: "Max Portfolio Exposure", key: "max_portfolio_exposure", type: "percent" as const },
    { label: "Max Single Market", key: "max_single_market_exposure", type: "percent" as const },
    { label: "Daily Loss Limit", key: "daily_loss_limit", type: "percent" as const },
    { label: "Max Drawdown", key: "max_drawdown", type: "percent" as const },
    { label: "Min Edge Threshold", key: "min_edge_threshold", type: "percent" as const },
    { label: "Kelly Fraction", key: "kelly_fraction", type: "multiplier" as const },
  ]

  const handleRiskSave = useCallback(async (key: string, val: number) => {
    await saveRisk({ ...risk, [key]: val })
    refetchRisk()
  }, [risk])

  const handleToggleMode = useCallback(async (key: string, val: boolean) => {
    await saveRisk({ ...risk, [key]: val })
    refetchRisk()
  }, [risk])

  const handleResetPaperTrades = async () => {
    setResetting(true)
    try {
      await apiFetch("/api/settings/reset-paper-trades", { method: "POST" })
      setResetConfirm(false)
    } catch (e) {
      alert("Reset failed — are you in paper mode?")
    }
    setResetting(false)
  }

  const handleSaveSlack = async () => {
    setSlackSaving(true)
    await saveNotifications({ slack_webhook: slackUrl })
    await refetchNotifications()
    setSlackSaving(false)
  }

  const handleAddProfile = async () => {
    setProfileSaving(true)
    await apiFetch("/api/settings/profiles", {
      method: "POST",
      body: JSON.stringify(newProfile),
    })
    setNewProfile({ name: "", wallet_address: "", api_key: "", private_key: "", multi_exec: false })
    setShowProfileForm(false)
    await refetchProfiles()
    setProfileSaving(false)
  }

  const handleDeleteProfile = async (name: string) => {
    await apiFetch(`/api/settings/profiles/${encodeURIComponent(name)}`, { method: "DELETE" })
    refetchProfiles()
  }

  const handleActivateProfile = async (name: string) => {
    await apiFetch(`/api/settings/profiles/${encodeURIComponent(name)}/activate`, { method: "PUT" })
    refetchProfiles()
  }

  const handleToggleMultiExec = async (name: string, val: boolean) => {
    await apiFetch(`/api/settings/profiles/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ multi_exec: val }),
    })
    refetchProfiles()
  }

  const activeProfile = profileData?.active
  const profiles = profileData?.profiles || []

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="mb-4 text-lg font-semibold">Risk Parameters</h2>
          <div className="space-y-3">
            {riskFields.map((f) => (
              <RiskField
                key={f.key}
                label={f.label}
                fieldKey={f.key}
                value={risk?.[f.key]}
                type={f.type}
                risk={risk}
                onSave={handleRiskSave}
              />
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="mb-4 text-lg font-semibold">Trading Mode</h2>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">Paper Trading</span>
              <Toggle checked={risk?.paper_mode !== false} onChange={(v) => handleToggleMode("paper_mode", v)} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Shadow Mode</span>
              <Toggle checked={!!risk?.shadow_mode} onChange={(v) => handleToggleMode("shadow_mode", v)} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm">Circuit Breaker</span>
              <Toggle checked={risk?.circuit_breaker_enabled !== false} onChange={(v) => handleToggleMode("circuit_breaker_enabled", v)} />
            </div>
          </div>

          <div className="mt-6 border-t border-border pt-4">
            <h3 className="mb-2 text-sm font-semibold text-destructive">Danger Zone</h3>
            {!resetConfirm ? (
              <button
                onClick={() => setResetConfirm(true)}
                className="rounded-md border border-destructive/50 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
              >
                Reset Paper Trades
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Delete all paper data?</span>
                <button
                  onClick={handleResetPaperTrades}
                  disabled={resetting}
                  className="rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                >
                  {resetting ? "Resetting..." : "Yes, Delete All"}
                </button>
                <button
                  onClick={() => setResetConfirm(false)}
                  className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-6 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Wallet Profiles</h2>
            <button
              onClick={() => setShowProfileForm(!showProfileForm)}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              {showProfileForm ? "Cancel" : "+ Add Profile"}
            </button>
          </div>

          {showProfileForm && (
            <div className="mb-4 rounded-lg border border-border bg-background p-4 space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <input
                  placeholder="Profile name"
                  value={newProfile.name}
                  onChange={(e) => setNewProfile({ ...newProfile, name: e.target.value })}
                  className="rounded border border-border bg-card px-3 py-2 text-sm focus:border-primary focus:outline-none"
                />
                <input
                  placeholder="Wallet address"
                  value={newProfile.wallet_address}
                  onChange={(e) => setNewProfile({ ...newProfile, wallet_address: e.target.value })}
                  className="rounded border border-border bg-card px-3 py-2 text-sm font-mono focus:border-primary focus:outline-none"
                />
                <input
                  placeholder="API key"
                  type="password"
                  value={newProfile.api_key}
                  onChange={(e) => setNewProfile({ ...newProfile, api_key: e.target.value })}
                  className="rounded border border-border bg-card px-3 py-2 text-sm focus:border-primary focus:outline-none"
                />
                <input
                  placeholder="Private key"
                  type="password"
                  value={newProfile.private_key}
                  onChange={(e) => setNewProfile({ ...newProfile, private_key: e.target.value })}
                  className="rounded border border-border bg-card px-3 py-2 text-sm focus:border-primary focus:outline-none"
                />
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Toggle checked={newProfile.multi_exec} onChange={(v) => setNewProfile({ ...newProfile, multi_exec: v })} />
                  <span className="text-sm text-muted-foreground">Multi-exec</span>
                </div>
                <button
                  onClick={handleAddProfile}
                  disabled={!newProfile.name || profileSaving}
                  className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {profileSaving ? "Saving..." : "Save Profile"}
                </button>
              </div>
            </div>
          )}

          {activeProfile && (
            <div className="mb-3 rounded bg-primary/10 p-3">
              <p className="text-sm font-medium">Active: {activeProfile.name}</p>
              <p className="text-xs text-muted-foreground font-mono mt-1">
                {activeProfile.wallet_address ? activeProfile.wallet_address.slice(0, 10) + "..." + activeProfile.wallet_address.slice(-6) : "No wallet set"}
              </p>
            </div>
          )}

          <div className="space-y-2">
            {profiles.map((p: any) => (
              <div key={p.name} className="flex items-center justify-between border-b border-border pb-3 last:border-0">
                <div>
                  <span className="text-sm font-medium">{p.name}</span>
                  <p className="text-xs text-muted-foreground font-mono">
                    {p.wallet_address ? p.wallet_address.slice(0, 10) + "..." + p.wallet_address.slice(-6) : "no wallet"}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5">
                    <Toggle checked={!!p.multi_exec} onChange={(v) => handleToggleMultiExec(p.name, v)} />
                    <span className="text-xs text-muted-foreground">multi</span>
                  </div>
                  {activeProfile?.name !== p.name && (
                    <button
                      onClick={() => handleActivateProfile(p.name)}
                      className="rounded border border-primary/50 px-2 py-1 text-xs text-primary hover:bg-primary/10"
                    >
                      Activate
                    </button>
                  )}
                  <button
                    onClick={() => handleDeleteProfile(p.name)}
                    className="rounded border border-destructive/50 px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="mb-4 text-lg font-semibold">Notifications</h2>
          <div className="space-y-3">
            <label className="block text-sm text-muted-foreground">Slack Webhook URL</label>
            <div className="flex gap-2">
              <input
                type="url"
                placeholder="https://hooks.slack.com/services/..."
                value={slackUrl}
                onChange={(e) => setSlackUrl(e.target.value)}
                className="flex-1 rounded border border-border bg-background px-3 py-2 text-sm font-mono focus:border-primary focus:outline-none"
              />
              <button
                onClick={handleSaveSlack}
                disabled={slackSaving}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {slackSaving ? "..." : "Save"}
              </button>
            </div>
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${notifications?.slack_webhook ? "bg-green-500" : "bg-muted-foreground"}`} />
              <span className="text-xs text-muted-foreground">
                {notifications?.slack_webhook ? "Connected" : "Not configured"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
