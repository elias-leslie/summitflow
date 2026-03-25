'use client'

import { useQuery } from '@tanstack/react-query'
import { Activity, Boxes, ShieldAlert, SquareTerminal } from 'lucide-react'
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
  const { data: health, isLoading: healthLoading, error: healthError } = useQuery({
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

  const statCards = [
    {
      label: 'Healthy',
      value: health?.healthy ?? 0,
      icon: Activity,
      tone: 'text-emerald-300',
      iconBg: 'bg-emerald-500/10',
      iconColor: 'text-emerald-300',
    },
    {
      label: 'Unhealthy',
      value: health?.unhealthy ?? 0,
      icon: ShieldAlert,
      tone: 'text-rose-300',
      iconBg: 'bg-rose-500/10',
      iconColor: 'text-rose-300',
    },
    {
      label: 'Stopped',
      value: health?.stopped ?? 0,
      icon: SquareTerminal,
      tone: 'text-slate-200',
      iconBg: 'bg-slate-700/40',
      iconColor: 'text-slate-300',
    },
    {
      label: 'Total services',
      value: health?.total ?? services?.length ?? 0,
      icon: Boxes,
      tone: 'text-phosphor-300',
      iconBg: 'bg-phosphor-500/10',
      iconColor: 'text-phosphor-300',
    },
  ]

  return (
    <div className="mx-auto max-w-[1500px] space-y-5 px-4 py-5 md:px-5 lg:px-6">
      <motion.section
        {...fadeUp}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="panel-glass px-4 py-4 md:px-5"
      >
        <div className="space-y-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div className="space-y-2.5">
              <div className="eyebrow">Runtime control</div>
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-cyan-500/18 bg-cyan-500/10">
                  <Boxes className="h-5 w-5 text-cyan-300" />
                </div>
                <div>
                  <h1 className="display text-2xl font-semibold tracking-tight text-slate-50 lg:text-3xl">
                    Runtime Management
                  </h1>
                  <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-300">
                    Scan service health fast, then drop into the live service
                    grid without losing space to oversized status cards.
                  </p>
                </div>
              </div>
            </div>

            {error && !isLoading && (
              <div className="rounded-2xl border border-rose-500/20 bg-rose-500/8 px-3.5 py-3 text-sm text-rose-200 xl:max-w-sm">
                Failed to load runtime data. Verify the backend is up and the
                service monitor endpoints are reachable.
              </div>
            )}
          </div>

          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {statCards.map((card) => {
              const Icon = card.icon
              return (
                <div key={card.label} className="rounded-[1.15rem] border border-slate-800/80 bg-slate-950/72 px-3.5 py-3">
                  <div className="flex items-center gap-3">
                    <div className={`rounded-xl p-2 ${card.iconBg}`}>
                      <Icon className={`h-4 w-4 ${card.iconColor}`} />
                    </div>
                    <div className="min-w-0">
                      <div className={`font-mono text-2xl font-bold leading-none tabular-nums ${card.tone}`}>
                        {card.value}
                      </div>
                      <div className="mt-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
                        {card.label}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="space-y-3">
            {services && services.length > 0 && <HealthBar services={services} />}
            <RuntimeModeBanner />
          </div>
        </div>
      </motion.section>

      <ServiceGrid />
      <ProxmoxStatusCard />
    </div>
  )
}
