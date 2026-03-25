'use client'

import { clsx } from 'clsx'
import type { RuntimeServiceStatus } from '@/lib/api/runtime'
import { resolveHealthTone } from './health-utils'

const toneColors: Record<string, { bg: string; glow: string }> = {
  healthy: { bg: 'bg-emerald-500', glow: '0 0 6px rgba(16, 185, 129, 0.4)' },
  unhealthy: { bg: 'bg-red-500', glow: '0 0 6px rgba(239, 68, 68, 0.4)' },
  warning: { bg: 'bg-amber-500', glow: '0 0 6px rgba(245, 158, 11, 0.4)' },
  stopped: { bg: 'bg-slate-600', glow: 'none' },
  unknown: { bg: 'bg-slate-700', glow: 'none' },
}

interface HealthBarProps {
  services: RuntimeServiceStatus[]
}

export function HealthBar({ services }: HealthBarProps) {
  if (services.length === 0) return null

  return (
    <div className="flex gap-0.5 h-2.5 rounded-full overflow-hidden bg-slate-800/50 ring-1 ring-white/5">
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
  )
}
