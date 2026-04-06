"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Card } from "@/components/shared/card"

const tabs = [
  { id: "setup", label: "Setup Notes" },
  { id: "trump", label: "Trump Module" },
  { id: "elon", label: "Elon Module" },
  { id: "strategies", label: "How It Works" },
  { id: "data-sources", label: "Data Sources" },
  { id: "risk", label: "Risk Rules" },
  { id: "changelog", label: "Changelog" },
]

function Badge({ children, variant = "default" }: { children: React.ReactNode; variant?: string }) {
  const colors: Record<string, string> = {
    default: "bg-primary/10 text-primary", green: "bg-green-500/10 text-green-400",
    yellow: "bg-yellow-500/10 text-yellow-400", blue: "bg-blue-500/10 text-blue-400",
    red: "bg-red-500/10 text-red-400", purple: "bg-purple-500/10 text-purple-400",
    orange: "bg-orange-500/10 text-orange-400",
  }
  return <span className={cn("inline-block rounded-full px-2 py-0.5 text-xs font-medium", colors[variant] || colors.default)}>{children}</span>
}

function Callout({ children, type = "info" }: { children: React.ReactNode; type?: string }) {
  const styles: Record<string, string> = {
    info: "border-blue-500/30 bg-blue-500/5", warning: "border-yellow-500/30 bg-yellow-500/5",
    important: "border-red-500/30 bg-red-500/5", tip: "border-green-500/30 bg-green-500/5",
  }
  return <div className={cn("rounded-md border-l-4 p-3 text-xs text-muted-foreground", styles[type])}>{children}</div>
}

