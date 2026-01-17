'use client'

import {
  Braces,
  Check,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Circle,
  Copy,
  FileCode,
  FileEdit,
  FileMinus,
  FilePlus,
  FileText,
  Globe,
  Loader2,
  MessageSquareQuote,
  Square,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Step, Subtask } from '@/lib/api/tasks'
import { getSteps, updateStep } from '@/lib/api/tasks'
import { PHASE_CONFIG } from '@/lib/utils/task-status'

interface SubtasksSectionProps {
  projectId: string
  taskId: string
  subtasks: Subtask[]
  onTogglePass: (subtaskId: string, passes: boolean) => Promise<void>
  isLoading?: boolean
  activeSubtaskId?: string
  activeStepNumber?: number
}

function groupByPhase(subtasks: Subtask[]): Record<string, Subtask[]> {
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

interface StepItemProps {
  step: Step
  index: number
  isOptimisticallyUpdated: boolean
  onToggle: (stepNumber: number, passes: boolean) => void
  isUpdating: boolean
  isActive?: boolean
}

// =============================================================================
// Type Detection for Step Specs
// =============================================================================

type SpecType = 'api' | 'prompt' | 'file' | 'generic'

interface SpecRecord {
  [key: string]: unknown
}

/** Check if a value looks like a file path */
function looksLikeFilePath(value: unknown): boolean {
  if (typeof value !== 'string') return false
  // Starts with ~, /, ./, or has file extension
  return /^[~./]|^[A-Za-z]:[/\\]|\.\w+$/.test(value)
}

/** Detect spec type from keys and values */
function detectSpecType(spec: SpecRecord): SpecType {
  const keys = Object.keys(spec).map((k) => k.toLowerCase())

  // File spec: has file-specific keys OR path that looks like a file path
  if (
    keys.some((k) =>
      [
        'file',
        'filepath',
        'file_path',
        'filename',
        'operation',
        'create',
        'modify',
        'delete',
      ].includes(k),
    ) ||
    (keys.includes('path') && looksLikeFilePath(spec.path || spec.Path))
  ) {
    return 'file'
  }

  // API spec: has endpoint, method, url, or api-related keys
  // Note: "path" alone is ambiguous, so require method or endpoint for API
  if (
    keys.some((k) => ['endpoint', 'method', 'url', 'api', 'route'].includes(k))
  ) {
    return 'api'
  }

  // Prompt spec: has prompt, template, or message-related keys
  if (
    keys.some((k) =>
      ['prompt', 'template', 'message', 'system', 'user', 'assistant'].includes(
        k,
      ),
    )
  ) {
    return 'prompt'
  }

  return 'generic'
}

// =============================================================================
// Type-Specific Spec Renderers
// =============================================================================

/** Method badge for API specs */
function MethodBadge({ method }: { method: string }) {
  const colors: Record<string, string> = {
    GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    PATCH: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    DELETE: 'bg-red-500/20 text-red-400 border-red-500/30',
  }
  const colorClass =
    colors[method.toUpperCase()] ||
    'bg-slate-500/20 text-slate-400 border-slate-500/30'

  return (
    <span
      className={`px-1.5 py-0.5 text-2xs font-mono font-semibold rounded border ${colorClass}`}
    >
      {method.toUpperCase()}
    </span>
  )
}

/** API spec renderer with method badge and endpoint */
function ApiSpecRenderer({ spec }: { spec: SpecRecord }) {
  const method =
    (spec.method as string) || (spec.http_method as string) || 'GET'
  const endpoint =
    (spec.endpoint as string) ||
    (spec.path as string) ||
    (spec.url as string) ||
    (spec.route as string) ||
    ''

  // Extract other fields for additional info
  const otherFields = Object.entries(spec).filter(
    ([key]) =>
      !['method', 'http_method', 'endpoint', 'path', 'url', 'route'].includes(
        key.toLowerCase(),
      ),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 font-mono">
        <Globe className="w-3.5 h-3.5 text-blue-400" />
        <MethodBadge method={method} />
        <code className="text-xs text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded">
          {endpoint || '(no endpoint)'}
        </code>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string'
                  ? value
                  : JSON.stringify(value, null, 2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Highlight template variables in text ({{var}} or {var} patterns) */
function HighlightTemplateVars({ text }: { text: string }) {
  // Match both {{var}} and {var} patterns
  const parts = text.split(/(\{\{?\w+\}?\})/g)

  return (
    <>
      {parts.map((part, i) => {
        if (part.match(/^\{\{?\w+\}?\}$/)) {
          return (
            <span key={i} className="text-purple-400 font-semibold">
              {part}
            </span>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

/** Prompt spec renderer with quoted text and variable highlighting */
function PromptSpecRenderer({ spec }: { spec: SpecRecord }) {
  const promptFields = [
    'prompt',
    'template',
    'message',
    'system',
    'user',
    'assistant',
  ]
  const mainPrompt = promptFields
    .map((f) => spec[f])
    .find((v) => typeof v === 'string') as string | undefined

  const otherFields = Object.entries(spec).filter(
    ([key]) => !promptFields.includes(key.toLowerCase()),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <MessageSquareQuote className="w-3.5 h-3.5 text-purple-400 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          {mainPrompt ? (
            <blockquote className="text-xs text-slate-300 italic border-l-2 border-purple-500/40 pl-3 py-1 bg-purple-500/5 rounded-r">
              <HighlightTemplateVars text={mainPrompt} />
            </blockquote>
          ) : (
            <span className="text-2xs text-slate-500">(no prompt text)</span>
          )}
        </div>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string' ? (
                  <HighlightTemplateVars text={value} />
                ) : (
                  JSON.stringify(value)
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Operation badge for file specs */
function OperationBadge({ operation }: { operation: string }) {
  const op = operation.toLowerCase()
  const config: Record<
    string,
    { icon: typeof FileText; color: string; label: string }
  > = {
    create: {
      icon: FilePlus,
      color: 'bg-emerald-500/20 text-emerald-400',
      label: 'CREATE',
    },
    modify: {
      icon: FileEdit,
      color: 'bg-amber-500/20 text-amber-400',
      label: 'MODIFY',
    },
    update: {
      icon: FileEdit,
      color: 'bg-amber-500/20 text-amber-400',
      label: 'UPDATE',
    },
    delete: {
      icon: FileMinus,
      color: 'bg-red-500/20 text-red-400',
      label: 'DELETE',
    },
    read: {
      icon: FileText,
      color: 'bg-blue-500/20 text-blue-400',
      label: 'READ',
    },
  }
  const {
    icon: Icon,
    color,
    label,
  } = config[op] || {
    icon: FileText,
    color: 'bg-slate-500/20 text-slate-400',
    label: op.toUpperCase(),
  }

  return (
    <span
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-semibold ${color}`}
    >
      <Icon className="w-3 h-3" />
      {label}
    </span>
  )
}

/** File spec renderer with clickable path and operation badge */
function FileSpecRenderer({ spec }: { spec: SpecRecord }) {
  const filePath =
    (spec.file as string) ||
    (spec.filepath as string) ||
    (spec.file_path as string) ||
    (spec.path as string) ||
    (spec.filename as string) ||
    ''
  const operation =
    (spec.operation as string) ||
    (spec.action as string) ||
    (spec.create
      ? 'create'
      : spec.modify
        ? 'modify'
        : spec.delete
          ? 'delete'
          : '')

  const otherFields = Object.entries(spec).filter(
    ([key]) =>
      ![
        'file',
        'filepath',
        'file_path',
        'path',
        'filename',
        'operation',
        'action',
        'create',
        'modify',
        'delete',
      ].includes(key.toLowerCase()),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <FileText className="w-3.5 h-3.5 text-orange-400" />
        {operation && <OperationBadge operation={operation} />}
        <code className="text-xs text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded font-mono truncate max-w-xs">
          {filePath || '(no file path)'}
        </code>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string' ? value : JSON.stringify(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Generic spec renderer as key-value table */
function GenericSpecRenderer({ spec }: { spec: SpecRecord }) {
  const entries = Object.entries(spec)

  if (entries.length === 0) {
    return <span className="text-2xs text-slate-500">(empty spec)</span>
  }

  return (
    <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <span className="text-2xs text-slate-500 font-mono text-right">
            {key}:
          </span>
          <span className="text-2xs text-amber-300/80 break-all">
            {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Main spec renderer that delegates to type-specific renderer */
function SpecRenderer({ spec }: { spec: SpecRecord }) {
  const specType = detectSpecType(spec)

  switch (specType) {
    case 'api':
      return <ApiSpecRenderer spec={spec} />
    case 'prompt':
      return <PromptSpecRenderer spec={spec} />
    case 'file':
      return <FileSpecRenderer spec={spec} />
    default:
      return <GenericSpecRenderer spec={spec} />
  }
}

function StepItem({
  step,
  index,
  isOptimisticallyUpdated,
  onToggle,
  isUpdating,
  isActive = false,
}: StepItemProps) {
  // Auto-expand spec for active step
  const [isSpecExpanded, setIsSpecExpanded] = useState(isActive)
  const [copied, setCopied] = useState(false)
  const passes = isOptimisticallyUpdated ? !step.passes : step.passes
  const hasSpec = step.spec && Object.keys(step.spec).length > 0

  // Expand spec when step becomes active
  useEffect(() => {
    if (isActive && hasSpec) {
      setIsSpecExpanded(true)
    }
  }, [isActive, hasSpec])

  const handleCopy = useCallback(async () => {
    if (!step.spec) return
    await navigator.clipboard.writeText(JSON.stringify(step.spec, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [step.spec])

  return (
    <motion.li
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.03 }}
      className={`group relative ${isActive ? 'z-10' : ''}`}
    >
      {/* Active step indicator - animated border */}
      {isActive && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute -inset-2 bg-gradient-to-r from-blue-500/10 to-purple-500/10 rounded-lg border border-blue-500/30"
        >
          <div className="absolute inset-0 bg-blue-500/5 animate-pulse rounded-lg" />
        </motion.div>
      )}
      <div className="flex items-start gap-2.5">
        <button
          onClick={() => onToggle(step.step_number, !passes)}
          disabled={isUpdating}
          className="mt-0.5 flex-shrink-0 focus:outline-none focus:ring-1 focus:ring-blue-500/50 rounded"
          aria-label={passes ? 'Mark step incomplete' : 'Mark step complete'}
        >
          {isUpdating ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500" />
          ) : passes ? (
            <motion.div
              initial={{ scale: 0.8 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 400, damping: 15 }}
            >
              <CheckSquare className="w-3.5 h-3.5 text-phosphor-400" />
            </motion.div>
          ) : (
            <Square className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-colors" />
          )}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            <span className="text-slate-600 text-2xs font-mono flex-shrink-0 w-4 text-right">
              {step.step_number}.
            </span>
            <span
              className={`text-xs transition-all duration-200 ${
                passes
                  ? 'text-slate-600 line-through decoration-slate-700'
                  : isActive
                    ? 'text-slate-200 font-medium'
                    : 'text-slate-400'
              }`}
            >
              {step.description}
            </span>
            {isActive && (
              <motion.span
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex-shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30"
              >
                <Loader2 className="w-3 h-3 animate-spin" />
                <span className="text-2xs font-semibold">Running</span>
              </motion.span>
            )}
            {hasSpec && (
              <button
                onClick={() => setIsSpecExpanded(!isSpecExpanded)}
                data-testid={`spec-btn-${step.step_number}`}
                className={`flex-shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded transition-all duration-150 ${
                  isSpecExpanded
                    ? 'bg-blue-500/15 text-blue-400'
                    : 'bg-slate-800/60 text-slate-500 hover:bg-slate-700/60 hover:text-blue-400'
                }`}
                aria-label={isSpecExpanded ? 'Hide spec' : 'Show spec'}
              >
                <Braces className="w-3 h-3" />
                <span className="text-2xs font-medium">spec</span>
                {isSpecExpanded ? (
                  <ChevronDown className="w-3.5 h-3.5" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5" />
                )}
              </button>
            )}
          </div>
          <AnimatePresence>
            {isSpecExpanded && hasSpec && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="overflow-hidden"
              >
                <div className="mt-2 ml-6 relative group/spec">
                  {/* Copy button - more visible on hover */}
                  <button
                    onClick={handleCopy}
                    className={`absolute top-2 right-2 p-1.5 rounded-md transition-all duration-150 z-10 ${
                      copied
                        ? 'bg-phosphor-500/20 text-phosphor-400'
                        : 'bg-slate-700/80 text-slate-400 opacity-60 group-hover/spec:opacity-100 hover:bg-slate-600 hover:text-slate-200'
                    }`}
                    aria-label="Copy spec"
                  >
                    {copied ? (
                      <Check className="w-3.5 h-3.5" />
                    ) : (
                      <Copy className="w-3.5 h-3.5" />
                    )}
                  </button>
                  {/* Spec content with left accent border */}
                  <div className="bg-slate-900/80 border border-slate-700/50 border-l-2 border-l-blue-500/40 rounded-md shadow-inner overflow-hidden">
                    <div className="p-3 pr-10">
                      <SpecRenderer spec={step.spec as SpecRecord} />
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.li>
  )
}

interface StepsListProps {
  projectId: string
  taskId: string
  subtask: Subtask
  activeStepNumber?: number
}

function StepsList({
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

  // Get step count for a subtask (from table or legacy)
  const getStepInfo = (subtask: Subtask) => {
    if (subtask.step_summary) {
      return {
        total: subtask.step_summary.total,
        completed: subtask.step_summary.completed,
      }
    }
    if (subtask.steps_from_table?.length) {
      const completed = subtask.steps_from_table.filter((s) => s.passes).length
      return { total: subtask.steps_from_table.length, completed }
    }
    if (subtask.steps?.length) {
      return { total: subtask.steps.length, completed: 0 }
    }
    return null
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
                onClick={() => togglePhase(phase)}
                data-testid={`phase-${phase}`}
                className="w-full flex items-center gap-3 px-4 py-2.5 bg-slate-800/50 hover:bg-slate-800 transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                )}
                <span className={`p-1.5 rounded ${config.bgColor}`}>
                  <PhaseIcon className={`w-3.5 h-3.5 ${config.color}`} />
                </span>
                <span className="text-sm text-slate-200 capitalize flex-1 text-left">
                  {phase}
                </span>
                <span
                  className={`text-xs font-mono ${
                    completedCount === phaseSubtasks.length
                      ? 'text-phosphor-400'
                      : 'text-slate-500'
                  }`}
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
                                      className={`text-sm ${
                                        subtask.passes
                                          ? 'text-slate-500 line-through'
                                          : 'text-slate-200'
                                      }`}
                                    >
                                      {subtask.description}
                                    </span>
                                  </div>

                                  {/* Steps Toggle with progress */}
                                  {stepInfo && stepInfo.total > 0 && (
                                    <button
                                      onClick={() => toggleSubtask(subtask.id)}
                                      data-testid={`steps-toggle-${subtask.subtask_id}`}
                                      className="mt-1 flex items-center gap-2 text-2xs text-slate-500 hover:text-slate-400 transition-colors group"
                                    >
                                      <span>
                                        {isSubtaskExpanded ? 'Hide' : 'Show'}{' '}
                                        steps
                                      </span>
                                      <span
                                        className={`font-mono px-1.5 py-0.5 rounded ${
                                          stepInfo.completed === stepInfo.total
                                            ? 'bg-phosphor-500/10 text-phosphor-400'
                                            : 'bg-slate-800 text-slate-500'
                                        }`}
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
