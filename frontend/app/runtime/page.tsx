'use client'

import { useQuery } from '@tanstack/react-query'
import { HealthBar } from '@/components/runtime/HealthBar'
import { RuntimeModeBanner } from '@/components/runtime/RuntimeModeBanner'
import { ServiceGrid } from '@/components/runtime/ServiceGrid'
import { ProxmoxStatusCard } from '@/components/runtime/ProxmoxStatusCard'
import { runtimeApi } from '@/lib/api/runtime'

export default function RuntimePage() {
  const { data: health, isLoading: healthLoading, error: healthError } = useQuery({
    queryKey: ['runtime', 'health'],
    queryFn: runtimeApi.getHealth,
    refetchInterval: 10_000,
  })

  const { data: services, isLoading: servicesLoading, error: servicesError } = useQuery({
    queryKey: ['runtime', 'status'],
    queryFn: runtimeApi.getStatus,
    refetchInterval: 10_000,
  })

  const isLoading = healthLoading || servicesLoading
  const error = healthError || servicesError

  return (
    <div className="p-6 space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white font-display">
            Runtime Management
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Native services, Docker infra, Proxmox guests
          </p>
        </div>
        {health && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-500">{health.total} services</span>
            {health.healthy > 0 && (
              <span className="text-emerald-400">{health.healthy} healthy</span>
            )}
            {health.unhealthy > 0 && (
              <span className="text-red-400">{health.unhealthy} unhealthy</span>
            )}
            {health.stopped > 0 && (
              <span className="text-slate-500">{health.stopped} stopped</span>
            )}
          </div>
        )}
      </div>

      {/* Error state */}
      {error && !isLoading && (
        <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">
          Failed to load runtime data. Verify the backend is running.
        </div>
      )}

      {/* Health visualization bar */}
      {services && services.length > 0 && <HealthBar services={services} />}

      {/* Runtime mode — compact banner instead of full card */}
      <RuntimeModeBanner />

      {/* Service grid with list/grid toggle */}
      <ServiceGrid />

      {/* Proxmox — collapsible */}
      <ProxmoxStatusCard />
    </div>
  )
}
