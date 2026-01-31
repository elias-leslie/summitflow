/**
 * EndpointRow - Row content renderer for API endpoints
 *
 * Renders endpoint path with method badge, status, and response time.
 */

import { FileText, Globe } from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'
import { ColumnValue } from '../../DataList'
import { HealthBadge, type HealthStatus } from '../../HealthBadge'

interface EndpointRowProps {
  entry: ExplorerEntry
}

// Method colors
const methodColors: Record<string, string> = {
  GET: 'bg-emerald-500/20 text-emerald-400',
  POST: 'bg-blue-500/20 text-blue-400',
  PUT: 'bg-amber-500/20 text-amber-400',
  PATCH: 'bg-yellow-500/20 text-yellow-400',
  DELETE: 'bg-red-500/20 text-red-400',
}

// Helpers
const formatDuration = (ms: number | undefined | null) => {
  if (ms === undefined || ms === null) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function EndpointRow({ entry }: EndpointRowProps) {
  const method = entry.metadata.method ?? 'GET'
  const httpStatus = entry.metadata.http_status
  const responseTime = entry.metadata.response_time_ms
  const endpointType = entry.metadata.endpoint_type
  const consoleErrors = entry.metadata.console_errors ?? 0
  const healthStatus = (entry.healthStatus ?? 'unknown') as HealthStatus

  const isPage = endpointType === 'page'
  const isHealthy =
    httpStatus !== undefined && httpStatus >= 200 && httpStatus < 400
  const isError = httpStatus !== undefined && httpStatus >= 400

  return (
    <>
      {/* Icon */}
      <span className="flex-shrink-0 text-slate-500">
        {isPage ? (
          <FileText className="w-4 h-4 text-blue-500/70" />
        ) : (
          <Globe className="w-4 h-4 text-cyan-500/70" />
        )}
      </span>

      {/* Health indicator */}
      <HealthBadge status={healthStatus} type="endpoint" size="sm" />

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

      {/* Method badge */}
      <span
        className={cn(
          'w-[70px] text-center px-2 py-0.5 rounded text-2xs font-bold uppercase',
          methodColors[method] || 'bg-slate-700/50 text-slate-400',
        )}
      >
        {isPage ? 'PAGE' : method}
      </span>

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
