import type { TaskStatus } from '@/lib/api'
import { EXECUTION_PHASES, getPhaseFromStatus } from './task-card-utils'

interface StepProgressIndicatorProps {
  status: TaskStatus
}

export function StepProgressIndicator({ status }: StepProgressIndicatorProps) {
  const currentPhase = getPhaseFromStatus(status)
  if (!currentPhase) return null

  const currentIndex = EXECUTION_PHASES.indexOf(currentPhase)

  return (
    <div className="flex items-center gap-1 text-xs">
      {EXECUTION_PHASES.map((phase, index) => {
        const isActive = index === currentIndex
        const isPast = index < currentIndex
        return (
          <div key={phase} className="flex items-center gap-1">
            {index > 0 && (
              <div
                className={`w-3 h-px transition-colors ${isPast ? 'bg-phosphor-500/60' : 'bg-slate-700'}`}
              />
            )}
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                isActive
                  ? 'bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30'
                  : isPast
                    ? 'bg-slate-700 text-slate-300'
                    : 'bg-slate-800 text-slate-500'
              }`}
            >
              {phase}
            </span>
          </div>
        )
      })}
    </div>
  )
}
