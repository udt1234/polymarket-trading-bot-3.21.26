# PolyMarket Bot — Design Spec

## Design Direction
- Inspired by DefibotX/Envato Market: dark cards, clean metrics, area charts
- **Light mode default**, dark mode toggle (top-right)
- Card-based layout: Portfolio Value, Total Profit, Win Rate, Market Condition across top
- Performance chart with time range selector (24h / 7d / 30d / 90d / All)

## Framework
- **Next.js 14+** App Router
- **Tailwind CSS** for utility styling
- **shadcn/ui** component library (Radix primitives + Tailwind)
- **Recharts** for charts (area, bar, line, pie)
- **PWA** via next-pwa — installable on iOS home screen

## Color Palette
### Light Mode (Default)
- Background: `#FAFAFA` (gray-50)
- Cards: `#FFFFFF` with `border-gray-200`
- Primary: `#2563EB` (blue-600)
- Success: `#16A34A` (green-600)
- Danger: `#DC2626` (red-600)
- Text: `#111827` (gray-900)

### Dark Mode
- Background: `#0F172A` (slate-900)
- Cards: `#1E293B` (slate-800)
- Primary: `#3B82F6` (blue-500)
- Accent: `#D4AF37` (gold — from XA style guide)
- Text: `#F8FAFC` (slate-50)

## Navigation
Tab bar (bottom on mobile, sidebar on desktop):
1. **Overview** — Portfolio summary, top metrics, performance chart, AI insights
2. **Portfolio** — Open positions, P&L per market, exposure breakdown
3. **Strategy** — Module list, per-module config, A/B test results
4. **Trades** — Trade log, order history, fill rates
5. **Logs** — Decision, execution, system, risk logs (filterable, searchable)
6. **Settings** — Global risk params, statistical tests, notifications, theme toggle

## Key Components

### Metric Cards (top row)
```
[Portfolio Value] [Total Profit] [Win Rate] [Active Markets]
    $1,234.56      +$234.56       67.3%         4
```

### Performance Chart
- Area chart with gradient fill
- Time range selector: 24h | 7d | 30d | 90d | All
- Overlay: benchmark line (if applicable)

### Module Cards (Strategy tab)
- Market name, status badge (active/paused/paper)
- Current P&L, position count, strategy name
- Quick actions: pause, configure, view trades

### Trade Log Table
- Columns: Time, Market, Side, Size, Price, Status, P&L
- Sortable, filterable, exportable (CSV)
- Color-coded: green fills, red losses, gray pending

## Responsive Breakpoints
- Mobile: < 640px — single column, bottom tab bar
- Tablet: 640-1024px — two columns, side tab bar
- Desktop: > 1024px — full layout, sidebar nav

## PWA Config
- `manifest.json`: name, icons (192/512px), theme_color, display: standalone
- Service worker: cache API responses, offline fallback page
- iOS: apple-touch-icon, apple-mobile-web-app-capable
