/**
 * TableRow - Row content renderer for database tables
 *
 * Renders table name with icon, row count, column count, and completeness.
 */

import { Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { ColumnValue } from "../../DataList";
import type { ExplorerEntry } from "@/lib/api/explorer";

interface TableRowProps {
  entry: ExplorerEntry;
}

// Helpers
const formatNumber = (n: number | undefined | null) => {
  const num = n ?? 0;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return num.toLocaleString();
};

const formatPercent = (pct: number | undefined | null) => {
  if (pct === undefined || pct === null) return "-";
  return `${Math.round(pct)}%`;
};

export function TableRow({ entry }: TableRowProps) {
  const rowCount = entry.metadata.row_count ?? 0;
  const columnCount = entry.metadata.column_count ?? 0;
  const completeness = entry.metadata.completeness_pct;
  const category = entry.metadata.category;

  return (
    <>
      {/* Icon */}
      <span className="flex-shrink-0 text-slate-500">
        <Database className="w-4 h-4 text-emerald-500/70" />
      </span>

      {/* Name with category badge */}
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <ColumnValue className="truncate font-medium text-slate-200">
          {entry.name}
        </ColumnValue>
        {category && (
          <span className="px-1.5 py-0.5 rounded text-2xs font-medium bg-slate-700/50 text-slate-400">
            {category}
          </span>
        )}
      </div>

      {/* Row count */}
      <ColumnValue width="100px" align="right" mono muted={rowCount === 0}>
        {rowCount > 0 ? formatNumber(rowCount) : "-"}
      </ColumnValue>

      {/* Column count */}
      <ColumnValue width="80px" align="right" mono muted={columnCount === 0}>
        {columnCount > 0 ? columnCount : "-"}
      </ColumnValue>

      {/* Completeness */}
      <ColumnValue
        width="80px"
        align="right"
        mono
        className={cn(
          completeness !== undefined &&
            completeness < 50 &&
            "text-amber-400",
          completeness !== undefined &&
            completeness >= 90 &&
            "text-emerald-400"
        )}
      >
        {formatPercent(completeness)}
      </ColumnValue>
    </>
  );
}
