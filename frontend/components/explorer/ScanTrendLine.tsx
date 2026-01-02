/**
 * ScanTrendLine - Minimal sparkline for scan history
 *
 * Architecture: SVG for trend line, HTML/CSS for event markers
 * Time-based positioning with dynamic window sizing
 */

"use client";

import { useState, useMemo } from "react";
import { useScanHistory } from "@/lib/hooks/useScanHistory";
import { cn } from "@/lib/utils";

interface ScanTrendLineProps {
  projectId: string;
  className?: string;
}

interface ProcessedScan {
  id: number;
  started_at: string;
  triggered_by: string;
  metrics: Record<string, unknown>;
  complexity: number | null;
  delta: string;
  xPosition: number;
}

const TRIGGER_COLORS: Record<string, string> = {
  refactor_it: "#a855f7",
  og_refactor_it: "#a855f7",
  scheduled: "#22c55e",
  celery_beat: "#22c55e",
  daily_qa_scan: "#22c55e",
  manual: "#3b82f6",
  test: "#64748b",
};

const TRIGGER_LABELS: Record<string, string> = {
  refactor_it: "Refactor",
  og_refactor_it: "Refactor",
  scheduled: "Scheduled",
  celery_beat: "Scheduled",
  daily_qa_scan: "QA Scan",
  manual: "Manual",
  test: "Test",
};

function getTriggerColor(trigger: string): string {
  return TRIGGER_COLORS[trigger] || "#64748b";
}

