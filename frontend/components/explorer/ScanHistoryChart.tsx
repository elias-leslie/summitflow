"use client";

/**
 * ScanHistoryChart - Visualizes scan history with complexity trend
 *
 * Features:
 * - Area chart for complexity trend (purple gradient)
 * - Scatter dots for scan events (colored by trigger type)
 * - Timeframe selector (7d, 30d, 90d)
 * - Summary footer with delta %
 * - Custom tooltip on dot hover
 */

import { useState, useMemo } from "react";
import {
  ComposedChart,
  Area,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Loader2 } from "lucide-react";
import { useScanHistory } from "@/lib/hooks/useScanHistory";
import { ScanTooltip, TRIGGER_COLORS } from "./ScanTooltip";
import type { ScanHistoryEntry } from "@/lib/api/explorer";

const TIMEFRAME_OPTIONS = [
  { value: 7, label: "7d" },
  { value: 30, label: "30d" },
  { value: 90, label: "90d" },
] as const;

interface ChartDataPoint {
  date: string;
  dateLabel: string;
  complexity: number | null;
  scan?: ScanHistoryEntry;
  dotColor?: string;
}

interface ScanHistoryChartProps {
  projectId: string;
}

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function calculateDeltaPercent(first: number, last: number): number {
  if (first === 0) return 0;
  return ((last - first) / first) * 100;
}

// Custom tooltip component for Recharts
function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ChartDataPoint }>;
}) {
  if (!active || !payload?.length) return null;

  const data = payload[0]?.payload;
  if (!data?.scan) {
    // Just hovering over area, show date and complexity
    return (
      <div className="rounded bg-slate-900 border border-slate-700 px-3 py-2 shadow-lg">
        <div className="text-sm text-slate-200">{data?.dateLabel}</div>
        {data?.complexity !== null && (
          <div className="text-xs text-slate-400">
            Complexity: {data.complexity.toFixed(1)}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="rounded bg-slate-900 border border-slate-700 shadow-lg p-2">
      <ScanTooltip scan={data.scan} />
    </div>
  );
}

export function ScanHistoryChart({ projectId }: ScanHistoryChartProps) {
  const [timeframe, setTimeframe] = useState(30);

  const { data, isLoading, isError, error } = useScanHistory({
    projectId,
    days: timeframe,
  });

  // Transform data for chart
  const chartData = useMemo<ChartDataPoint[]>(() => {
    if (!data?.sparkline_data) return [];

    const { dates, complexity } = data.sparkline_data;
    const scansMap = new Map(data.scans.map((s) => [s.started_at.split("T")[0], s]));

    return dates.map((date, i) => {
      const scan = scansMap.get(date);
      return {
        date,
        dateLabel: formatDateLabel(date),
        complexity: complexity[i],
        scan,
        dotColor: scan ? TRIGGER_COLORS[scan.triggered_by] ?? TRIGGER_COLORS.default : undefined,
      };
    });
  }, [data]);

  // Calculate summary stats
  const summaryStats = useMemo(() => {
    if (!chartData.length) return null;

    const validComplexity = chartData.filter((d) => d.complexity !== null);
    if (!validComplexity.length) return null;

    const first = validComplexity[0]?.complexity ?? 0;
    const last = validComplexity[validComplexity.length - 1]?.complexity ?? 0;
    const deltaPct = calculateDeltaPercent(first, last);

    return {
      first: first.toFixed(1),
      last: last.toFixed(1),
      deltaPct: deltaPct.toFixed(1),
      isImproving: deltaPct < 0,
      totalScans: data?.summary?.total_scans ?? 0,
    };
  }, [chartData, data?.summary]);

  // Loading state
  if (isLoading) {
    return (
      <div className="h-64 flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  // Error state
  if (isError) {
    return (
      <div className="h-64 flex items-center justify-center text-red-400">
        {error?.message || "Failed to load scan history"}
      </div>
    );
  }

  // Empty state
  if (!chartData.length || !data?.summary?.total_scans) {
    return (
      <div className="h-64 flex flex-col items-center justify-center text-slate-500 gap-2">
        <div>No scans yet</div>
        <div className="text-xs text-slate-600">
          Run your first scan to see codebase health trends
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Timeframe selector */}
      <div className="flex justify-end">
        <div className="flex gap-1 bg-slate-800 rounded-lg p-1">
          {TIMEFRAME_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setTimeframe(opt.value)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                timeframe === opt.value
                  ? "bg-purple-600 text-white"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="h-64 transition-opacity duration-300 ease-in-out">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="complexityGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="dateLabel"
              stroke="#64748b"
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              stroke="#64748b"
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={40}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="complexity"
              stroke="#a855f7"
              strokeWidth={2}
              fill="url(#complexityGradient)"
              connectNulls
              animationBegin={0}
              animationDuration={500}
              animationEasing="ease-in-out"
            />
            <Scatter
              dataKey="complexity"
              fill="#a855f7"
              shape="circle"
              animationBegin={200}
              animationDuration={400}
              animationEasing="ease-out"
            >
              {chartData.map((entry, index) => (
                entry.scan && (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.dotColor}
                    stroke={entry.dotColor}
                    strokeWidth={2}
                    r={5}
                  />
                )
              ))}
            </Scatter>
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Summary footer */}
      {summaryStats && (
        <div className="flex items-center justify-between text-xs border-t border-slate-700 pt-3">
          <div className="flex items-center gap-4">
            <span className="text-slate-400">
              {summaryStats.totalScans} scan{summaryStats.totalScans !== 1 ? "s" : ""} in{" "}
              {timeframe} days
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-slate-400">Complexity:</span>
            <span className="text-slate-200">{summaryStats.first}</span>
            <span className="text-slate-500">→</span>
            <span className="text-slate-200">{summaryStats.last}</span>
            <span
              className={`font-medium ${
                summaryStats.isImproving ? "text-green-400" : Number(summaryStats.deltaPct) > 0 ? "text-red-400" : "text-slate-400"
              }`}
            >
              ({summaryStats.isImproving ? "" : "+"}{summaryStats.deltaPct}%)
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default ScanHistoryChart;
