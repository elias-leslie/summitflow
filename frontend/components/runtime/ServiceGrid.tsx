'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Boxes, DatabaseZap, LayoutGrid, List, Radar, TriangleAlert } from 'lucide-react'
import { motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { type RuntimeServiceStatus, runtimeApi } from '@/lib/api/runtime'
import { POLL_MONITOR, POLL_STANDARD } from '@/lib/polling'
import { resolveHealthTone } from './health-utils'
import { ServiceCard } from './ServiceCard'
import { ServiceListView } from './ServiceListView'

type ViewMode = 'grid' | 'list'

const STORAGE_KEY = 'runtime-view-mode'

export function ServiceGrid() {
  const [view, setViewRaw] = useState<ViewMode>('grid')

  // Hydrate from localStorage after mount
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'list') setViewRaw('list')
  }, [])

  const setView = useCallback((mode: ViewMode) => {
    setViewRaw(mode)
    localStorage.setItem(STORAGE_KEY, mode)
  }, [])

  const {
    data: containers,
    error,
    isLoading,
  } = useQuery({
    queryKey: ['runtime', 'status'],
    queryFn: runtimeApi.getStatus,
    refetchInterval: POLL_MONITOR,
  })
  const { data: metrics, isLoading: isMetricsLoading } = useQuery({
    queryKey: ['runtime', 'metrics'],
    queryFn: runtimeApi.getMetrics,
    refetchInterval: POLL_STANDARD,
  })

  const metricsByService = useMemo(
    () => new Map((metrics ?? []).map((m) => [m.service, m])),
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
              (s) => s.manager === 'systemd' && s.category === 'app',
            ) ?? [],
        },
        {
          id: 'native-workers',
          title: 'Native Workers',
          description: 'Background workers running under systemd --user.',
          items:
            containers?.filter(
              (s) => s.manager === 'systemd' && s.category === 'worker',
            ) ?? [],
        },
        {
          id: 'docker-infra',
          title: 'Docker Infra',
          description: 'Shared infrastructure that stays containerized.',
          items:
            containers?.filter((s) => s.manager === 'docker') ?? [],
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

  const serviceCount = containers?.length ?? 0
  const nativeCount =
    containers?.filter((service) => service.manager === 'systemd').length ?? 0
  const infraCount =
    containers?.filter((service) => service.manager === 'docker').length ?? 0
  const issueCount =
    containers?.filter((service) => {
      const tone = resolveHealthTone(service.state, service.health)
      return tone === 'warning' || tone === 'unhealthy'
    }).length ?? 0
  const runningCount =
    containers?.filter((service) => service.state === 'running').length ?? 0

  const overviewCards = [
    {
      label: 'Managed services',
      value: serviceCount,
      detail: `${sections.length} active lanes`,
      icon: Boxes,
      tone: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200',
    },
    {
      label: 'Native services',
      value: nativeCount,
      detail: 'systemd --user apps and workers',
      icon: Radar,
      tone: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200',
    },
    {
      label: 'Shared infra',
      value: infraCount,
      detail: 'docker-backed dependencies',
      icon: DatabaseZap,
      tone: 'border-amber-500/20 bg-amber-500/10 text-amber-200',
    },
    {
      label: 'Attention needed',
      value: issueCount,
      detail: `${runningCount} running right now`,
      icon: TriangleAlert,
      tone:
        issueCount > 0
          ? 'border-rose-500/20 bg-rose-500/10 text-rose-200'
          : 'border-slate-700/70 bg-slate-950/70 text-slate-200',
    },
  ]

  const sectionTheme: Record<
    string,
    { icon: typeof Boxes; tone: string; badge: string }
  > = {
    'native-apps': {
      icon: Radar,
      tone: 'border-cyan-500/18 bg-cyan-500/10 text-cyan-200',
      badge: 'border-cyan-500/18 bg-cyan-500/10 text-cyan-300',
    },
    'native-workers': {
      icon: Boxes,
      tone: 'border-emerald-500/18 bg-emerald-500/10 text-emerald-200',
      badge: 'border-emerald-500/18 bg-emerald-500/10 text-emerald-300',
    },
    'docker-infra': {
      icon: DatabaseZap,
      tone: 'border-amber-500/18 bg-amber-500/10 text-amber-200',
      badge: 'border-amber-500/18 bg-amber-500/10 text-amber-300',
    },
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="card-elevated h-40 animate-pulse" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="h-64 rounded-[1.75rem] bg-slate-800/40 animate-pulse"
            />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="card-elevated border-rose-500/30 bg-rose-950/20 p-8 text-center">
        <p className="text-base font-medium text-rose-200">
          Runtime status is unavailable.
        </p>
        <p className="mt-2 text-sm leading-relaxed text-rose-200/80">
          {error instanceof Error ? error.message : 'Unknown runtime API error'}
        </p>
      </div>
    )
  }

  if (!containers?.length) {
    return (
      <div className="card-elevated p-8 text-center">
        <p className="text-base font-medium text-slate-200">
          No managed runtime services found.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          Start or rebuild services with:{' '}
          <code className="text-amber-400">
            rebuild.sh summitflow
          </code>
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="card-elevated px-5 py-5">
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
          <div className="space-y-4">
            <div>
              <div className="eyebrow">Services</div>
              <h2 className="display mt-2 text-3xl font-semibold text-slate-50">
                Control deck
              </h2>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300">
                Scan the runtime fleet at a glance, then switch to the denser
                list view when you need action-by-action operational detail.
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {overviewCards.map((card) => {
                const Icon = card.icon
                return (
                  <div
                    key={card.label}
                    className={clsx('rounded-[1.35rem] border px-4 py-4', card.tone)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="rounded-2xl border border-white/10 bg-slate-950/45 p-2.5">
                        <Icon className="h-4 w-4 text-current" />
                      </div>
                      <span className="font-mono text-3xl tabular-nums text-slate-50">
                        {card.value}
                      </span>
                    </div>
                    <div className="mt-4 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      {card.label}
                    </div>
                    <div className="mt-1 text-xs text-slate-400">
                      {card.detail}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="space-y-3 xl:w-[260px]">
            <div className="flex items-center gap-1 rounded-full border border-slate-700/50 bg-slate-950/70 p-1">
              <button
                onClick={() => setView('grid')}
                className={clsx(
                  'flex flex-1 items-center justify-center gap-2 rounded-full px-3 py-2 text-xs font-medium transition-all duration-200',
                  view === 'grid'
                    ? 'bg-phosphor-500/15 text-phosphor-300 shadow-[0_12px_24px_rgba(14,165,233,0.15)]'
                    : 'text-slate-500 hover:bg-slate-900/80 hover:text-slate-200',
                )}
                aria-label="Grid view"
              >
                <LayoutGrid className="h-3.5 w-3.5" />
                Grid
              </button>
              <button
                onClick={() => setView('list')}
                className={clsx(
                  'flex flex-1 items-center justify-center gap-2 rounded-full px-3 py-2 text-xs font-medium transition-all duration-200',
                  view === 'list'
                    ? 'bg-phosphor-500/15 text-phosphor-300 shadow-[0_12px_24px_rgba(14,165,233,0.15)]'
                    : 'text-slate-500 hover:bg-slate-900/80 hover:text-slate-200',
                )}
                aria-label="List view"
              >
                <List className="h-3.5 w-3.5" />
                List
              </button>
            </div>
            <p className="rounded-[1.35rem] border border-slate-800/70 bg-slate-950/45 px-4 py-4 text-xs leading-relaxed text-slate-400">
              Grid view favors fast anomaly scanning. List view favors denser
              metrics and quick action batching.
            </p>
          </div>
        </div>
      </div>

      {sections.map((section) => {
        const theme = sectionTheme[section.id] ?? sectionTheme['native-apps']
        const SectionIcon = theme.icon

        return (
          <section key={section.id} className="card-elevated space-y-4 px-5 py-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
              <div className="flex items-start gap-3">
                <div
                  className={clsx(
                    'flex h-12 w-12 items-center justify-center rounded-2xl border',
                    theme.tone,
                  )}
                >
                  <SectionIcon className="h-5 w-5 text-current" />
                </div>
                <div>
                  <div className="eyebrow">{section.id.replace('-', ' ')}</div>
                  <h2 className="display mt-2 text-xl font-semibold text-slate-100">
                    {section.title}
                  </h2>
                  <p className="mt-2 text-sm text-slate-400">
                    {section.description}
                  </p>
                </div>
              </div>
              <span
                className={clsx(
                  'rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.16em]',
                  theme.badge,
                )}
              >
                {section.items.length} services
              </span>
            </div>

            {view === 'list' ? (
              <ServiceListView
                services={section.items}
                metricsByService={metricsByService}
              />
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {section.items.map((service, i) => (
                  <motion.div
                    key={service.name}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.3,
                      delay: i * 0.04,
                      ease: [0.25, 0.46, 0.45, 0.94],
                    }}
                  >
                    <ServiceCard
                      container={service}
                      metric={metricsByService.get(service.service)}
                      metricsLoading={isMetricsLoading}
                    />
                  </motion.div>
                ))}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
