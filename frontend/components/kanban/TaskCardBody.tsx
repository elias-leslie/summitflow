import clsx from 'clsx'
import { Bot, Link2, Loader2, Palette, ShieldCheck } from 'lucide-react'
import type { Task } from '@/lib/api'
import { getTaskStatusCardConfig } from '@/lib/task-config'
import { hasVerifiedEvidence } from '@/lib/task-verification'
import { StepProgressIndicator } from './StepProgressIndicator'

interface TaskCardBodyProps {
  task: Task
  currentStep?: string
  canExpand: boolean
}

export function TaskCardBody({
  task,
  currentStep,
  canExpand,
}: TaskCardBodyProps) {
  const _statusConfig = getTaskStatusCardConfig(task.status)
  const capability = task.capability
  const hasCriteria = capability && capability.criteria_total > 0
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total
  const isRunning = task.status === 'running'
  const sessionCount = task.agent_hub_session_ids?.length ?? 0
  const hasDesignWork = task.labels?.some((label) =>
    ['design', 'ui-design', 'mockup'].includes(label.toLowerCase()),
  )
  const hasVerifier = hasVerifiedEvidence(task.verification_result)

  return (
    <>
      <h4 className="text-sm font-medium text-slate-100 leading-tight mb-2 line-clamp-2">
        {task.title}
      </h4>

      {isRunning && currentStep && (
        <div className="flex items-center gap-2 mb-2 py-1.5 px-2 -mx-1 rounded bg-blue-500/10 border border-blue-500/20">
          <Loader2 className="h-3 w-3 animate-spin text-blue-400 shrink-0" />
          <span className="text-xs text-blue-300 truncate">{currentStep}</span>
        </div>
      )}

      {canExpand && <StepProgressIndicator status={task.status} />}

      {(sessionCount > 0 || hasVerifier || hasDesignWork) && (
        <div className="mb-2 flex flex-wrap gap-1">
          {sessionCount > 0 && (
            <span className="inline-flex items-center gap-1 rounded border border-phosphor-500/20 bg-phosphor-500/10 px-1.5 py-0.5 text-[10px] text-phosphor-300">
              <Bot className="h-3 w-3" />
              {sessionCount} agent{sessionCount === 1 ? '' : 's'}
            </span>
          )}
          {hasVerifier && (
            <span className="inline-flex items-center gap-1 rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">
              <ShieldCheck className="h-3 w-3" />
              verified
            </span>
          )}
          {hasDesignWork && (
            <span className="inline-flex items-center gap-1 rounded border border-outrun-500/20 bg-outrun-500/10 px-1.5 py-0.5 text-[10px] text-outrun-300">
              <Palette className="h-3 w-3" />
              design
            </span>
          )}
        </div>
      )}

      <div className="flex items-center justify-between">
        {capability ? (
          <div className="flex items-center gap-1.5">
            <Link2 className="h-3 w-3 text-slate-500" />
            <span className="text-xs text-phosphor-400 mono">
              {capability.capability_id}
            </span>
            {hasCriteria && (
              <span
                className={clsx(
                  'text-xs mono',
                  allPassed ? 'text-phosphor-400' : 'text-slate-400',
                )}
              >
                ({capability.criteria_passed}/{capability.criteria_total})
              </span>
            )}
          </div>
        ) : (
          <span className="text-xs text-slate-600 italic">Standalone</span>
        )}

        {hasCriteria && (
          <div className="flex items-center gap-0.5">
            {Array.from({ length: capability?.criteria_total }).map((_, i) => (
              <div
                key={i}
                className={clsx(
                  'h-1.5 w-1.5 rounded-full',
                  i < capability?.criteria_passed
                    ? 'bg-phosphor-500'
                    : 'bg-slate-600',
                )}
              />
            ))}
          </div>
        )}
      </div>
    </>
  )
}
