'use client'

import { Loader2 } from 'lucide-react'
import { motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Step, Subtask } from '@/lib/api/tasks'
import { getSteps, updateStep } from '@/lib/api/tasks'
import { StepItem } from './StepItem'

export interface StepsListProps {
  projectId: string
  taskId: string
  subtask: Subtask
  activeStepNumber?: number
}

export function StepsList({
  projectId,
  taskId,
  subtask,
  activeStepNumber,
}: StepsListProps) {
  const [steps, setSteps] = useState<Step[]>(subtask.steps_from_table || [])
  const [isLoading, setIsLoading] = useState(!subtask.steps_from_table?.length)
  const [updatingSteps, setUpdatingSteps] = useState<Set<number>>(new Set())
  const [optimisticUpdates, setOptimisticUpdates] = useState<Set<number>>(
    new Set(),
  )

  // Fetch steps if not already loaded
  const fetchStepsIfNeeded = useCallback(async () => {
    if (subtask.steps_from_table?.length) {
      setSteps(subtask.steps_from_table)
      setIsLoading(false)
      return
    }

    // If no table steps, check if we have legacy steps
    if (!subtask.steps?.length) {
      setIsLoading(false)
      return
    }

    try {
      setIsLoading(true)
      const fetchedSteps = await getSteps(projectId, taskId, subtask.subtask_id)
      setSteps(fetchedSteps)
    } catch (error) {
      console.error('Failed to fetch steps:', error)
      // Fallback: convert legacy steps to display format
      setSteps([])
    } finally {
      setIsLoading(false)
    }
  }, [projectId, taskId, subtask])

  // Fetch on mount
  useEffect(() => {
    fetchStepsIfNeeded()
  }, [fetchStepsIfNeeded])

  const handleToggleStep = useCallback(
    async (stepNumber: number, passes: boolean) => {
      // Optimistic update
      setOptimisticUpdates((prev) => new Set(prev).add(stepNumber))
      setUpdatingSteps((prev) => new Set(prev).add(stepNumber))

      try {
        const updated = await updateStep(
          projectId,
          taskId,
          subtask.subtask_id,
          stepNumber,
          passes,
        )
        // Update local state with server response
        setSteps((prev) =>
          prev.map((s) => (s.step_number === stepNumber ? updated : s)),
        )
        // Clear optimistic update on success
        setOptimisticUpdates((prev) => {
          const next = new Set(prev)
          next.delete(stepNumber)
          return next
        })
      } catch (error) {
        console.error('Failed to update step:', error)
        // Revert optimistic update on failure
        setOptimisticUpdates((prev) => {
          const next = new Set(prev)
          next.delete(stepNumber)
          return next
        })
      } finally {
        setUpdatingSteps((prev) => {
          const next = new Set(prev)
          next.delete(stepNumber)
          return next
        })
      }
    },
    [projectId, taskId, subtask.subtask_id],
  )

  // Calculate completion with optimistic updates
  const completedCount = useMemo(() => {
    return steps.filter((s) => {
      const isOptimistic = optimisticUpdates.has(s.step_number)
      return isOptimistic ? !s.passes : s.passes
    }).length
  }, [steps, optimisticUpdates])

  // If no steps in table, show legacy steps as read-only
  if (steps.length === 0 && subtask.steps?.length) {
    return (
      <ul className="pl-11 pr-4 pb-3 space-y-1.5">
        {subtask.steps.map((stepText, idx) => (
          <li
            key={idx}
            className="text-xs text-slate-500 flex items-start gap-2"
          >
            <span className="text-slate-700 font-mono text-2xs w-4 text-right flex-shrink-0">
              {idx + 1}.
            </span>
            <span>{stepText}</span>
          </li>
        ))}
      </ul>
    )
  }

  if (isLoading) {
    return (
      <div className="pl-11 pr-4 pb-3 flex items-center gap-2">
        <Loader2 className="w-3 h-3 animate-spin text-slate-600" />
        <span className="text-2xs text-slate-600">Loading steps...</span>
      </div>
    )
  }

  if (steps.length === 0) {
    return (
      <div className="pl-11 pr-4 pb-3">
        <span className="text-2xs text-slate-600">No steps defined</span>
      </div>
    )
  }

  return (
    <div className="pl-11 pr-4 pb-3">
      {/* Step progress indicator */}
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

      {/* Steps list */}
      <ul className="space-y-1.5">
        {steps.map((step, idx) => (
          <StepItem
            key={step.id}
            step={step}
            index={idx}
            isOptimisticallyUpdated={optimisticUpdates.has(step.step_number)}
            onToggle={handleToggleStep}
            isUpdating={updatingSteps.has(step.step_number)}
            isActive={activeStepNumber === step.step_number}
          />
        ))}
      </ul>
    </div>
  )
}
