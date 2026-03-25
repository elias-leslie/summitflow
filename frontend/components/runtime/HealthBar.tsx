'use client'

import { clsx } from 'clsx'
import type { RuntimeServiceStatus } from '@/lib/api/runtime'
import { resolveHealthTone } from './health-utils'

const toneColors: Record<
  string,
  { bg: string; glow: string; chip: string; label: string }
> = {
  healthy: {
    bg: 'bg-emerald-500',
    glow: '0 0 6px rgba(16, 185, 129, 0.4)',
    chip: 'border-emerald-500/18 bg-emerald-500/10 text-emerald-300',
    label: 'Healthy',
  },
  unhealthy: {
    bg: 'bg-red-500',
    glow: '0 0 6px rgba(239, 68, 68, 0.4)',
    chip: 'border-rose-500/18 bg-rose-500/10 text-rose-300',
    label: 'Unhealthy',
  },
  warning: {
    bg: 'bg-amber-500',
    glow: '0 0 6px rgba(245, 158, 11, 0.4)',
    chip: 'border-amber-500/18 bg-amber-500/10 text-amber-300',
    label: 'Watch',
  },
  stopped: {
    bg: 'bg-slate-600',
    glow: 'none',
    chip: 'border-slate-700/70 bg-slate-950/70 text-slate-300',
    label: 'Stopped',
  },
  unknown: {
    bg: 'bg-slate-700',
    glow: 'none',
    chip: 'border-slate-700/70 bg-slate-950/70 text-slate-300',
    label: 'Unknown',
  },
}

interface HealthBarProps {
  services: RuntimeServiceStatus[]
}

export function HealthBar({ services }: HealthBarProps) {
  if (services.length === 0) return null

  const healthCounts = services.reduce(
    (acc, service) => {
      const tone = resolveHealthTone(service.state, service.health)
      acc[tone] = (acc[tone] ?? 0) + 1
      return acc
    },
    {} as Record<string, number>,
  )

  const alertCount =
    (healthCounts.unhealthy ?? 0) +
    (healthCounts.warning ?? 0) +
    (healthCounts.stopped ?? 0)

  const legend = ['healthy', 'warning', 'unhealthy', 'stopped']
    .map((key) => ({
      key,
      count: healthCounts[key] ?? 0,
      ...toneColors[key],
    }))
    .filter((item) => item.count > 0)

  return (
    <div className="card-elevated px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <h2 className="display text-sm font-semibold text-slate-100">
            Fleet Health
          </h2>
          <span className="rounded-full border border-slate-700/70 bg-slate-950/70 px-2 py-0.5 text-[10px] text-slate-400">
            {services.length} monitored
          </span>
          {alertCount > 0 && (
            <span className="rounded-full border border-rose-500/18 bg-rose-500/10 px-2 py-0.5 text-[10px] text-rose-300">
              {alertCount} attention
            </span>
          )}
        </div>
      </div>

      <div className="flex h-2.5 rounded-full overflow-hidden border border-white/5 bg-slate-800/60">
        {services.map((s) => {
          const tone = resolveHealthTone(s.state, s.health)
          const colors = toneColors[tone] ?? toneColors.unknown
          return (
            <div
              key={s.service}
              className={clsx('flex-1 transition-colors duration-500', colors.bg)}
              style={{ boxShadow: colors.glow }}
              title={`${s.display_name}: ${s.health || s.state}`}
            />
          )
        })}
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {legend.map((item) => (
          <span
            key={item.key}
            className={clsx(
              'rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.16em]',
              item.chip,
            )}
          >
            {item.count} {item.label}
          </span>
        ))}
      </div>
    </div>
  )
}
