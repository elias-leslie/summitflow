import {
  ExternalLink,
  GitPullRequest,
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
  const statusConfig = getTaskStatusCardConfig(task.status)
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

      {(task.status === 'ai_reviewing' || task.status === 'pr_created') && (
        <div className="flex items-center gap-2 mb-2 py-1.5 px-2 -mx-1 rounded bg-slate-800/50">
          <span
            className={`flex items-center gap-1.5 ${statusConfig?.className || ''}`}
          >
            {statusConfig?.icon}
            <span className="text-xs font-medium">{statusConfig?.title}</span>
          </span>
          {task.pull_request_url && (
            <a
              href={task.pull_request_url}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              <GitPullRequest className="h-3 w-3" />
              <span>PR</span>
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
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
                className={`text-xs mono ${allPassed ? 'text-phosphor-400' : 'text-slate-400'}`}
              >
                ({capability.criteria_passed}/{capability.criteria_total})
              </span>
            )}
          </div>
        ) : task.pull_request_url &&
          task.status !== 'ai_reviewing' &&
          task.status !== 'pr_created' ? (
          <a
            href={task.pull_request_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            <GitPullRequest className="h-3 w-3" />
            <span>View PR</span>
            <ExternalLink className="h-2.5 w-2.5" />
          </a>
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
