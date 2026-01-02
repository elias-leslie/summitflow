"use client";

/**
 * ScanHistoryTable - Table of recent scans
 *
 * Shows last 10 scans with:
 * - Timestamp
 * - Trigger type (colored)
 * - Duration
 * - Status
 * - Complexity delta
 */

import { useScanHistory } from "@/lib/hooks/useScanHistory";
import { TRIGGER_COLORS, TRIGGER_LABELS } from "./ScanTooltip";
import { Loader2, Clock, CheckCircle, XCircle, PlayCircle } from "lucide-react";
import type { ScanHistoryEntry } from "@/lib/api/explorer";

interface ScanHistoryTableProps {
  projectId: string;
  limit?: number;
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function formatDistanceToNow(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return `${Math.floor(diffDay / 7)}w ago`;
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

function StatusIcon({ status }: { status: ScanHistoryEntry["status"] }) {
  switch (status) {
    case "completed":
      return <CheckCircle className="h-4 w-4 text-green-400" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-red-400" />;
    case "running":
      return <PlayCircle className="h-4 w-4 text-yellow-400 animate-pulse" />;
    default:
      return <Clock className="h-4 w-4 text-slate-400" />;
  }
}

function TriggerBadge({ triggeredBy }: { triggeredBy: string }) {
  const color = TRIGGER_COLORS[triggeredBy] ?? TRIGGER_COLORS.default;
  const label = TRIGGER_LABELS[triggeredBy] ?? TRIGGER_LABELS.default;

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
      style={{
        backgroundColor: `${color}20`,
        color: color,
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      {label}
    </span>
  );
}

function formatDelta(metrics_delta: Record<string, unknown>): string {
  const complexity = metrics_delta?.complexity;
  if (typeof complexity !== "number") return "—";
  const sign = complexity > 0 ? "+" : "";
  return `${sign}${complexity.toFixed(1)}`;
}

function getDeltaColor(metrics_delta: Record<string, unknown>): string {
  const complexity = metrics_delta?.complexity;
  if (typeof complexity !== "number") return "text-slate-500";
  if (complexity > 0) return "text-red-400";
  if (complexity < 0) return "text-green-400";
  return "text-slate-500";
}

export function ScanHistoryTable({
  projectId,
  limit = 10,
}: ScanHistoryTableProps) {
  const { scans, isLoading, isError, error } = useScanHistory({
    projectId,
    days: 30,
  });

  // Limit to most recent scans
  const recentScans = scans.slice(0, limit);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="text-center py-8 text-red-400 text-sm">
        {error?.message || "Failed to load scan history"}
      </div>
    );
  }

  if (!recentScans.length) {
    return (
      <div className="text-center py-8 text-slate-500 text-sm">
        No recent scans
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700">
            <th className="text-left py-3 px-4 text-slate-400 font-medium">
              Time
            </th>
            <th className="text-left py-3 px-4 text-slate-400 font-medium">
              Trigger
            </th>
            <th className="text-left py-3 px-4 text-slate-400 font-medium">
              Duration
            </th>
            <th className="text-left py-3 px-4 text-slate-400 font-medium">
              Status
            </th>
            <th className="text-right py-3 px-4 text-slate-400 font-medium">
              Δ Complexity
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {recentScans.map((scan) => (
            <tr
              key={scan.id}
              className="hover:bg-slate-800/50 transition-colors"
            >
              <td className="py-3 px-4">
                <div className="text-slate-200">{formatTime(scan.started_at)}</div>
                <div className="text-xs text-slate-500">
                  {formatDistanceToNow(new Date(scan.started_at))}
                </div>
              </td>
              <td className="py-3 px-4">
                <TriggerBadge triggeredBy={scan.triggered_by} />
              </td>
              <td className="py-3 px-4 text-slate-300">
                {formatDuration(scan.duration_ms)}
              </td>
              <td className="py-3 px-4">
                <div className="flex items-center gap-2">
                  <StatusIcon status={scan.status} />
                  <span className="text-slate-300 capitalize">
                    {scan.status}
                  </span>
                </div>
              </td>
              <td
                className={`py-3 px-4 text-right font-medium ${getDeltaColor(scan.metrics_delta)}`}
              >
                {formatDelta(scan.metrics_delta)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ScanHistoryTable;