function SetupNotes() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">Environment Variables Required</h3>
        <Callout type="important">
          <strong>All of these must be in your .env file.</strong> Without them, the corresponding features silently return neutral/empty data.
        </Callout>
        <div className="mt-3 space-y-2 text-xs">
          {[
            { key: "POLYMARKET_API_KEY + SECRET + PASSPHRASE + PRIVATE_KEY", note: "Required for live trading. Paper mode works without these." },
            { key: "SUPABASE_URL + SUPABASE_ANON_KEY + SUPABASE_SERVICE_KEY", note: "Required. Nothing works without Supabase." },
            { key: "LUNARCRUSH_API_KEY", note: "Powers engagement velocity + social dominance (25% of signal modifier). Without it, returns neutral 1.0x." },
            { key: "ANTHROPIC_API_KEY", note: "Powers Claude Haiku regime override from news. ~$0.01/call, ~$4/day at 5-min cycles. Without it, falls back to z-score only." },
          ].map((v) => (
            <div key={v.key} className="rounded-md bg-accent/30 p-2">
              <code className="text-[10px] font-bold text-primary">{v.key}</code>
              <p className="mt-1 text-muted-foreground">{v.note}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Python Dependencies</h3>
        <Callout type="warning">Run <code>pip install pytrends</code> for Google Trends. Without it, trends signal returns flat (no error, just no data).</Callout>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Database Migration</h3>
        <Callout type="important">Run <code>003_add_signal_metadata.sql</code> on Supabase to add metadata JSONB column to signals table. Without it, signal context data won't persist.</Callout>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Historical Data Setup</h3>
        <p className="mb-2 text-xs text-muted-foreground">Run these scripts to seed historical data for better predictions:</p>
        <div className="space-y-1 text-xs font-mono text-muted-foreground">
          <p>python scripts/fetch_historical_auctions.py --handle realDonaldTrump</p>
          <p>python scripts/fetch_historical_auctions.py --handle elonmusk</p>
        </div>
        <Callout type="tip">This pulls all past xTracker auctions with daily stats. More history = better DOW averages and regime detection.</Callout>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Signal Modifier Weights (Remember This)</h3>
        <Callout type="important">
          <strong>The signal modifier is a multiplier (0.5x to 1.5x) that adjusts predicted post counts up or down.</strong><br/>
          It's blended from 4 sources with these fixed weights:
        </Callout>
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md bg-accent/30 p-2"><Badge variant="green">40%</Badge> Google News RSS — headline volume + conflict + events</div>
          <div className="rounded-md bg-accent/30 p-2"><Badge variant="purple">25%</Badge> LunarCrush — engagement velocity + social dominance</div>
          <div className="rounded-md bg-accent/30 p-2"><Badge variant="yellow">20%</Badge> Presidential/Public Schedule — rally, court, travel</div>
          <div className="rounded-md bg-accent/30 p-2"><Badge variant="blue">15%</Badge> Google Trends — "Trump Truth Social" interest momentum</div>
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Ensemble Weights (Remember This)</h3>
        <Callout type="info">
          <strong>5 pacing models predict the final count. Their weights shift by auction progress:</strong><br/>
          Early = trust history. Late = trust observed pace. Hawkes gets 15% during bursts, 8% normally.<br/>
          Calibration feedback adjusts all weights +/-20% based on which models have been most accurate recently.
        </Callout>
      </Card>
    </div>
  )
}

function TrumpModule() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">Trump Truth Social Module</h3>
        <p className="text-sm text-muted-foreground">Predicts weekly Truth Social post count brackets (0-19 through 200+).</p>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Schedule Impact Modifiers</h3>
        <Callout type="important">These multiply the predicted post count. A rally day means we expect 25% more posts than normal.</Callout>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-border text-left text-muted-foreground">
              <th className="pb-2 pr-4">Event</th><th className="pb-2 pr-4">Modifier</th><th className="pb-2">Effect on Prediction</th>
            </tr></thead>
            <tbody>
              {[
                { event: "Rally / Campaign Event", mod: "1.25x", effect: "Expect 25% more posts. Pre-rally hype + post-rally energy.", color: "red" },
                { event: "Court / Trial / Hearing", mod: "1.30x", effect: "Expect 30% more posts. Highest engagement trigger.", color: "red" },
                { event: "Speech / Address", mod: "1.15x", effect: "Expect 15% more posts. Usually pre/post commentary.", color: "yellow" },
                { event: "Press Conference", mod: "1.20x", effect: "Expect 20% more posts. Follow-up reactions.", color: "yellow" },
                { event: "Debate", mod: "1.20x", effect: "Expect 20% more posts. Live-commentary + aftermath.", color: "yellow" },
                { event: "Golf Weekend", mod: "1.05x", effect: "Expect 5% more posts. Still posts, just slightly more relaxed.", color: "green" },
                { event: "Domestic Travel", mod: "0.85x", effect: "Expect 15% fewer posts. Limited connectivity windows.", color: "blue" },
                { event: "Foreign Travel", mod: "0.70x", effect: "Expect 30% fewer posts. Jet lag + meetings + limited posting.", color: "blue" },
                { event: "Camp David", mod: "0.80x", effect: "Expect 20% fewer posts. Retreat = lower activity.", color: "blue" },
                { event: "Vacation / Mar-a-Lago", mod: "0.75x", effect: "Expect 25% fewer posts. Relaxation mode.", color: "blue" },
                { event: "State Dinner", mod: "0.90x", effect: "Expect 10% fewer posts. Occupied with formalities.", color: "blue" },
                { event: "Executive Order / Signing", mod: "1.15x", effect: "Expect 15% more posts. Announcement + follow-up.", color: "yellow" },
                { event: "Fundraiser", mod: "1.10x", effect: "Expect 10% more posts. Energized base engagement.", color: "yellow" },
              ].map((r) => (
                <tr key={r.event} className="border-b border-border/50">
                  <td className="py-1.5 pr-4 font-medium">{r.event}</td>
                  <td className="py-1.5 pr-4"><Badge variant={r.color}>{r.mod}</Badge></td>
                  <td className="py-1.5 text-muted-foreground">{r.effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Data Sources (Trump-Specific)</h3>
        <div className="space-y-2 text-xs">
          {[
            { src: "xTracker", desc: "Primary post counter. Resolution source for Polymarket. ~5-15 min lag.", badge: "Active" },
            { src: "CNN Archive", desc: "ix.cnn.io — backup counter updated every 5 min. Cross-referenced for count divergence. Also used for historical hourly data import.", badge: "Active" },
            { src: "Factbase Schedule", desc: "media-cdn.factba.se — structured presidential schedule from WH Press Office + pool reports. Updates daily. Primary schedule source.", badge: "Active" },
            { src: "Google News RSS", desc: "4 queries: 'Trump', 'Trump Truth Social', 'Trump rally speech', 'Trump court trial'", badge: "Active" },
            { src: "LunarCrush", desc: "Engagement velocity + social dominance for @realDonaldTrump. Leading indicator of posting momentum.", badge: "Active" },
            { src: "Google Trends", desc: "'Trump Truth Social' interest-over-time. Surging interest = behavioral momentum.", badge: "Active" },
            { src: "Claude Haiku", desc: "Reads top 10 headlines, classifies regime. Overrides z-score when news context is stronger.", badge: "Active" },
          ].map((s) => (
            <div key={s.src} className="flex items-start gap-2 rounded-md bg-accent/30 p-2">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{s.src}</span>
                  <Badge variant={s.badge === "Active" ? "green" : "yellow"}>{s.badge}</Badge>
                </div>
                <p className="mt-0.5 text-muted-foreground">{s.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Regime Override Logic</h3>
        <p className="mb-2 text-xs text-muted-foreground">
          Every cycle, Claude Haiku reads the top 10 headlines and classifies the current "vibe":
        </p>
        <Callout type="info">
          If Claude says SURGE but the z-score says NORMAL, Claude wins. This catches breaking events
          (indictment, major feud) that the statistical model won't see for hours.
        </Callout>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Count Verification</h3>
        <Callout type="tip">
          xTracker and CNN both count posts, but use slightly different rules. When they disagree by 2+ posts,
          the bot logs it. If CNN sees more posts, it likely means xTracker hasn't caught up yet — you may
          have an information edge on other traders who only watch xTracker.
        </Callout>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Historical Data (CNN Archive Import)</h3>
        <p className="mb-2 text-xs text-muted-foreground">
          The CNN archive has millisecond-precision timestamps for every Trump Truth Social post.
          Running the import script creates hourly posting patterns that the bot uses as its baseline.
        </p>
        <Callout type="important">
          <strong>Run this to seed historical data:</strong><br/>
          <code>python scripts/import_cnn_archive.py</code><br/><br/>
          This creates hourly/daily/weekly aggregations + DOW and hour-of-day averages.
          The bot automatically loads these cross-week hourly patterns instead of relying only on
          current-week data from xTracker.
        </Callout>
        <p className="mt-2 text-xs text-muted-foreground">
          Available formats: JSON, CSV, and Parquet (script tries Parquet first — 10x faster download).
        </p>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Schedule Source Details</h3>
        <Callout type="info">
          <strong>Primary:</strong> Factbase (media-cdn.factba.se) — structured JSON from WH Press Office + pool reports. Updates daily at midnight ET.<br/><br/>
          <strong>Fallback:</strong> Google News RSS for "Trump schedule OR rally OR travel OR court".<br/><br/>
          <strong>Note:</strong> WhiteHouse.gov has no public schedule API (removed after Obama era). OpenSecrets API was shut down April 2025. FEC API has financial data only, not events. Factbase is the best free source.
        </Callout>
      </Card>
    </div>
  )
}

function ElonModule() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">Elon Musk Tweets Module</h3>
        <p className="text-sm text-muted-foreground">Predicts tweet count brackets (dynamic from market). Supports weekly and monthly auctions.</p>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Key Differences from Trump</h3>
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">No presidential schedule.</strong> Signal modifier is: News 60% + LunarCrush 40%.
          </div>
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">Dynamic brackets.</strong> Bracket labels are read from Gamma API, not hardcoded. Different markets have different ranges.
          </div>
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">Variable auction length.</strong> Some Elon markets are monthly (30 days), not weekly. Ensemble weights use percentages so they adapt automatically.
          </div>
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">No CNN archive.</strong> No free equivalent for X/Twitter. Count verification only via xTracker.
          </div>
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-base font-semibold">Elon-Specific Signals</h3>
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">LunarCrush is critical here.</strong> Elon's engagement velocity (likes/replies per tweet) directly predicts whether he'll keep tweeting. High velocity = dopamine loop = more tweets.
          </div>
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">Hawkes model matters more.</strong> Elon has extreme burst patterns — reply storms, multi-tweet threads, 3am posting sprees. Hawkes captures this self-exciting behavior.
          </div>
          <div className="rounded-md bg-accent/30 p-2">
            <strong className="text-foreground">News queries:</strong> 'Elon Musk', 'Elon Musk Twitter', 'Elon Musk SpaceX Tesla', 'Elon Musk DOGE'
          </div>
        </div>
      </Card>
    </div>
  )
}

function HowItWorks() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">The Full Pipeline (Every 5 Minutes)</h3>
        <div className="space-y-2">
          {[
            { step: "1", title: "Fetch Data", desc: "Pull post counts from xTracker, market prices from Gamma, news from Google RSS, social metrics from LunarCrush, schedule events, and Google Trends." },
            { step: "2", title: "Detect Regime", desc: "Z-score from 12-week history classifies as SURGE/HIGH/NORMAL/LOW/QUIET. Then Claude Haiku reads headlines and can override if it sees something the math missed." },
            { step: "3", title: "Run 5 Pacing Models", desc: "Each model independently predicts final post count. Linear extrapolation, Bayesian blend, DOW-hourly patterns, historical average, and Hawkes burst model." },
            { step: "4", title: "Blend with Weights", desc: "Models are weighted by auction progress (early = trust history, late = trust pace) and adjusted by calibration feedback (+/-20%)." },
            { step: "5", title: "Convert to Bracket Probabilities", desc: "Negative Binomial + Normal distribution converts predicted count into probability for each bracket (0-19, 20-39, ..., 200+)." },
            { step: "6", title: "Apply Signal Modifiers", desc: "News (40%) + LunarCrush (25%) + Schedule (20%) + Trends (15%) adjust predictions up or down based on external context." },
            { step: "7", title: "Find Edge", desc: "Compare model probability to market price for each bracket. Edge = model_prob - market_price. Only trade brackets with positive edge." },
            { step: "8", title: "Size with Kelly", desc: "Fractional Kelly (0.25x) determines bet size. Adjusted for regime, volatility, and time remaining." },
            { step: "9", title: "Risk Check (15 gates)", desc: "All 15 risk checks must pass. Any failure = signal rejected." },
            { step: "10", title: "Execute", desc: "Paper mode simulates. Live mode places order on Polymarket via CLOB API." },
          ].map((s) => (
            <div key={s.step} className="flex gap-3 rounded-md bg-accent/30 p-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-bold text-primary">{s.step}</span>
              <div><p className="text-sm font-medium">{s.title}</p><p className="text-xs text-muted-foreground">{s.desc}</p></div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function DataSources() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">All Active Data Sources</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-border text-left text-muted-foreground">
              <th className="pb-2 pr-4">Source</th><th className="pb-2 pr-4">Purpose</th><th className="pb-2 pr-4">Latency</th><th className="pb-2">Modules</th>
            </tr></thead>
            <tbody>
              {[
                { src: "xTracker API", purpose: "Post counts + tracking periods", lat: "~5-15 min", modules: "Both" },
                { src: "CNN Archive", purpose: "Truth Social count verification", lat: "~5 min", modules: "Trump" },
                { src: "Gamma API", purpose: "Prices, brackets, volume", lat: "~1 sec", modules: "Both" },
                { src: "CLOB API", purpose: "Order book + execution", lat: "~1 sec", modules: "Both" },
                { src: "Google News RSS", purpose: "4 queries: headlines + conflict + events", lat: "~2 sec", modules: "Both" },
                { src: "LunarCrush API", purpose: "Engagement velocity + social dominance", lat: "~2 sec", modules: "Both" },
                { src: "Claude Haiku API", purpose: "News regime classification", lat: "~1-2 sec", modules: "Both" },
                { src: "Presidential Schedule", purpose: "Travel/rally/court/golf modifiers", lat: "~2 sec", modules: "Trump" },
                { src: "Google Trends", purpose: "Interest-over-time momentum", lat: "~3 sec", modules: "Trump" },
                { src: "Polymarket Parquet", purpose: "Historical price data (S3)", lat: "Cached", modules: "Both" },
              ].map((d) => (
                <tr key={d.src} className="border-b border-border/50">
                  <td className="py-1.5 pr-4 font-medium">{d.src}</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">{d.purpose}</td>
                  <td className="py-1.5 pr-4">{d.lat}</td>
                  <td className="py-1.5"><Badge variant={d.modules === "Both" ? "blue" : "purple"}>{d.modules}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function RiskRules() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">15 Pre-Trade Risk Checks</h3>
        <Callout type="important">Every signal must pass ALL 15 checks. One failure = rejected. No exceptions.</Callout>
        <div className="mt-3 space-y-1">
          {[
            "Circuit breaker: Halt after 5 consecutive losses (30-min cooldown)",
            "Edge threshold: Minimum 2% edge over market price",
            "Kelly validation: Only positive Kelly bets allowed",
            "Position cap: Max 15% of bankroll per market",
            "Daily loss limit: Stop if daily loss > 5% of bankroll",
            "Weekly loss limit: Stop if weekly loss > 10% of bankroll",
            "Max drawdown: Stop if peak-to-current > 15%",
            "Portfolio exposure: Total open positions < 50% of bankroll",
            "Single market: One market < 15% of bankroll",
            "Correlated exposure: Similar positions < 30%",
            "Duplicate prevention: Requires 3%+ edge improvement to add",
            "Cross-module: Flags when 2+ modules signal same direction",
            "Settlement decay: Reduces size as market approaches resolution",
            "Spread check: Rejects trades with wide bid-ask spreads",
            "Liquidity check: Verifies order book has sufficient depth",
          ].map((rule, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">{i + 1}</span>
              <span className="text-muted-foreground">{rule}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}

function ChangelogTab() {
  return (
    <div className="space-y-4">
      <Card>
        <h3 className="mb-3 text-base font-semibold">Recent Changes</h3>
        {[
          { date: "2026-04-01 (Session 3)", items: [
            "Added WhiteHouse.gov + FEC schedule sources (planned)",
            "Added CNN archive hourly data import into Trump module",
            "Added module-specific notes tabs (Trump + Elon)",
            "Added setup notes with env var requirements + weight references",
            "Added Polymarket volume data fetcher per bracket",
            "Added Google Trends momentum signal (15% weight)",
            "Added CNN Truth Social archive for count verification",
            "Added cross-bracket arbitrage detection",
            "Added contrarian bracket signals",
            "Added order book depth sizing",
          ]},
          { date: "2026-04-01 (Session 2)", items: [
            "Added Hawkes Process as 5th pacing model",
            "Added Claude Haiku regime override from news",
            "Added LunarCrush velocity + dominance signals",
            "Added Presidential schedule modifiers",
            "Added calibration-driven ensemble weight adjustment",
            "Fixed DOW weights (were hardcoded to 1.0)",
            "Fixed auction timing (was truncating to date-only)",
            "Upgraded ensemble to percentage-based (monthly compatible)",
            "Upgraded Elon module with all new features",
            "Added signal metadata with full context",
          ]},
        ].map((entry) => (
          <div key={entry.date} className="mb-4">
            <p className="mb-1 text-sm font-medium">{entry.date}</p>
            <ul className="space-y-0.5">
              {entry.items.map((item, i) => (
                <li key={i} className="text-xs text-muted-foreground">+ {item}</li>
              ))}
            </ul>
          </div>
        ))}
      </Card>
    </div>
  )
}

export default function NotesPage() {
  const [activeTab, setActiveTab] = useState("setup")

  const tabContent: Record<string, JSX.Element> = {
    setup: <SetupNotes />, trump: <TrumpModule />, elon: <ElonModule />,
    strategies: <HowItWorks />, "data-sources": <DataSources />,
    risk: <RiskRules />, changelog: <ChangelogTab />,
  }

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-bold">Notes</h1>
      <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1">
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={cn("rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              activeTab === tab.id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent")}>
            {tab.label}
          </button>
        ))}
      </div>
      {tabContent[activeTab]}
    </div>
  )
}
