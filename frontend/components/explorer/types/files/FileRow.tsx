/**
 * FileRow - Row content renderer for files
 *
 * Renders file/directory name with icon, LOC, size, and modified date.
 */

import { Folder, File } from "lucide-react";
import { cn } from "@/lib/utils";
import { ColumnValue } from "../../DataList";
import type { ExplorerEntry } from "@/lib/api/explorer";

interface FileRowProps {
  entry: ExplorerEntry;
}

// Helpers
const formatNumber = (n: number | undefined | null) => (n ?? 0).toLocaleString();

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

export function FileRow({ entry }: FileRowProps) {
  const isDir = entry.metadata.is_directory;
  const loc = isDir
    ? entry.metadata.lines_of_code ?? 0
    : entry.metadata.lines_of_code ?? 0;
  const size = entry.metadata.size_bytes ?? 0;
  const bloatLevel = entry.metadata.bloat_level;

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

      {/* Name */}
      <ColumnValue
        className={cn(
          "flex-1 truncate",
          isDir && "font-medium text-slate-200",
          bloatLevel === "critical" && "text-red-400",
          bloatLevel === "warning" && "text-amber-400"
        )}
      >
        {entry.name}
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