function getTriggerLabel(trigger: string): string {
  return TRIGGER_LABELS[trigger] || trigger.replace(/_/g, " ");
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

// Calculate dynamic time window based on scan timestamps
function calculateTimeWindow(scans: { started_at: string }[]): { start: number; end: number } {
  const now = Date.now();
  const DAY_MS = 24 * 60 * 60 * 1000;
  const MIN_WINDOW = DAY_MS;
  const MAX_WINDOW = 30 * DAY_MS;

  if (scans.length === 0) return { start: now - MAX_WINDOW, end: now };

  const timestamps = scans.map((s) => new Date(s.started_at).getTime());
  const oldest = Math.min(...timestamps);
  const newest = Math.max(...timestamps);
  const padding = Math.max((newest - oldest) * 0.15, 2 * 60 * 60 * 1000);

  let windowStart = oldest - padding;
  let windowEnd = Math.min(newest + padding, now);

  if (windowEnd - windowStart < MIN_WINDOW) {
    const center = (windowStart + windowEnd) / 2;
    windowStart = center - MIN_WINDOW / 2;
    windowEnd = Math.min(center + MIN_WINDOW / 2, now);
    if (windowEnd - windowStart < MIN_WINDOW) windowStart = windowEnd - MIN_WINDOW;
  }

  if (windowEnd - windowStart > MAX_WINDOW) windowStart = windowEnd - MAX_WINDOW;

  return { start: windowStart, end: windowEnd };
}

function getTimePosition(timestamp: number, start: number, end: number): number {
  const size = end - start;
  if (size <= 0) return 50;
  return Math.max(0, Math.min(100, ((timestamp - start) / size) * 100));
}

export function ScanTrendLine({ projectId, className }: ScanTrendLineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const { scans, isLoading, isError } = useScanHistory({ projectId, days: 30 });

  const timeWindow = useMemo(() => {
    if (!scans || scans.length === 0) return null;
    return calculateTimeWindow(scans);
  }, [scans]);

  // Process scans - use metrics.complexity directly from each scan
  const chartData = useMemo((): ProcessedScan[] | null => {
    if (!scans || scans.length === 0 || !timeWindow) return null;

    const sorted = [...scans].sort(
      (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
    );

    return sorted.map((scan, idx, arr): ProcessedScan => {
      const curr = typeof scan.metrics?.complexity === "number" ? scan.metrics.complexity : null;
      const prev = idx > 0 && typeof arr[idx - 1].metrics?.complexity === "number"
        ? (arr[idx - 1].metrics.complexity as number)
        : null;

      let delta = "—";
      if (curr !== null && prev !== null) {
        const diff = curr - prev;
        delta = diff > 0 ? `+${diff.toFixed(0)}` : diff < 0 ? diff.toFixed(0) : "±0";
      }

      return {
        id: scan.id,
        started_at: scan.started_at,
        triggered_by: scan.triggered_by,
        metrics: scan.metrics,
        complexity: curr,
        delta,
        xPosition: getTimePosition(new Date(scan.started_at).getTime(), timeWindow.start, timeWindow.end),
      };
    });
  }, [scans, timeWindow]);

  const hasComplexityData = chartData?.some((d) => d.complexity !== null) ?? false;

  // Build SVG paths for trend line
  const { linePath, areaPath } = useMemo(() => {
    if (!chartData) return { linePath: "", areaPath: "" };

    const points = chartData
      .filter((d) => d.complexity !== null)
      .map((d) => ({ x: d.xPosition, y: d.complexity as number }));

    if (points.length < 2) return { linePath: "", areaPath: "" };

    const minY = Math.min(...points.map((p) => p.y)) * 0.95;
    const maxY = Math.max(...points.map((p) => p.y)) * 1.05;
    const range = maxY - minY || 1;

    const scaled = points.map((p) => ({ x: p.x, y: 100 - ((p.y - minY) / range) * 100 }));

    let line = `M ${scaled[0].x} ${scaled[0].y}`;
    let area = `M ${scaled[0].x} 100 L ${scaled[0].x} ${scaled[0].y}`;

    for (let i = 1; i < scaled.length; i++) {
      const cpx = (scaled[i - 1].x + scaled[i].x) / 2;
      line += ` C ${cpx} ${scaled[i - 1].y}, ${cpx} ${scaled[i].y}, ${scaled[i].x} ${scaled[i].y}`;
      area += ` C ${cpx} ${scaled[i - 1].y}, ${cpx} ${scaled[i].y}, ${scaled[i].x} ${scaled[i].y}`;
    }

    area += ` L ${scaled[scaled.length - 1].x} 100 Z`;
    return { linePath: line, areaPath: area };
  }, [chartData]);

  if (isLoading) {
    return (
      <div className={cn("h-12 flex items-center justify-center", className)}>
        <div className="h-px w-20 bg-gradient-to-r from-transparent via-slate-600 to-transparent animate-pulse" />
      </div>
    );
  }

  if (isError || !chartData || chartData.length === 0) {
    return (
      <div className={cn("h-12 flex items-center justify-center", className)}>
        <span className="text-[10px] font-mono text-slate-600">No scan activity</span>
      </div>
    );
  }

  const hovered = hoveredIndex !== null ? chartData[hoveredIndex] : null;

  return (
    <div className={cn("h-12 relative", className)}>
      {/* Trend line SVG */}
      {hasComplexityData && linePath && (
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full"
          style={{ top: "8px", height: "calc(100% - 8px)" }}
        >
          <defs>
            <linearGradient id="scanAreaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#a855f7" stopOpacity="0.12" />
              <stop offset="100%" stopColor="#a855f7" stopOpacity="0" />
            </linearGradient>
          </defs>
          {areaPath && <path d={areaPath} fill="url(#scanAreaGrad)" />}
          <path
            d={linePath}
            fill="none"
            stroke="#a855f7"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      )}

      {/* Baseline when no complexity data */}
      {!hasComplexityData && (
        <div className="absolute left-0 right-0 h-px bg-slate-700/50" style={{ top: "50%" }} />
      )}

      {/* Event markers */}
      <div className="absolute inset-x-0 top-0 h-4 flex items-center">
        {chartData.map((scan, i) => {
          const color = getTriggerColor(scan.triggered_by);
          const isHovered = hoveredIndex === i;

          return (
            <div
              key={scan.id}
              className="absolute -translate-x-1/2"
              style={{ left: `${scan.xPosition}%` }}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              <div
                className={cn(
                  "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-all duration-200",
                  isHovered ? "w-3 h-3 opacity-40" : "w-2 h-2 opacity-0"
                )}
                style={{ backgroundColor: color, filter: "blur(3px)" }}
              />
              <div
                className={cn(
                  "relative rounded-full cursor-pointer transition-all duration-150",
                  isHovered ? "w-2 h-2" : "w-1.5 h-1.5"
                )}
                style={{ backgroundColor: color, boxShadow: isHovered ? `0 0 8px ${color}` : `0 0 4px ${color}50` }}
              />
            </div>
          );
        })}
      </div>

      {/* Tooltip */}
      {hovered && (
        <div
          className="absolute z-50 pointer-events-none"
          style={{
            left: `${hovered.xPosition}%`,
            top: 0,
            transform: `translateX(${hovered.xPosition > 75 ? "-100%" : hovered.xPosition < 25 ? "0%" : "-50%"}) translateY(-100%)`,
            paddingBottom: "8px",
          }}
        >
          <div
            className="bg-slate-900/95 backdrop-blur-sm border rounded px-2 py-1.5 shadow-xl whitespace-nowrap"
            style={{ borderColor: `${getTriggerColor(hovered.triggered_by)}40` }}
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: getTriggerColor(hovered.triggered_by), boxShadow: `0 0 4px ${getTriggerColor(hovered.triggered_by)}` }}
              />
              <span className="text-[10px] font-mono text-slate-200">{getTriggerLabel(hovered.triggered_by)}</span>
            </div>
            <div className="text-[9px] font-mono text-slate-500">{formatDate(hovered.started_at)}</div>
            {hovered.complexity !== null && (
              <div className="flex items-center gap-1.5 mt-1 pt-1 border-t border-slate-700/50 text-[9px] font-mono">
                <span className="text-slate-400">{hovered.complexity.toFixed(0)}</span>
                <span
                  className={cn(
                    hovered.delta.startsWith("+") && "text-rose-400",
                    hovered.delta.startsWith("-") && "text-emerald-400",
                    (hovered.delta === "±0" || hovered.delta === "—") && "text-slate-500"
                  )}
                >
                  {hovered.delta}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
