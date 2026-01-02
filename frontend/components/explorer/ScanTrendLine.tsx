/**
 * ScanTrendLine - Minimal sparkline for scan history
 *
 * Architecture: SVG for trend line, HTML/CSS for event markers
 * This avoids SVG aspect ratio issues and gives native hover states.
 */

"use client";

import { useState, useMemo } from "react";
import { useScanHistory } from "@/lib/hooks/useScanHistory";
import { cn } from "@/lib/utils";

interface ScanTrendLineProps {
  projectId: string;
  className?: string;
}

// Trigger colors
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
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function ScanTrendLine({ projectId, className }: ScanTrendLineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const { scans, sparklineData, isLoading, isError } = useScanHistory({
    projectId,
    days: 30,
  });

  // Process scan data
  const chartData = useMemo(() => {
    if (!scans || scans.length === 0) return null;

    const sortedScans = [...scans].sort(
      (a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
    );

    return sortedScans.map((scan, idx) => {
      const currentComplexity = sparklineData?.complexity?.[idx] ?? null;
      const prevComplexity = idx > 0 ? sparklineData?.complexity?.[idx - 1] : null;

      let delta = "—";
      if (currentComplexity !== null && prevComplexity !== null && prevComplexity !== undefined) {
        const diff = currentComplexity - prevComplexity;
        if (diff > 0) delta = `+${diff.toFixed(0)}`;
        else if (diff < 0) delta = diff.toFixed(0);
        else delta = "±0";
      }

      return { ...scan, complexity: currentComplexity, delta };
    });
  }, [scans, sparklineData]);

  const hasComplexityData = useMemo(() => {
    return chartData?.some((d) => d.complexity !== null) ?? false;
  }, [chartData]);

  // Generate SVG path for trend line
  const { linePath, areaPath } = useMemo(() => {
    if (!chartData || chartData.length === 0) {
      return { linePath: "", areaPath: "" };
    }

    const complexityValues = chartData
      .map((d, i) => ({ value: d.complexity, index: i }))
      .filter((d): d is { value: number; index: number } => d.value !== null);

    if (complexityValues.length < 2) {
      return { linePath: "", areaPath: "" };
    }

    const minC = Math.min(...complexityValues.map((d) => d.value)) * 0.95;
    const maxC = Math.max(...complexityValues.map((d) => d.value)) * 1.05;
    const range = maxC - minC || 1;

    // Map to 0-100 coordinate space
    const points = complexityValues.map((d) => ({
      x: (d.index / Math.max(chartData.length - 1, 1)) * 100,
      y: 100 - ((d.value - minC) / range) * 100,
    }));

    // Build bezier path
    let line = `M ${points[0].x} ${points[0].y}`;
    let area = `M ${points[0].x} 100 L ${points[0].x} ${points[0].y}`;

    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const curr = points[i];
      const cpx = (prev.x + curr.x) / 2;
      line += ` C ${cpx} ${prev.y}, ${cpx} ${curr.y}, ${curr.x} ${curr.y}`;
      area += ` C ${cpx} ${prev.y}, ${cpx} ${curr.y}, ${curr.x} ${curr.y}`;
    }

    area += ` L ${points[points.length - 1].x} 100 Z`;

    return { linePath: line, areaPath: area };
  }, [chartData]);

  // Loading state
  if (isLoading) {
    return (
      <div className={cn("h-12 flex items-center justify-center", className)}>
        <div className="h-px w-20 bg-gradient-to-r from-transparent via-slate-600 to-transparent animate-pulse" />
      </div>
    );
  }

  if (isError) return null;

  // Empty state
  if (!chartData || chartData.length === 0) {
    return (
      <div className={cn("h-12 flex items-center justify-center", className)}>
        <span className="text-[10px] font-mono text-slate-600">No scan activity</span>
      </div>
    );
  }

  const hoveredScan = hoveredIndex !== null ? chartData[hoveredIndex] : null;

  return (
    <div className={cn("h-12 relative", className)}>
      {/* SVG Layer - Trend line only (can stretch) */}
      {hasComplexityData && (linePath || areaPath) && (
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
          {linePath && (
            <path
              d={linePath}
              fill="none"
              stroke="#a855f7"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>
      )}

      {/* Baseline for no-data state */}
      {!hasComplexityData && (
        <div
          className="absolute left-0 right-0 h-px bg-slate-700/50"
          style={{ top: "50%" }}
        />
      )}

      {/* HTML Layer - Event markers (perfect circles, proper hover) */}
      <div className="absolute inset-x-0 top-0 h-4 flex items-center">
        {chartData.map((scan, i) => {
          const leftPercent = (i / Math.max(chartData.length - 1, 1)) * 100;
          const color = getTriggerColor(scan.triggered_by);
          const isHovered = hoveredIndex === i;

          return (
            <div
              key={scan.id}
              className="absolute -translate-x-1/2 group/dot"
              style={{ left: `${leftPercent}%` }}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              {/* Glow layer */}
              <div
                className={cn(
                  "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-all duration-200",
                  isHovered ? "w-3 h-3 opacity-40" : "w-2 h-2 opacity-0"
                )}
                style={{ backgroundColor: color, filter: "blur(3px)" }}
              />
              {/* Dot */}
              <div
                className={cn(
                  "relative rounded-full cursor-pointer transition-all duration-150",
                  isHovered ? "w-2 h-2" : "w-1.5 h-1.5"
                )}
                style={{
                  backgroundColor: color,
                  boxShadow: isHovered ? `0 0 8px ${color}` : `0 0 4px ${color}50`,
                }}
              />
            </div>
          );
        })}
      </div>

      {/* Tooltip */}
      {hoveredScan && hoveredIndex !== null && (
        <div
          className="absolute z-50 pointer-events-none"
          style={{
            left: `${(hoveredIndex / Math.max(chartData.length - 1, 1)) * 100}%`,
            top: 0,
            transform: `translateX(${
              hoveredIndex / chartData.length > 0.7
                ? "-100%"
                : hoveredIndex / chartData.length < 0.3
                ? "0%"
                : "-50%"
            }) translateY(-100%)`,
            paddingBottom: "8px",
          }}
        >
          <div
            className="bg-slate-900/95 backdrop-blur-sm border rounded px-2 py-1.5 shadow-xl whitespace-nowrap"
            style={{ borderColor: `${getTriggerColor(hoveredScan.triggered_by)}40` }}
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{
                  backgroundColor: getTriggerColor(hoveredScan.triggered_by),
                  boxShadow: `0 0 4px ${getTriggerColor(hoveredScan.triggered_by)}`,
                }}
              />
              <span className="text-[10px] font-mono text-slate-200">
                {getTriggerLabel(hoveredScan.triggered_by)}
              </span>
            </div>
            <div className="text-[9px] font-mono text-slate-500">
              {formatDate(hoveredScan.started_at)}
            </div>
            {hoveredScan.complexity !== null && (
              <div className="flex items-center gap-1.5 mt-1 pt-1 border-t border-slate-700/50 text-[9px] font-mono">
                <span className="text-slate-400">{hoveredScan.complexity.toFixed(0)}</span>
                <span
                  className={cn(
                    hoveredScan.delta.startsWith("+") && "text-rose-400",
                    hoveredScan.delta.startsWith("-") && "text-emerald-400",
                    (hoveredScan.delta === "±0" || hoveredScan.delta === "—") && "text-slate-500"
                  )}
                >
                  {hoveredScan.delta}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
