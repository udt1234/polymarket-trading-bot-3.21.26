"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  createChart,
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
} from "lightweight-charts";
import { SnapshotData } from "@/lib/types";

// price_snapshots.bracket is stored as "<market-slug>|<bracket>".
function splitKey(key: string): { market: string; bracket: string } {
  const i = key.indexOf("|");
  return i === -1
    ? { market: key, bracket: key }
    : { market: key.slice(0, i), bracket: key.slice(i + 1) };
}

export default function PricePanel({
  data,
  onSelectBracket,
}: {
  data: SnapshotData | null;
  onSelectBracket: (bracket: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const hasPoints = !!data && data.points.length > 0;
  const selected = data?.bracket ?? null;

  const markets = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const key of data?.brackets ?? []) {
      const { market } = splitKey(key);
      map.set(market, [...(map.get(market) ?? []), key]);
    }
    return map;
  }, [data?.brackets]);

  const selectedMarket = selected ? splitKey(selected).market : null;

  useEffect(() => {
    if (!hasPoints || !containerRef.current) return;
    const chart = createChart(containerRef.current, {
      height: 260,
      layout: {
        background: { color: "#10151d" },
        textColor: "#5c6b82",
        fontFamily: "ui-monospace, Menlo, Consolas, monospace",
      },
      grid: {
        vertLines: { color: "#1c2432" },
        horzLines: { color: "#1c2432" },
      },
      rightPriceScale: { borderColor: "#1c2432" },
      timeScale: { borderColor: "#1c2432", timeVisible: true },
    });
    chartRef.current = chart;
    seriesRef.current = chart.addLineSeries({
      color: "#38bdf8",
      lineWidth: 2,
    });
    const observer = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [hasPoints]);

  useEffect(() => {
    if (!hasPoints || !seriesRef.current || !data) return;
    seriesRef.current.setData(
      data.points.map((p) => ({
        time: Math.floor(
          new Date(p.snapshot_hour).getTime() / 1000
        ) as UTCTimestamp,
        value: p.price,
      }))
    );
    chartRef.current?.timeScale().fitContent();
  }, [data, hasPoints]);

  const selectClass =
    "rounded border border-term-border bg-term-bg px-2 py-1 text-xs text-term-text focus:outline-none";

  return (
    <div className="p-3">
      {markets.size > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <select
            className={selectClass}
            value={selectedMarket ?? ""}
            onChange={(e) => {
              const first = markets.get(e.target.value)?.[0];
              if (first) onSelectBracket(first);
            }}
          >
            {Array.from(markets.keys()).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <select
            className={selectClass}
            value={selected ?? ""}
            onChange={(e) => onSelectBracket(e.target.value)}
          >
            {(selectedMarket ? markets.get(selectedMarket) ?? [] : []).map(
              (key) => (
                <option key={key} value={key}>
                  {splitKey(key).bracket}
                </option>
              )
            )}
          </select>
        </div>
      )}
      {hasPoints ? (
        <div ref={containerRef} className="w-full" />
      ) : (
        <p className="py-8 text-center text-term-muted">
          snapshots accruing — chart appears once price_snapshots has data
        </p>
      )}
    </div>
  );
}
