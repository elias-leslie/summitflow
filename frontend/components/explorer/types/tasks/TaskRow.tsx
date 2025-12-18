/**
 * TaskRow - Row content renderer for Celery tasks
 *
 * Renders task name with icon, schedule, success rate, and avg duration.
 */

import { Zap, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { ColumnValue } from "../../DataList";
import type { ExplorerEntry } from "@/lib/api/explorer";

interface TaskRowProps {
  entry: ExplorerEntry;
}

// Helpers
const formatDuration = (ms: number | undefined | null) => {
  if (ms === undefined || ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
};

const formatPercent = (pct: number | undefined | null) => {
  if (pct === undefined || pct === null) return "-";
  return `${Math.round(pct)}%`;
};

export function TaskRow({ entry }: TaskRowProps) {
  const schedule = entry.metadata.schedule_human;
  const successRate = entry.metadata.success_rate_pct;
  const avgDuration = entry.metadata.avg_duration_ms;
  const isScheduled = !!entry.metadata.schedule_type;

  return (
    <>
      {/* Icon */}
      <span className="flex-shrink-0 text-slate-500">
        <Zap className="w-4 h-4 text-yellow-500/70" />
      </span>

      {/* Name with schedule indicator */}
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <ColumnValue className="truncate font-medium text-slate-200">
          {entry.name}
        </ColumnValue>
        {isScheduled && (
          <Clock className="w-3 h-3 text-slate-500 flex-shrink-0" />
        )}
      </div>

      {/* Schedule */}
      <ColumnValue width="120px" muted={!schedule} className="text-xs">
        {schedule || "Manual"}
      </ColumnValue>

      {/* Success rate */}
      <ColumnValue
        width="80px"
        align="right"
        mono
        className={cn(
          successRate !== undefined &&
            successRate < 90 &&
            "text-amber-400",
          successRate !== undefined &&
            successRate < 50 &&
            "text-red-400",
          successRate !== undefined &&
            successRate >= 99 &&
            "text-emerald-400"
        )}
      >
        {formatPercent(successRate)}
      </ColumnValue>

      {/* Average duration */}
      <ColumnValue width="80px" align="right" mono muted={!avgDuration}>
        {formatDuration(avgDuration)}
      </ColumnValue>
    </>
  );
}
