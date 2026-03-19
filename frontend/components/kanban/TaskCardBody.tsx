import {
  Link2,
  Loader2,
} from 'lucide-react'
import type { Task } from '@/lib/api'
import { getTaskStatusCardConfig } from '@/lib/task-config'
import { StepProgressIndicator } from './StepProgressIndicator'

interface TaskCardBodyProps {
  task: Task
  currentStep?: string
  canExpand: boolean
}

export function TaskCardBody({ task, currentStep, canExpand }: TaskCardBodyProps) {
  const _statusConfig = getTaskStatusCardConfig(task.status)
  const capability = task.capability
  const hasCriteria = capability && capability.criteria_total > 0
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total
  const isRunning = task.status === 'running'

  return (
    <>
      <h4 className="text-sm font-medium text-white leading-tight mb-2 line-clamp-2">
        {task.title}
      </h4>

      {isRunning && currentStep && (
        <div className="flex items-center gap-2 mb-2 py-1.5 px-2 -mx-1 rounded bg-blue-500/10 border border-blue-500/20">
          <Loader2 className="h-3 w-3 animate-spin text-blue-400 shrink-0" />
          <span className="text-xs text-blue-300 truncate">
            {currentStep}
          </span>
        </div>
      )}

      {canExpand && <StepProgressIndicator status={task.status} />}


      <div className="flex items-center justify-between">
        {capability ? (
          <div className="flex items-center gap-1.5">
            <Link2 className="h-3 w-3 text-slate-500" />
            <span className="text-xs text-phosphor-400 mono">
              {capability.capability_id}
            </span>
            {hasCriteria && (
              <span
                className={`text-xs mono ${allPassed ? 'text-phosphor-400' : 'text-slate-400'}`}
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
            {Array.from({ length: capability?.criteria_total }).map(
              (_, i) => (
                <div
                  key={i}
                  className={`h-1.5 w-1.5 rounded-full ${
                    i < capability?.criteria_passed
                      ? 'bg-phosphor-500'
                      : 'bg-slate-600'
                  }`}
                />
              ),
            )}
          </div>
        )}
      </div>
    </>
  )
}
