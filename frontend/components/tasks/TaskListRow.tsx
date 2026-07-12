import clsx from 'clsx'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import type { Task } from '@/lib/api'
import type { Subtask } from '@/lib/api/tasks'
import { formatTimeAgo } from '@/lib/format'
import { priorityConfig, statusIconConfig, typeConfig } from '@/lib/task-config'
import { cn } from '@/lib/utils'
import { CriteriaProgress } from './CriteriaProgress'
import { EnrichmentStatusBadge } from './EnrichmentStatusBadge'
import { SubtaskProgress } from './SubtaskProgress'

interface TaskListRowProps {
  task: Task
  isExpanded: boolean
  onToggle: () => void
  onDelete?: (taskId: string) => void
  isSelected?: boolean
  onToggleSelect?: (taskId: string) => void
  subtasks: Subtask[]
}

export function TaskListRow({
  task,
  isExpanded,
  onToggle,
  onDelete,
  isSelected,
  onToggleSelect,
  subtasks,
}: TaskListRowProps) {
  const priority = task.priority ?? 2
  const taskType = task.task_type ?? 'task'
  const priorityStyle = priorityConfig[priority] || priorityConfig[2]
  const typeStyle = typeConfig[taskType] || typeConfig.task
  const statusStyle = statusIconConfig[task.status] || statusIconConfig.pending

  const TypeIcon = typeStyle.icon
  const StatusIcon = statusStyle.icon

  return (
    <tr
      className={cn(
        'border-b border-slate-800 hover:bg-slate-800/30 focus-visible:bg-slate-800/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-phosphor-500/50 transition-colors cursor-pointer',
        isExpanded && 'bg-slate-800/50',
        isSelected && 'bg-phosphor-500/10',
      )}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onToggle()
        }
      }}
      tabIndex={0}
    >
      {/* Checkbox */}
      {onToggleSelect && (
        <td className="w-8 px-2 py-3" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            aria-label={`Select ${task.title}`}
            checked={isSelected}
            onChange={() => onToggleSelect(task.id)}
            className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
          />
        </td>
      )}

      {/* Expand */}
      <td className="hidden w-8 px-2 py-3 lg:table-cell">
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-500" />
        )}
      </td>

      {/* Priority */}
      <td className="hidden px-3 py-3 sm:table-cell">
        <span
          className={clsx(
            'text-xs px-1.5 py-0.5 rounded border mono font-medium',
            priorityStyle.className,
          )}
        >
          {priorityStyle.label}
        </span>
      </td>

      {/* Type */}
      <td className="hidden px-3 py-3 md:table-cell">
        <span
          className={clsx('flex items-center gap-1.5', typeStyle.className)}
        >
          <TypeIcon className="h-3.5 w-3.5" />
          <span className="text-xs">{typeStyle.label}</span>
        </span>
      </td>

      {/* ID */}
      <td className="hidden px-3 py-3 lg:table-cell">
        <span className="text-xs mono text-slate-500 whitespace-nowrap">
          {task.id}
        </span>
      </td>

      {/* Title + Warning */}
      <td className="min-w-0 px-2 py-3 sm:px-3">
        <div className="flex items-center gap-2">
          <span
            className="text-sm text-slate-200 leading-snug break-words"
            title={task.title}
          >
            {task.title}
          </span>
        </div>
        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 sm:hidden">
          <span className="max-w-32 truncate font-mono text-[10px] text-slate-500">
            {task.id}
          </span>
          <span
            className={clsx(
              'rounded border px-1 py-0.5 font-mono text-[10px] font-medium',
              priorityStyle.className,
            )}
          >
            {priorityStyle.label}
          </span>
          <span
            className={clsx('flex items-center gap-1', typeStyle.className)}
          >
            <TypeIcon className="h-3 w-3" />
            <span className="text-[10px]">{typeStyle.label}</span>
          </span>
        </div>
      </td>

      {/* Progress Indicators */}
      <td className="hidden px-3 py-3 xl:table-cell">
        <div className="flex items-center gap-3">
          {/* Criteria Progress */}
          {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
            <CriteriaProgress
              criteria={task.acceptance_criteria}
              maxVisible={4}
            />
          )}
          {/* Subtask Progress */}
          {subtasks.length > 0 && (
            <SubtaskProgress subtasks={subtasks} maxVisible={5} />
          )}
          {/* Enrichment Status Badge for non-accepted tasks */}
          <EnrichmentStatusBadge status={task.enrichment_status} />
        </div>
      </td>

      {/* Status */}
      <td className="px-2 py-3 sm:px-3">
        <span
          className={clsx('flex items-center gap-1.5', statusStyle.className)}
        >
          <StatusIcon className="h-3.5 w-3.5" />
          <span className="text-xs capitalize">{task.status}</span>
        </span>
      </td>

      {/* Updated */}
      <td className="hidden px-3 py-3 lg:table-cell">
        <span className="text-xs text-slate-500">
          {task.updated_at
            ? formatTimeAgo(task.updated_at)
            : task.created_at
              ? formatTimeAgo(task.created_at)
              : '-'}
        </span>
      </td>

      {/* Actions */}
      {onDelete && (
        <td className="px-2 py-3 sm:px-3" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => onDelete(task.id)}
            aria-label={`Delete ${task.title}`}
            className="rounded p-1 text-slate-500 transition-colors hover:bg-red-500/20 hover:text-red-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500/50"
            title="Delete task"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </td>
      )}
    </tr>
  )
}
