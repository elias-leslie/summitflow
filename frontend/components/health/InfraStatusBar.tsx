'use client'

import clsx from 'clsx'
import { useSystemStats } from '@/hooks/useSystemStats'
import { API_PATHS, buildApiUrl } from '@/lib/api-config'
import { fetchWithErrorHandling } from '@/lib/api/utils'
import { POLL_STANDARD } from '@/lib/polling'
import { formatUptime } from '@/components/runtime/health-utils'
import { useQuery } from '@tanstack/react-query'

interface ComponentHealth {
  status: string
  message: string | null
  response_time_ms: number | null
}

interface DetailedHealth {
  status: string
  uptime_seconds: number
  database: ComponentHealth
  cache: ComponentHealth
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'healthy' || status === 'ok'
      ? 'bg-emerald-500'
      : status === 'degraded' || status === 'warning'
        ? 'bg-amber-500'
        : status === 'critical' || status === 'unhealthy'
          ? 'bg-rose-500'
          : 'bg-slate-500'
  return <span className={clsx('w-1.5 h-1.5 rounded-full', color)} />
}


function getOverallStatus(
  systemStatus: string | undefined,
  detailedStatus: string | undefined,
): { label: string; color: string } {
  if (!systemStatus && !detailedStatus) {
    return { label: 'Loading', color: 'bg-slate-500' }
  }
  const statuses = [systemStatus, detailedStatus].filter(Boolean)
  if (statuses.some((s) => s === 'unhealthy' || s === 'critical')) {
    return { label: 'Unhealthy', color: 'bg-rose-500' }
  }
  if (statuses.some((s) => s === 'degraded' || s === 'warning')) {
    return { label: 'Degraded', color: 'bg-amber-500' }
  }
  return { label: 'Healthy', color: 'bg-emerald-500' }
}

export function InfraStatusBar() {
  const { data: systemStats } = useSystemStats()

  const { data: detailed, isError: isDetailedError } = useQuery({
    queryKey: ['health-detailed'],
    queryFn: () =>
      fetchWithErrorHandling<DetailedHealth>(
        buildApiUrl(API_PATHS.HEALTH_DETAILED),
        { errorMessage: 'Failed to fetch detailed health' },
      ),
    refetchInterval: POLL_STANDARD * 2,
    staleTime: POLL_STANDARD * 2 - 5000,
  })

  const overall = getOverallStatus(
    systemStats?.cpu.status,
    detailed?.status,
  )

  return (
    <div className="card rounded-xl px-4 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-5">
          {/* DB Latency */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">DB:</span>
            <span className="text-xs text-slate-300 tabular-nums">
              {isDetailedError
                ? '✗'
                : detailed?.database.response_time_ms != null
                  ? `${detailed.database.response_time_ms.toFixed(1)}ms`
                  : '—'}
            </span>
            {isDetailedError ? (
              <StatusDot status="critical" />
            ) : (
              detailed?.database && <StatusDot status={detailed.database.status} />
            )}
          </div>

          {/* Redis Latency */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">Redis:</span>
            <span className="text-xs text-slate-300 tabular-nums">
              {isDetailedError
                ? '✗'
                : detailed?.cache.response_time_ms != null
                  ? `${detailed.cache.response_time_ms.toFixed(1)}ms`
                  : '—'}
            </span>
            {isDetailedError ? (
              <StatusDot status="critical" />
            ) : (
              detailed?.cache && <StatusDot status={detailed.cache.status} />
            )}
          </div>

          {/* CPU */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">CPU:</span>
            <span className="text-xs text-slate-300 tabular-nums">
              {systemStats?.cpu.percent_used != null
                ? `${Math.round(systemStats.cpu.percent_used)}%`
                : '—'}
            </span>
            {systemStats?.cpu && <StatusDot status={systemStats.cpu.status} />}
          </div>

          {/* Memory */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">Mem:</span>
            <span className="text-xs text-slate-300 tabular-nums">
              {systemStats?.memory.percent_used != null
                ? `${Math.round(systemStats.memory.percent_used)}%`
                : '—'}
            </span>
            {systemStats?.memory && <StatusDot status={systemStats.memory.status} />}
          </div>

          {/* Disk */}
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">Disk:</span>
            <span className="text-xs text-slate-300 tabular-nums">
              {systemStats?.disk.percent_used != null
                ? `${Math.round(systemStats.disk.percent_used)}%`
                : '—'}
            </span>
            {systemStats?.disk && <StatusDot status={systemStats.disk.status} />}
          </div>

          {/* Uptime */}
          {detailed?.uptime_seconds != null && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-500">Up:</span>
              <span className="text-xs text-slate-300 tabular-nums">
                {formatUptime(detailed.uptime_seconds)}
              </span>
            </div>
          )}
        </div>

        {/* Overall status */}
        <div className="flex items-center gap-2">
          <span className={clsx('w-2 h-2 rounded-full', overall.color)} />
          <span className="text-xs text-slate-400">{overall.label}</span>
        </div>
      </div>
    </div>
  )
}
