'use client'

import { useQuery } from '@tanstack/react-query'
import { dockerApi } from '@/lib/api/docker'
import { ServiceGrid } from '@/components/docker/ServiceGrid'
import { MetricsPanel } from '@/components/docker/MetricsPanel'

export default function DockerPage() {
  const { data: health } = useQuery({
    queryKey: ['docker', 'health'],
    queryFn: dockerApi.getHealth,
    refetchInterval: 10_000,
  })

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white font-display">
            Docker Management
          </h1>
          <p className="text-sm text-neutral-400 mt-1">
            Container status, logs, and metrics
          </p>
        </div>
        {health && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-neutral-400">
              {health.total} containers
            </span>
            {health.healthy > 0 && (
              <span className="text-emerald-400">
                {health.healthy} healthy
              </span>
            )}
            {health.unhealthy > 0 && (
              <span className="text-red-400">
                {health.unhealthy} unhealthy
              </span>
            )}
            {health.stopped > 0 && (
              <span className="text-neutral-500">
                {health.stopped} stopped
              </span>
            )}
          </div>
        )}
      </div>

      {/* Service Grid */}
      <ServiceGrid />

      {/* Metrics */}
      <MetricsPanel />
    </div>
  )
}
