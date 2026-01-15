/**
 * FileRow - Row content renderer for files
 *
 * Renders file/directory name with icon, LOC, size, complexity badge, and modified date.
 */

import { Folder, File } from "lucide-react";
import { cn } from "@/lib/utils";
import { ColumnValue } from "../../DataList";
import type { ExplorerEntry } from "@/lib/api/explorer";

interface FileRowProps {
  entry: ExplorerEntry;
}

// Helpers
const formatNumber = (n: number | undefined | null) =>
  (n ?? 0).toLocaleString();

const formatBytes = (bytes: number | undefined | null) => {
  const b = bytes ?? 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
};

const formatTimeAgo = (dateStr: string | null) => {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return `${Math.floor(diffDays / 30)}mo ago`;
};

// Health badge component - triage dot indicator for refactor priority
function HealthBadge({ priority }: { priority: string | undefined }) {
  // Only show badge for high or medium priority
  if (!priority || priority === "low" || priority === "none") return null;

  const isHigh = priority === "high";

  return (
    <span
      className={cn(
        "w-2 h-2 rounded-full shrink-0",
        isHigh ? "bg-red-500" : "bg-amber-500",
      )}
      title={
        isHigh
          ? "Critical - needs refactoring"
          : "Warning - consider refactoring"
      }
    />
  );
}

// Comment density indicator - shows when >15% (excessive commenting)
function CommentDensityBadge({
  density,
}: {
  density: number | undefined | null;
}) {
  if (density === undefined || density === null || density <= 15) return null;

  return (
    <span
      className="text-[10px] px-1 py-0.5 rounded bg-purple-500/20 text-purple-400 shrink-0"
      title={`Comment density: ${density.toFixed(1)}% (>15% is excessive)`}
    >
      {density.toFixed(0)}%
    </span>
  );
}

export function FileRow({ entry }: FileRowProps) {
  const isDir = entry.metadata.is_directory;
  const loc = isDir
    ? (entry.metadata.lines_of_code ?? 0)
    : (entry.metadata.lines_of_code ?? 0);
  const size = entry.metadata.size_bytes ?? 0;
  const bloatLevel = entry.metadata.bloat_level;
  const refactorPriority = entry.metadata.refactor_priority as
    | string
    | undefined;
  const commentDensity = entry.metadata.comment_density as number | undefined;

  return (
    <>
      {/* Icon */}
      <span className="flex-shrink-0 text-slate-500">
        {isDir ? (
          <Folder className="w-4 h-4 text-amber-500/70" />
        ) : (
          <File className="w-4 h-4" />
        )}
      </span>

      {/* Name with complexity badge */}
      <ColumnValue
        className={cn(
          "flex-1 truncate flex items-center gap-2",
          isDir && "font-medium text-slate-200",
          bloatLevel === "critical" && "text-red-400",
          bloatLevel === "warning" && "text-amber-400",
        )}
      >
        <span className="truncate">{entry.name}</span>
        <HealthBadge priority={refactorPriority} />
        <CommentDensityBadge density={commentDensity} />
      </ColumnValue>

      {/* LOC */}
      <ColumnValue width="80px" align="right" mono muted={loc === 0}>
        {loc > 0 ? formatNumber(loc) : "-"}
      </ColumnValue>

      {/* Size */}
      <ColumnValue width="80px" align="right" mono muted={size === 0}>
        {size > 0 ? formatBytes(size) : "-"}
      </ColumnValue>

      {/* Modified */}
      <ColumnValue width="100px" align="right" muted>
        {formatTimeAgo(entry.lastScannedAt)}
      </ColumnValue>
    </>
  );
}
