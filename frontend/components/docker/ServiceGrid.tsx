'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { type RuntimeServiceStatus, runtimeApi } from '@/lib/api/runtime'
import { ServiceCard } from './ServiceCard'

export function ServiceGrid() {
  const {
    data: containers,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['runtime', 'status'],
    queryFn: runtimeApi.getStatus,
    refetchInterval: 10_000,
  })
  const { data: metrics, isLoading: isMetricsLoading } = useQuery({
    queryKey: ['runtime', 'metrics'],
    queryFn: runtimeApi.getMetrics,
    refetchInterval: 15_000,
  })

  const metricsByService = useMemo(
    () => new Map((metrics ?? []).map((metric) => [metric.service, metric])),
    [metrics],
  )

  const sections = useMemo(
    () =>
      [
        {
          id: 'native-apps',
          title: 'Native App Services',
          description: 'Services running under systemd --user.',
          items:
            containers?.filter(
              (service) =>
                service.manager === 'systemd' && service.category === 'app',
            ) ?? [],
        },
        {
          id: 'native-workers',
          title: 'Native Workers',
          description: 'Background workers running under systemd --user.',
          items:
            containers?.filter(
              (service) =>
                service.manager === 'systemd' && service.category === 'worker',
            ) ?? [],
        },
        {
          id: 'docker-infra',
          title: 'Docker Infra',
          description: 'Shared infrastructure that stays containerized.',
          items:
            containers?.filter((service) => service.manager === 'docker') ?? [],
        },
      ].filter(
        (section): section is {
          id: string
          title: string
          description: string
          items: RuntimeServiceStatus[]
        } => section.items.length > 0,
      ),
    [containers],
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
    <div className="space-y-6">
      {sections.map((section) => (
        <section key={section.id} className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
              {section.title}
            </h2>
            <p className="mt-1 text-sm text-slate-500">{section.description}</p>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {section.items.map((service) => (
              <ServiceCard
                key={service.name}
                container={service}
                metric={metricsByService.get(service.service)}
                metricsLoading={isMetricsLoading}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
