'use client'

import { useQuery } from '@tanstack/react-query'
import { Boxes } from 'lucide-react'
import { motion } from 'motion/react'
import { SystemHealthWidget } from '@/components/dashboard/SystemHealthWidget'
import { HealthBar } from '@/components/runtime/HealthBar'
import { MaintenanceStatusCard } from '@/components/runtime/MaintenanceStatusCard'
import { ProxmoxStatusCard } from '@/components/runtime/ProxmoxStatusCard'
import { RuntimeModeBanner } from '@/components/runtime/RuntimeModeBanner'
import { ServiceGrid } from '@/components/runtime/ServiceGrid'
import { runtimeApi } from '@/lib/api/runtime'
import { POLL_MONITOR } from '@/lib/polling'

export default function RuntimePage() {
  const {
    data: health,
    isLoading: healthLoading,
    error: healthError,
  } = useQuery({
    queryKey: ['runtime', 'health'],
    queryFn: runtimeApi.getHealth,
    refetchInterval: POLL_MONITOR,
  })

  const {
    data: services,
    isLoading: servicesLoading,
    error: servicesError,
  } = useQuery({
    queryKey: ['runtime', 'status'],
    queryFn: runtimeApi.getStatus,
    refetchInterval: POLL_MONITOR,
  })

  const isLoading = healthLoading || servicesLoading
  const error = healthError || servicesError

  return (
    <div className="p-6 space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="flex items-center justify-between hero-glow"
      >
        <div className="flex items-center gap-3 relative z-10">
          <div className="p-1.5 rounded-md bg-cyan-500/10 border border-cyan-500/20">
            <Boxes className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-100 display tracking-tight leading-none">
              Runtime Management
            </h1>
            <p className="text-sm text-slate-500 mt-0.5">
              Native services, Docker infra, Proxmox guests
            </p>
          </div>
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
      </motion.div>

      {/* Error state */}
      {error && !isLoading && (
        <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">
          Failed to load runtime data. Verify the backend is running.
        </div>
      )}

      {/* System resources */}
      <SystemHealthWidget />

      {/* Health visualization bar */}
      {services && services.length > 0 && <HealthBar services={services} />}

      {/* Runtime mode — compact banner instead of full card */}
      <RuntimeModeBanner />

      {/* Maintenance — compact row */}
      <MaintenanceStatusCard />

      {/* Service grid with list/grid toggle */}
      <ServiceGrid />

      {/* Proxmox — collapsible */}
      <ProxmoxStatusCard />
    </div>
  )
}
