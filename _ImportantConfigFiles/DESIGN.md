# PolyMarket Bot — Design Spec

## Design Direction
- Visual inspiration: DefibotX (layout, card style, metric tiles, chart patterns only)
- **Dark mode default**, light mode toggle
- Card-based layout with clean metric tiles and area charts
- Inter font, Lucide icons, rounded-md cards

## Framework
- **Next.js 14** App Router
- **Tailwind CSS** with CSS custom properties (HSL)
- **shadcn/ui** component patterns (Radix-compatible)
- **Recharts** for charts (area, bar, line)
- **PWA** via manifest.json — installable on iOS home screen

## Color Palette
### Dark Mode (Default)
- Background: `hsl(222, 47%, 11%)` — slate-900
- Cards: `hsl(217, 33%, 17%)` — slate-800
- Primary: `hsl(217, 91%, 60%)` — blue-500
- Accent: `hsl(43, 74%, 49%)` — gold (#D4AF37)
- Text: `hsl(210, 40%, 98%)` — slate-50
- Muted text: `hsl(215, 20%, 65%)`
- Border: `hsl(217, 33%, 17%)`

### Light Mode
- Background: `hsl(0, 0%, 98%)` — gray-50
- Cards: `hsl(0, 0%, 100%)` — white
- Primary: `hsl(221, 83%, 53%)` — blue-600
- Text: `hsl(222, 47%, 11%)` — gray-900
- Border: `hsl(214, 32%, 91%)`

## Navigation
Sidebar on desktop (w-56), hidden on mobile (future: bottom tab bar):
1. **Dashboard** — Metric cards, performance chart, insights
2. **Modules** — Auction module list, per-module detail
3. **Portfolio** — Open positions, P&L, exposure breakdown
4. **Trades** — Order history, fills, export CSV
5. **Analytics** — Sharpe, Sortino, drawdown, calibration
6. **Logs** — Decision/execution/system/risk, filterable, searchable
7. **Settings** — Risk params, trading mode, stat tests, notifications

## Key Components
### Metric Cards (top row, 4 across)
- Portfolio Value, Total Profit, Win Rate, Active Modules
- Icon top-right, value large, change % below

### Performance Chart
- Area chart with gradient fill
- Time range: 24h | 7d | 30d | 90d | All

### Module Cards
- Name, strategy, status badge, P&L, position count
- Click → module detail page

### Data Table (reusable)
- Sortable columns, hover highlight, empty state

### Status Badges
- active (green), paused (yellow), paper (blue), scaffold (gray), error (red)

## Responsive
- Desktop: sidebar + main content
- Mobile: single column, sidebar hidden (future bottom tab)

## PWA
- manifest.json: standalone display, dark theme color
- Icons: 192px + 512px (placeholder — need to create)
