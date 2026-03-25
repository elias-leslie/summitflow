'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { type RuntimeServiceStatus, runtimeApi } from '@/lib/api/runtime'
import { POLL_MONITOR, POLL_STANDARD } from '@/lib/polling'
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

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-32 rounded-lg bg-slate-800/40 animate-pulse"
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
      <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-8 text-center">
        <p className="text-slate-400">No managed runtime services found.</p>
        <p className="text-sm text-slate-500 mt-1">
          Start or rebuild services with:{' '}
          <code className="text-amber-400">
            rebuild.sh summitflow
          </code>
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* View toggle */}
      <div className="flex items-center justify-end">
        <div className="flex items-center gap-0.5 rounded-lg bg-slate-800/60 border border-slate-700/50 p-0.5">
          <button
            onClick={() => setView('grid')}
            className={clsx(
              'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
              view === 'grid'
                ? 'bg-phosphor-500/15 text-phosphor-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
            )}
            aria-label="Grid view"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="inline-block">
              <rect x="1" y="1" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="9" y="1" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="1" y="9" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
              <rect x="9" y="9" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" />
            </svg>
            Grid
          </button>
          <button
            onClick={() => setView('list')}
            className={clsx(
              'flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
              view === 'list'
                ? 'bg-phosphor-500/15 text-phosphor-400 shadow-sm'
                : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
            )}
            aria-label="List view"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="inline-block">
              <line x1="1" y1="3" x2="15" y2="3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="1" y1="8" x2="15" y2="8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <line x1="1" y1="13" x2="15" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            List
          </button>
        </div>
      </div>

      {sections.map((section) => (
        <section key={section.id} className="space-y-3">
          <div>
            <h2 className="display text-sm font-bold uppercase tracking-[0.16em] text-slate-200">
              {section.title}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {section.description}
            </p>
          </div>

          {view === 'list' ? (
            <ServiceListView
              services={section.items}
              metricsByService={metricsByService}
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {section.items.map((service, i) => (
                <motion.div
                  key={service.name}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: i * 0.04, ease: [0.25, 0.46, 0.45, 0.94] }}
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
      ))}
    </div>
  )
}
