"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PnlPoint } from "@/lib/types";
import { fmtUsd } from "@/lib/format";

const RANGES = ["1D", "1W", "1M", "1Y", "YTD", "ALL"] as const;
type Range = (typeof RANGES)[number];

function rangeStart(r: Range): number {
  const now = Date.now();
  const day = 86_400_000;
  switch (r) {
    case "1D":
      return now - day;
    case "1W":
      return now - 7 * day;
    case "1M":
      return now - 30 * day;
    case "1Y":
      return now - 365 * day;
    case "YTD":
      return new Date(new Date().getFullYear(), 0, 1).getTime();
    default:
      return 0;
  }
}

export default function PnlHero({
  series,
  label = "Profit / Loss · Realized",
}: {
  series: PnlPoint[];
  label?: string;
}) {
  const [range, setRange] = useState<Range>("ALL");
  const elRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const areaRef = useRef<any>(null);

  // running cumulative over ALL points (absolute curve), sorted ascending
  const cumulative = useMemo(() => {
    const sorted = [...series].sort(
      (a, b) => new Date(a.t).getTime() - new Date(b.t).getTime()
    );
    let cum = 0;
    return sorted.map((p) => {
      cum += p.d ?? 0;
      return { ms: new Date(p.t).getTime(), cum };
    });
  }, [series]);

  const total = cumulative.length ? cumulative[cumulative.length - 1].cum : 0;

  useEffect(() => {
    let disposed = false;
    (async () => {
      const lc = await import("lightweight-charts");
      if (disposed || !elRef.current || chartRef.current) return;
      const chart = lc.createChart(elRef.current, {
        autoSize: true,
        layout: {
          background: { type: lc.ColorType.Solid, color: "transparent" },
          textColor: "#5c6b82",
          fontFamily: "ui-monospace, monospace",
          fontSize: 11,
        },
        grid: {
          vertLines: { visible: false },
          horzLines: { color: "#141b26" },
        },
        rightPriceScale: { borderColor: "#1c2432" },
        timeScale: {
          borderColor: "#1c2432",
          timeVisible: true,
          secondsVisible: false,
        },
        crosshair: { mode: lc.CrosshairMode.Magnet },
      });
      areaRef.current = chart.addAreaSeries({
        lineColor: "#e0b341",
        topColor: "rgba(224,179,65,0.35)",
        bottomColor: "rgba(34,197,94,0.02)",
        lineWidth: 2,
        priceFormat: {
          type: "custom",
          formatter: (v: number) => "$" + v.toFixed(0),
          minMove: 0.01,
        },
      });
      chartRef.current = chart;
      draw();
    })();
    return () => {
      disposed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        areaRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function draw() {
    const area = areaRef.current;
    if (!area) return;
    const start = rangeStart(range);
    const bySec = new Map<number, number>();
    for (const pt of cumulative) {
      if (pt.ms < start) continue;
      bySec.set(Math.floor(pt.ms / 1000), pt.cum);
    }
    const data = Array.from(bySec.entries())
      .sort((a, b) => a[0] - b[0])
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .map(([time, value]) => ({ time: time as any, value }));
    area.setData(data);
    if (data.length) chartRef.current?.timeScale().fitContent();
  }

  useEffect(() => {
    draw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, cumulative]);

  return (
    <section className="rounded border border-term-border bg-term-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-widest text-term-muted">
            {label}
          </div>
          <div className="mt-1 text-4xl font-bold tabular-nums text-term-text">
            {fmtUsd(total)}
          </div>
          <div className="mt-1 text-xs text-term-muted">
            Cumulative realized P/L
          </div>
        </div>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`rounded px-2 py-1 text-xs ${
                range === r
                  ? "bg-term-gold/20 text-term-gold"
                  : "text-term-muted hover:text-term-text"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div className="relative mt-3 h-64 w-full">
        <div ref={elRef} className="h-full w-full" />
        {cumulative.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-term-muted">
            no closed P/L yet — paper trading is banking data
          </div>
        )}
      </div>
    </section>
  );
}
