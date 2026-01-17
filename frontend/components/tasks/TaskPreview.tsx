'use client'

import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileCode,
  ListChecks,
  Tag,
  Target,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Subtask, Task, TaskAcceptanceCriterion } from '@/lib/api/tasks'
import {
  CATEGORY_COLORS,
  getPriorityConfig,
  PHASE_COLORS,
  PHASE_ICONS,
} from '@/lib/utils/task-status'

interface TaskPreviewProps {
  task: Task
  subtasks?: Subtask[]
  highlightChanges?: boolean
}

function groupSubtasksByPhase(subtasks: Subtask[]): Record<string, Subtask[]> {
  return subtasks.reduce(
    (acc, subtask) => {
      const phase = subtask.phase || 'other'
      if (!acc[phase]) acc[phase] = []
      acc[phase].push(subtask)
      return acc
    },
    {} as Record<string, Subtask[]>,
  )
}

export function TaskPreview({
  task,
  subtasks = [],
  highlightChanges = false,
}: TaskPreviewProps) {
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set())
  const groupedSubtasks = groupSubtasksByPhase(subtasks)
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

  const priorityInfo = getPriorityConfig(task.priority)

  return (
    <div className="space-y-5">
      {/* Objective Section */}
      <section>
        <div className="flex items-center gap-2 mb-2">
          <Target className="w-4 h-4 text-phosphor-400" />
          <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
            Objective
          </h4>
        </div>
        {task.objective ? (
          <motion.div
            initial={highlightChanges ? { scale: 0.98 } : false}
            animate={{ scale: 1 }}
            className="p-4 bg-phosphor-500/5 border border-phosphor-500/20 rounded-lg"
          >
            <p className="text-sm text-white leading-relaxed">
              {task.objective}
            </p>
          </motion.div>
        ) : (
          <div className="p-4 bg-amber-500/5 border border-amber-500/20 rounded-lg flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <p className="text-sm text-amber-400">No objective defined</p>
          </div>
        )}
      </section>

      {/* Metadata Row */}
      <section className="flex flex-wrap items-center gap-3 py-3 border-y border-slate-800">
        <span className={`text-xs font-medium ${priorityInfo.color}`}>
          {priorityInfo.label}
        </span>
        <span className="text-slate-600">·</span>
        <span className="text-xs text-slate-400 capitalize">
          {task.task_type}
        </span>
        {task.labels && task.labels.length > 0 && (
          <>
            <span className="text-slate-600">·</span>
            <div className="flex items-center gap-1.5">
              <Tag className="w-3 h-3 text-slate-500" />
              {task.labels.slice(0, 3).map((label) => (
                <span
                  key={label}
                  className="px-1.5 py-0.5 text-2xs bg-slate-800 text-slate-400 rounded"
                >
                  {label}
                </span>
              ))}
              {task.labels.length > 3 && (
                <span className="text-2xs text-slate-500">
                  +{task.labels.length - 3}
                </span>
              )}
            </div>
          </>
        )}
      </section>

      {/* Acceptance Criteria */}
      {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <ListChecks className="w-4 h-4 text-emerald-400" />
            <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
              Acceptance Criteria
            </h4>
            <span className="text-2xs text-slate-500">
              ({task.acceptance_criteria.length})
            </span>
          </div>
          <ul className="space-y-2">
            {task.acceptance_criteria.map(
              (criterion: TaskAcceptanceCriterion, index: number) => (
                <motion.li
                  key={criterion.id || index}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="flex items-start gap-3 p-2 rounded-md hover:bg-slate-800/50 transition-colors"
                >
                  <div className="w-5 h-5 rounded-full bg-slate-800 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <span className="text-2xs text-slate-500">{index + 1}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-slate-200">
                      {criterion.criterion}
                    </p>
                    {(criterion.category || criterion.threshold) && (
                      <div className="flex items-center gap-2 mt-1">
                        {criterion.category && (
                          <span
                            className={`px-1.5 py-0.5 text-2xs rounded border ${CATEGORY_COLORS[criterion.category] || 'text-slate-400 bg-slate-800'}`}
                          >
                            {criterion.category}
                          </span>
                        )}
                        {criterion.threshold && (
                          <span className="text-2xs text-slate-500">
                            {criterion.threshold}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </motion.li>
              ),
            )}
          </ul>
        </section>
      )}

      {/* Subtasks by Phase */}
      {phases.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <FileCode className="w-4 h-4 text-blue-400" />
            <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
              Implementation Subtasks
            </h4>
            <span className="text-2xs text-slate-500">({subtasks.length})</span>
          </div>
          <div className="space-y-1">
            {phases.map((phase) => {
              const phaseSubtasks = groupedSubtasks[phase]
              const isExpanded = expandedPhases.has(phase)
              const PhaseIcon = PHASE_ICONS[phase] || FileCode
              const phaseColor =
                PHASE_COLORS[phase] || 'text-slate-400 bg-slate-800'
              const completedCount = phaseSubtasks.filter(
                (s) => s.passes,
              ).length

              return (
                <div key={phase} className="rounded-lg overflow-hidden">
                  <button
                    onClick={() => togglePhase(phase)}
                    className="w-full flex items-center gap-3 px-3 py-2 hover:bg-slate-800/50 transition-colors"
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4 text-slate-500" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-slate-500" />
                    )}
                    <span className={`p-1 rounded ${phaseColor}`}>
                      <PhaseIcon className="w-3 h-3" />
                    </span>
                    <span className="text-sm text-slate-300 capitalize flex-1 text-left">
                      {phase}
                    </span>
                    <span className="text-2xs text-slate-500">
                      {completedCount}/{phaseSubtasks.length}
                    </span>
                  </button>

                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <ul className="pl-10 pr-3 pb-2 space-y-1">
                          {phaseSubtasks.map((subtask) => (
                            <li
                              key={subtask.id}
                              className="flex items-start gap-2 py-1.5"
                            >
                              <span className="text-2xs text-slate-600 w-8 flex-shrink-0 pt-0.5">
                                {subtask.subtask_id}
                              </span>
                              <span
                                className={`text-sm ${subtask.passes ? 'text-slate-500 line-through' : 'text-slate-300'}`}
                              >
                                {subtask.description}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
