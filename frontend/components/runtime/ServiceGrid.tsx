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
    <div className="space-y-4">
      <div className="card-elevated px-4 py-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="space-y-2">
            <h2 className="display text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
              Service Control Deck
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              {overviewCards.map((card) => {
                const Icon = card.icon
                return (
                  <div
                    key={card.label}
                    className={clsx('rounded-lg border px-3 py-2', card.tone)}
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className="h-3.5 w-3.5 text-current" />
                      <div className="flex items-baseline gap-2">
                        <span className="font-mono text-lg tabular-nums text-slate-50">
                          {card.value}
                        </span>
                        <span className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
                          {card.label}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="flex items-center gap-1 rounded-full border border-slate-700/50 bg-slate-950/70 p-1">
            <button
              onClick={() => setView('grid')}
              className={clsx(
                'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all',
                view === 'grid'
                  ? 'bg-phosphor-500/15 text-phosphor-300'
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
                'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all',
                view === 'list'
                  ? 'bg-phosphor-500/15 text-phosphor-300'
                  : 'text-slate-500 hover:bg-slate-900/80 hover:text-slate-200',
              )}
              aria-label="List view"
            >
              <List className="h-3.5 w-3.5" />
              List
            </button>
          </div>
        </div>
      </div>

      {sections.map((section) => {
        const theme = sectionTheme[section.id] ?? sectionTheme['native-apps']
        const SectionIcon = theme.icon

        return (
          <section key={section.id} className="card-elevated space-y-3 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <SectionIcon className={clsx('h-4 w-4', theme.tone.includes('cyan') ? 'text-cyan-300' : theme.tone.includes('emerald') ? 'text-emerald-300' : 'text-amber-300')} />
                <div>
                  <h2 className="display text-sm font-semibold text-slate-100">
                    {section.title}
                  </h2>
                  <p className="text-xs text-slate-500">
                    {section.description}
                  </p>
                </div>
              </div>
              <span
                className={clsx(
                  'rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.14em]',
                  theme.badge,
                )}
              >
                {section.items.length}
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
