'use client'

import { useQuery } from '@tanstack/react-query'
import { Boxes } from 'lucide-react'
import { motion } from 'motion/react'
import { HealthBar } from '@/components/runtime/HealthBar'
import { RuntimeModeBanner } from '@/components/runtime/RuntimeModeBanner'
import { ServiceGrid } from '@/components/runtime/ServiceGrid'
import { ProxmoxStatusCard } from '@/components/runtime/ProxmoxStatusCard'
import { runtimeApi } from '@/lib/api/runtime'
import { POLL_MONITOR } from '@/lib/polling'

const fadeUp = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0 },
}

export default function RuntimePage() {
  const { isLoading: healthLoading, error: healthError } = useQuery({
    queryKey: ['runtime', 'health'],
    queryFn: runtimeApi.getHealth,
    refetchInterval: POLL_MONITOR,
  })

  const { data: services, isLoading: servicesLoading, error: servicesError } = useQuery({
    queryKey: ['runtime', 'status'],
    queryFn: runtimeApi.getStatus,
    refetchInterval: POLL_MONITOR,
  })

  const isLoading = healthLoading || servicesLoading
  const error = healthError || servicesError

  return (
    <div className="mx-auto max-w-[1500px] space-y-3 px-4 py-3 md:px-5 lg:px-6">
      <motion.section
        {...fadeUp}
        transition={{ duration: 0.3, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="space-y-3"
      >
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex items-center gap-3">
            <Boxes className="h-5 w-5 text-cyan-300" />
            <div>
              <h1 className="display text-xl font-semibold tracking-tight text-slate-50">
                Runtime Management
              </h1>
              <p className="text-sm text-slate-400">
                Service health, native apps, and shared infrastructure
              </p>
            </div>
          </div>

          {error && !isLoading && (
            <div className="rounded-lg border border-rose-500/20 bg-rose-500/8 px-3 py-2 text-sm text-rose-200 xl:max-w-sm">
              Failed to load runtime data. Verify the backend is reachable.
            </div>
          )}
        </div>

        <div className="space-y-2">
          {services && services.length > 0 && <HealthBar services={services} />}
          <RuntimeModeBanner />
        </div>
      </motion.section>

      <ServiceGrid />
      <ProxmoxStatusCard />
    </div>
  )
}
