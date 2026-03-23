'use client'

import { clsx } from 'clsx'
import type { RuntimeServiceStatus } from '@/lib/api/runtime'
import { resolveHealthTone } from './health-utils'

const toneColors: Record<string, string> = {
  healthy: 'bg-emerald-500',
  unhealthy: 'bg-red-500',
  warning: 'bg-amber-500',
  stopped: 'bg-slate-600',
  unknown: 'bg-slate-700',
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
        return (
          <div
            key={s.service}
            className={clsx('flex-1 transition-colors duration-500', toneColors[tone])}
            title={`${s.display_name}: ${s.health || s.state}`}
          />
        )
      })}
    </div>
  )
}
