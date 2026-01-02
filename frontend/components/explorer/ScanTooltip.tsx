"use client";

/**
 * ScanTooltip - Tooltip content for scan history chart dots
 *
 * Shows:
 * - Date and time
 * - Trigger type with color indicator
 * - Session info (if available)
 * - Duration
 * - Metrics with deltas vs previous scan
 */

import { type ScanHistoryEntry } from "@/lib/api/explorer";

// Trigger type colors - used for chart dots and tooltip indicators
export const TRIGGER_COLORS: Record<string, string> = {
  refactor_it: "#a855f7", // purple-500
  og_refactor_it: "#a855f7", // purple-500
  daily_qa_scan: "#22c55e", // green-500
  celery_beat: "#22c55e", // green-500
  manual: "#3b82f6", // blue-500
  audit_it: "#f97316", // orange-500
  default: "#94a3b8", // slate-400
};

// Human-readable labels for trigger types
export const TRIGGER_LABELS: Record<string, string> = {
  refactor_it: "Refactor Session",
  og_refactor_it: "Refactor Session",
  daily_qa_scan: "Daily QA Scan",
  celery_beat: "Scheduled Scan",
  manual: "Manual Scan",
  audit_it: "Audit",
  default: "Scan",
};

function getTriggerColor(triggeredBy: string): string {
  return TRIGGER_COLORS[triggeredBy] ?? TRIGGER_COLORS.default;
}

function getTriggerLabel(triggeredBy: string): string {
  return TRIGGER_LABELS[triggeredBy] ?? TRIGGER_LABELS.default;
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function formatDateTime(dateStr: string): { date: string; time: string } {
  const d = new Date(dateStr);
  return {
    date: d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    }),
    time: d.toLocaleTimeString("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }),
  };
}

function formatDelta(delta: number | undefined): string {
  if (delta === undefined || delta === 0) return "";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta}`;
}

interface MetricRowProps {
  label: string;
  value: number | string | undefined;
  delta?: number;
}

function MetricRow({ label, value, delta }: MetricRowProps) {
  const deltaStr = formatDelta(delta);
  const deltaColor =
    delta === undefined
      ? ""
      : delta > 0
        ? "text-red-400"
        : delta < 0
          ? "text-green-400"
          : "text-slate-500";

  return (
    <div className="flex justify-between gap-4 text-xs">
      <span className="text-slate-400">{label}</span>
      <span className="text-slate-200">
        {value ?? "—"}
        {deltaStr && <span className={`ml-1 ${deltaColor}`}>({deltaStr})</span>}
      </span>
    </div>
  );
}

interface ScanTooltipProps {
  scan: ScanHistoryEntry;
}

export function ScanTooltip({ scan }: ScanTooltipProps) {
  const { date, time } = formatDateTime(scan.started_at);
  const triggerColor = getTriggerColor(scan.triggered_by);
  const triggerLabel = getTriggerLabel(scan.triggered_by);

  // Extract metrics and deltas
  const metrics = scan.metrics as Record<string, number> | undefined;
  const deltas = scan.metrics_delta as Record<string, number> | undefined;

  return (
    <div className="min-w-48 space-y-2 p-1">
      {/* Header: Date and time */}
      <div className="flex items-center justify-between border-b border-slate-700 pb-2">
        <span className="text-sm font-medium text-slate-100">{date}</span>
        <span className="text-xs text-slate-400">{time}</span>
      </div>

      {/* Trigger indicator */}
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: triggerColor }}
        />
        <span className="text-xs text-slate-200">{triggerLabel}</span>
      </div>

      {/* Session info */}
      {scan.triggered_by_session && (
        <div className="text-xs text-slate-500 truncate max-w-48">
          Session: {scan.triggered_by_session.slice(0, 8)}...
        </div>
      )}

      {/* Duration and status */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">Duration</span>
        <span className="text-slate-200">{formatDuration(scan.duration_ms)}</span>
      </div>

      {/* Status */}
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">Status</span>
        <span
          className={
            scan.status === "completed"
              ? "text-green-400"
              : scan.status === "failed"
                ? "text-red-400"
                : scan.status === "running"
                  ? "text-yellow-400"
                  : "text-slate-400"
          }
        >
          {scan.status}
        </span>
      </div>

      {/* Metrics section */}
      {metrics && Object.keys(metrics).length > 0 && (
        <div className="border-t border-slate-700 pt-2 space-y-1">
          <div className="text-xs text-slate-400 mb-1">Metrics</div>
          {metrics.complexity !== undefined && (
            <MetricRow
              label="Complexity"
              value={typeof metrics.complexity === "number" ? metrics.complexity.toFixed(1) : metrics.complexity}
              delta={deltas?.complexity}
            />
          )}
          {metrics.high_priority !== undefined && (
            <MetricRow
              label="High Priority"
              value={metrics.high_priority}
              delta={deltas?.high_priority}
            />
          )}
          {metrics.targets !== undefined && (
            <MetricRow
              label="Targets"
              value={metrics.targets}
              delta={deltas?.targets}
            />
          )}
        </div>
      )}

      {/* Entries info */}
      <div className="border-t border-slate-700 pt-2">
        <MetricRow label="Entries Found" value={scan.entries_found} />
        <MetricRow label="Entries Saved" value={scan.entries_saved} />
      </div>
    </div>
  );
}

export default ScanTooltip;
