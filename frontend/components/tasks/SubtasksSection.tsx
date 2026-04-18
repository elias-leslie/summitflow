'use client'

import clsx from 'clsx'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  FileCode,
  Loader2,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useState } from 'react'
import type { Subtask } from '@/lib/api/tasks'
import { PHASE_CONFIG } from '@/lib/task-config'
import { StepsList } from './subtasks/StepsList'
import { getStepInfo, groupByPhase } from './subtasks/utils'

interface SubtasksSectionProps {
  projectId: string
  taskId: string
  subtasks: Subtask[]
  onTogglePass: (subtaskId: string, passes: boolean) => Promise<void>
  isLoading?: boolean
  activeSubtaskId?: string
  activeStepNumber?: number
}

export function SubtasksSection({
  projectId,
  taskId,
  subtasks,
  onTogglePass,
  isLoading = false,
  activeSubtaskId,
  activeStepNumber,
}: SubtasksSectionProps) {
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set())
  const [expandedSubtasks, setExpandedSubtasks] = useState<Set<string>>(
    new Set(),
  )
  const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set())

  const groupedSubtasks = useMemo(() => groupByPhase(subtasks), [subtasks])
  const phases = Object.keys(groupedSubtasks)

  const togglePhase = (phase: string) => {
    setExpandedPhases((prev) => {
      const next = new Set(prev)
      if (next.has(phase)) {
        next.delete(phase)
      } else {
        next.add(phase)
      }
      return next
    })
  }

  const toggleSubtask = (subtaskId: string) => {
    setExpandedSubtasks((prev) => {
      const next = new Set(prev)
      if (next.has(subtaskId)) {
        next.delete(subtaskId)
      } else {
        next.add(subtaskId)
      }
      return next
    })
  }

  const handleTogglePass = async (subtask: Subtask) => {
    setUpdatingIds((prev) => new Set(prev).add(subtask.id))
    try {
      await onTogglePass(subtask.subtask_id, !subtask.passes)
    } finally {
      setUpdatingIds((prev) => {
        const next = new Set(prev)
        next.delete(subtask.id)
        return next
      })
    }
  }

  if (subtasks.length === 0) {
    return (
      <section>
        <div className="flex items-center gap-2 mb-2">
          <FileCode className="w-4 h-4 text-slate-500" />
          <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
            Subtasks
          </h4>
        </div>
        <div className="p-4 bg-slate-800/50 rounded-lg text-center">
          <p className="text-sm text-slate-500">No subtasks defined</p>
        </div>
      </section>
    )
  }

  const totalComplete = subtasks.filter((s) => s.passes).length

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <FileCode className="w-4 h-4 text-blue-400" />
        <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
          Subtasks
        </h4>
        <span className="text-2xs text-slate-500">
          {totalComplete}/{subtasks.length} complete
        </span>
        {isLoading && (
          <Loader2 className="w-3 h-3 animate-spin text-slate-500" />
        )}
      </div>

      <div className="space-y-1 rounded-lg border border-slate-800 overflow-hidden">
        {phases.map((phase) => {
          const phaseSubtasks = groupedSubtasks[phase]
          const isExpanded = expandedPhases.has(phase)
          const config = PHASE_CONFIG[phase] || PHASE_CONFIG.other
          const PhaseIcon = config.icon
          const completedCount = phaseSubtasks.filter((s) => s.passes).length

          return (
            <div key={phase}>
              {/* Phase Header */}
              <button
                type="button"
                onClick={() => togglePhase(phase)}
                data-testid={`phase-${phase}`}
                className="w-full flex items-center gap-3 px-4 py-2.5 bg-slate-800/50 hover:bg-slate-800 transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                )}
                <span className={clsx('p-1.5 rounded', config.bgColor)}>
                  <PhaseIcon className={clsx('w-3.5 h-3.5', config.color)} />
                </span>
                <span className="text-sm text-slate-200 capitalize flex-1 text-left">
                  {phase}
                </span>
                <span
                  className={clsx(
                    'text-xs font-mono',
                    completedCount === phaseSubtasks.length
                      ? 'text-phosphor-400'
                      : 'text-slate-500',
                  )}
                >
                  {completedCount}/{phaseSubtasks.length}
                </span>
              </button>

              {/* Subtasks List */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="divide-y divide-slate-800/50">
                      {phaseSubtasks
                        .sort((a, b) => a.display_order - b.display_order)
                        .map((subtask) => {
                          const isSubtaskExpanded = expandedSubtasks.has(
                            subtask.id,
                          )
                          const isUpdating = updatingIds.has(subtask.id)
                          const stepInfo = getStepInfo(subtask)

                          return (
                            <div key={subtask.id} className="bg-slate-900/50">
                              {/* Subtask Row */}
                              <div className="flex items-start gap-3 px-4 py-2.5">
                                {/* Checkbox */}
                                <button
                                  type="button"
                                  onClick={() => handleTogglePass(subtask)}
                                  disabled={isUpdating}
                                  className="mt-0.5 flex-shrink-0"
                                >
                                  {isUpdating ? (
                                    <Loader2 className="w-4 h-4 animate-spin text-slate-500" />
                                  ) : subtask.passes ? (
                                    <CheckCircle2 className="w-4 h-4 text-phosphor-400" />
                                  ) : (
                                    <Circle className="w-4 h-4 text-slate-600 hover:text-slate-400 transition-colors" />
                                  )}
                                </button>

                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-2xs font-mono text-slate-600">
                                      {subtask.subtask_id}
                                    </span>
                                    <span
                                      className={clsx(
                                        'text-sm',
                                        subtask.passes
                                          ? 'text-slate-500 line-through'
                                          : 'text-slate-200',
                                      )}
                                    >
                                      {subtask.description}
                                    </span>
                                  </div>

                                  {/* Steps Toggle with progress */}
                                  {stepInfo && stepInfo.total > 0 && (
                                    <button
                                      type="button"
                                      onClick={() => toggleSubtask(subtask.id)}
                                      data-testid={`steps-toggle-${subtask.subtask_id}`}
                                      className="mt-1 flex items-center gap-2 text-2xs text-slate-500 hover:text-slate-400 transition-colors group"
                                    >
                                      <span>
                                        {isSubtaskExpanded ? 'Hide' : 'Show'}{' '}
                                        steps
                                      </span>
                                      <span
                                        className={clsx(
                                          'font-mono px-1.5 py-0.5 rounded',
                                          stepInfo.completed === stepInfo.total
                                            ? 'bg-phosphor-500/10 text-phosphor-400'
                                            : 'bg-slate-800 text-slate-500',
                                        )}
                                      >
                                        {stepInfo.completed}/{stepInfo.total}
                                      </span>
                                    </button>
                                  )}
                                </div>
                              </div>

                              {/* Steps */}
                              <AnimatePresence>
                                {isSubtaskExpanded &&
                                  stepInfo &&
                                  stepInfo.total > 0 && (
                                    <motion.div
                                      initial={{ height: 0, opacity: 0 }}
                                      animate={{ height: 'auto', opacity: 1 }}
                                      exit={{ height: 0, opacity: 0 }}
                                      className="overflow-hidden"
                                    >
                                      <StepsList
                                        projectId={projectId}
                                        taskId={taskId}
                                        subtask={subtask}
                                        activeStepNumber={
                                          activeSubtaskId === subtask.subtask_id
                                            ? activeStepNumber
                                            : undefined
                                        }
                                      />
                                    </motion.div>
                                  )}
                              </AnimatePresence>
                            </div>
                          )
                        })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )
        })}
      </div>
    </section>
  )
}
