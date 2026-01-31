/**
 * PageRow - Row content renderer for frontend pages
 *
 * Renders page route with params, status, and response time.
 */

import { FileText } from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'
import { ColumnValue } from '../../DataList'
import { HealthBadge, type HealthStatus } from '../../HealthBadge'

interface PageRowProps {
  entry: ExplorerEntry
}

// Helpers
const formatDuration = (ms: number | undefined | null) => {
  if (ms === undefined || ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function PageRow({ entry }: PageRowProps) {
  const httpStatus = entry.metadata.http_status
  const responseTime = entry.metadata.response_time_ms
  const routeParams = entry.metadata.route_params ?? []
  const consoleErrors = entry.metadata.console_errors ?? 0
  const healthStatus = (entry.healthStatus ?? 'unknown') as HealthStatus

  const isHealthy =
    httpStatus !== undefined && httpStatus >= 200 && httpStatus < 400
  const isError = httpStatus !== undefined && httpStatus >= 400

  return (
    <>
      {/* Icon */}
      <span className="flex-shrink-0 text-slate-500">
        <FileText className="w-4 h-4 text-purple-500/70" />
      </span>

      {/* Health indicator */}
      <HealthBadge status={healthStatus} type="page" size="sm" />

      {/* Path with error indicator */}
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <ColumnValue className="truncate font-medium text-slate-200">
          {entry.path}
        </ColumnValue>
        {consoleErrors > 0 && (
          <span className="px-1.5 py-0.5 rounded text-2xs font-medium bg-red-500/20 text-red-400">
            {consoleErrors} error{consoleErrors > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Route params */}
      <ColumnValue width="100px" className="text-slate-400 text-xs">
        {routeParams.length > 0
          ? routeParams.map((p) => `:${p}`).join(', ')
          : '-'}
      </ColumnValue>

      {/* Status code */}
      <ColumnValue
        width="70px"
        align="center"
        mono
        className={cn(
          isHealthy && 'text-emerald-400',
          isError && 'text-red-400',
          !httpStatus && 'text-slate-500',
        )}
      >
        {httpStatus ?? '-'}
      </ColumnValue>

      {/* Response time */}
      <ColumnValue
        width="80px"
        align="right"
        mono
        className={cn(
          responseTime !== undefined && responseTime > 1000 && 'text-amber-400',
          responseTime !== undefined && responseTime > 3000 && 'text-red-400',
        )}
        muted={!responseTime}
      >
        {formatDuration(responseTime)}
      </ColumnValue>
    </>
  )
}
