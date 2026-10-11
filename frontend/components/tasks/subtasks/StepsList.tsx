'use client'

import { motion } from 'motion/react'
import type { Subtask } from '@/lib/api/tasks'
import { StepItem } from './StepItem'
import { getDisplaySteps } from './utils'

export interface StepsListProps {
  subtask: Subtask
  activeStepNumber?: number
}

export function StepsList({ subtask, activeStepNumber }: StepsListProps) {
  const steps = getDisplaySteps(subtask)

  if (steps.length === 0) {
    return (
      <div className="pl-11 pr-4 pb-3">
        <span className="text-2xs text-slate-600">No steps defined</span>
      </div>
    )
  }

  const completedCount = steps.filter((s) => s.passes).length

  return (
    <div className="pl-11 pr-4 pb-3">
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-0.5 bg-slate-800 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-phosphor-500/60 to-phosphor-400"
            initial={{ width: 0 }}
            animate={{ width: `${(completedCount / steps.length) * 100}%` }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
          />
        </div>
        <span className="text-2xs font-mono text-slate-500 tabular-nums">
          {completedCount}/{steps.length}
        </span>
      </div>

      <ul className="space-y-1.5">
        {steps.map((step, idx) => (
          <StepItem
            key={step.step_number}
            step={step}
            index={idx}
            isActive={activeStepNumber === step.step_number}
          />
        ))}
      </ul>
    </div>
  )
}
