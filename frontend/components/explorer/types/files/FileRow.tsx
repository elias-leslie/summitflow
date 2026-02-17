/**
 * FileRow - Row content renderer for files
 *
 * Renders file/directory name with icon, LOC, size, complexity badge, and modified date.
 */

import { File, Folder } from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { formatBytes, formatNumber, formatTimeAgo } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ColumnValue } from '../../DataList'
import { HealthBadge, type HealthStatus } from '../../HealthBadge'

interface FileRowProps {
  entry: ExplorerEntry
}


// Comment density indicator - shows when >15% (excessive commenting)
function CommentDensityBadge({
  density,
}: {
  density: number | undefined | null
}) {
  if (density === undefined || density === null || density <= 15) return null

  return (
    <span
      className="text-[10px] px-1 py-0.5 rounded bg-purple-500/20 text-purple-400 shrink-0"
      title={`Comment density: ${density.toFixed(1)}% (>15% is excessive)`}
    >
      {density.toFixed(0)}%
    </span>
  )
}

export function FileRow({ entry }: FileRowProps) {
  const isDir = entry.metadata.is_directory
  const loc = isDir
    ? (entry.metadata.lines_of_code ?? 0)
    : (entry.metadata.lines_of_code ?? 0)
  const size = entry.metadata.size_bytes ?? 0
  const bloatLevel = entry.metadata.bloat_level
  const commentDensity = entry.metadata.comment_density as number | undefined
  const healthStatus = (entry.healthStatus ?? 'unknown') as HealthStatus

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

      {/* Health indicator */}
      <HealthBadge status={healthStatus} type="file" size="sm" />

      {/* Name with complexity badge */}
      <ColumnValue
        className={cn(
          'flex-1 truncate flex items-center gap-2',
          isDir && 'font-medium text-slate-200',
          bloatLevel === 'critical' && 'text-red-400',
          bloatLevel === 'warning' && 'text-amber-400',
        )}
      >
        <span className="truncate">{entry.name}</span>
        <CommentDensityBadge density={commentDensity} />
      </ColumnValue>

      {/* LOC */}
      <ColumnValue width="80px" align="right" mono muted={loc === 0}>
        {loc > 0 ? formatNumber(loc) : '-'}
      </ColumnValue>

      {/* Size */}
      <ColumnValue width="80px" align="right" mono muted={size === 0}>
        {size > 0 ? formatBytes(size) : '-'}
      </ColumnValue>

      {/* Modified */}
      <ColumnValue width="100px" align="right" muted>
        {formatTimeAgo(entry.lastScannedAt)}
      </ColumnValue>
    </>
  )
}
