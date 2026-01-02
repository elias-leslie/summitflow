"use client";

/**
 * ScanSparkline - Mini sparkline for scan history
 *
 * Compact visualization for use in cards and dashboards.
 * Shows 7-day complexity trend with dots for scan events.
 */

import { useMemo } from "react";
import { LineChart, Line, ResponsiveContainer, Tooltip } from "recharts";
import { useScanHistory } from "@/lib/hooks/useScanHistory";
import { TRIGGER_COLORS } from "./ScanTooltip";

interface ScanSparklineProps {
  projectId: string;
  width?: number;
  height?: number;
  showDots?: boolean;
}

interface SparklineDataPoint {
  date: string;
  complexity: number | null;
  hasScan: boolean;
  dotColor?: string;
}

export function ScanSparkline({
  projectId,
  width = 100,
  height = 32,
  showDots = true,
}: ScanSparklineProps) {
  const { data, isLoading } = useScanHistory({
    projectId,
    days: 7,
  });

  // Transform data for sparkline
  const sparklineData = useMemo<SparklineDataPoint[]>(() => {
    if (!data?.sparkline_data) return [];

    const { dates, complexity } = data.sparkline_data;
    const scansMap = new Map(
      data.scans.map((s) => [s.started_at.split("T")[0], s])
    );

    return dates.map((date, i) => {
      const scan = scansMap.get(date);
      return {
        date,
        complexity: complexity[i],
        hasScan: !!scan,
        dotColor: scan
          ? TRIGGER_COLORS[scan.triggered_by] ?? TRIGGER_COLORS.default
          : undefined,
      };
    });
  }, [data]);

  // Calculate trend indicator
  const trend = useMemo(() => {
    const validPoints = sparklineData.filter((d) => d.complexity !== null);
    if (validPoints.length < 2) return null;

    const first = validPoints[0]?.complexity ?? 0;
    const last = validPoints[validPoints.length - 1]?.complexity ?? 0;
    const deltaPct = first === 0 ? 0 : ((last - first) / first) * 100;

    return {
      improving: deltaPct < 0,
      deltaPct: Math.abs(deltaPct).toFixed(0),
    };
  }, [sparklineData]);

  if (isLoading) {
    return (
      <div
        style={{ width, height }}
        className="bg-slate-800 rounded animate-pulse"
      />
    );
  }

  if (!sparklineData.length) {
    return (
      <div
        style={{ width, height }}
        className="flex items-center justify-center text-xs text-slate-600"
      >
        No data
      </div>
    );
  }

  // Custom dot renderer
  const renderDot = (props: { cx?: number; cy?: number; payload?: SparklineDataPoint }) => {
    const { cx, cy, payload } = props;
    if (!showDots || !payload?.hasScan || cx === undefined || cy === undefined) {
      return <></>;
    }

    return (
      <circle
        cx={cx}
        cy={cy}
        r={3}
        fill={payload.dotColor}
        stroke="#1e293b"
        strokeWidth={1}
      />
    );
  };

  // Simple tooltip for sparkline
  const CustomTooltip = ({
    active,
    payload,
  }: {
    active?: boolean;
    payload?: Array<{ payload: SparklineDataPoint }>;
  }) => {
    if (!active || !payload?.length) return null;
    const data = payload[0]?.payload;
    if (!data) return null;

    return (
      <div className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs shadow-lg">
        <div className="text-slate-200">
          {data.complexity !== null ? data.complexity.toFixed(1) : "—"}
        </div>
      </div>
    );
  };

  const trendDescription = trend
    ? `Complexity ${trend.improving ? "decreased" : "increased"} by ${trend.deltaPct}% over the last 7 days`
    : "No trend data available";

  return (
    <div
      className="flex items-center gap-2"
      role="img"
      aria-label={`7-day complexity sparkline. ${trendDescription}`}
    >
      <div style={{ width, height }} aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={sparklineData}>
            <Tooltip content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey="complexity"
              stroke="#a855f7"
              strokeWidth={1.5}
              dot={renderDot}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {trend && (
        <span
          className={`text-xs font-medium ${
            trend.improving ? "text-green-400" : "text-red-400"
          }`}
          aria-hidden="true"
        >
          {trend.improving ? "↓" : "↑"}
          {trend.deltaPct}%
        </span>
      )}
    </div>
  );
}

export default ScanSparkline;
