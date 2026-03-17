'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { dockerApi } from '@/lib/api/docker'
import { ServiceCard } from './ServiceCard'

export function ServiceGrid() {
  const {
    data: containers,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['docker', 'status'],
    queryFn: dockerApi.getStatus,
    refetchInterval: 10_000,
  })
  const { data: metrics, isLoading: isMetricsLoading } = useQuery({
    queryKey: ['docker', 'metrics'],
    queryFn: dockerApi.getMetrics,
    refetchInterval: 15_000,
  })

  const metricsByService = useMemo(
    () => new Map((metrics ?? []).map((metric) => [metric.service, metric])),
    [metrics],
  )

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-32 rounded-lg bg-neutral-800/50 animate-pulse"
          />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-950/20 p-8 text-center">
        <p className="text-red-300">Runtime status is unavailable.</p>
        <p className="mt-1 text-sm text-red-200/80">
          {error instanceof Error ? error.message : 'Unknown runtime API error'}
        </p>
      </div>
    )
  }

  if (!containers?.length) {
    return (
      <div className="rounded-lg border border-neutral-700 bg-neutral-800/30 p-8 text-center">
        <p className="text-neutral-400">No managed runtime services found.</p>
        <p className="text-sm text-neutral-500 mt-1">
          Start or rebuild services with:{' '}
          <code className="text-amber-400">
            ~/summitflow/scripts/rebuild.sh
          </code>
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {containers.map((c) => (
        <ServiceCard
          key={c.name}
          container={c}
          metric={metricsByService.get(c.service)}
          metricsLoading={isMetricsLoading}
        />
      ))}
    </div>
  )
}
