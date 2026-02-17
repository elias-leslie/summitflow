import { AlertCircle, ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import type { Task } from '@/lib/api'
import type { Subtask } from '@/lib/api/tasks'
import { cn } from '@/lib/utils'
import { CriteriaProgress } from './CriteriaProgress'
import { EnrichmentStatusBadge } from './EnrichmentStatusBadge'
import { SubtaskProgress } from './SubtaskProgress'
import {
  formatRelativeTime,
  priorityConfig,
  statusIconConfig,
  statusToKanbanLabel,
  typeConfig,
} from '@/lib/task-config'

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
  const phaseStyle =
    statusToKanbanLabel[task.status] || statusToKanbanLabel.pending

  const TypeIcon = typeStyle.icon
  const StatusIcon = statusStyle.icon

  return (
    <tr
      className={cn(
        'border-b border-slate-800 hover:bg-slate-800/30 transition-colors',
        isExpanded && 'bg-slate-800/50',
        isSelected && 'bg-blue-500/10',
      )}
    >
      {/* Checkbox */}
      {onToggleSelect && (
        <td className="w-8 px-2 py-3" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => onToggleSelect(task.id)}
            className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
          />
        </td>
      )}

      {/* Expand */}
      <td className="w-8 px-2 py-3 cursor-pointer" onClick={onToggle}>
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-500" />
        )}
      </td>

      {/* Priority */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityStyle.className}`}
        >
          {priorityStyle.label}
        </span>
      </td>

      {/* Type */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <span className={`flex items-center gap-1.5 ${typeStyle.className}`}>
          <TypeIcon className="h-3.5 w-3.5" />
          <span className="text-xs">{typeStyle.label}</span>
        </span>
      </td>

      {/* ID */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <span className="text-xs mono text-slate-500">{task.id}</span>
      </td>

      {/* Title + Warning */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-200 line-clamp-1">
            {task.title}
          </span>
          {!task.objective && task.enrichment_status !== 'enriching' && (
            <span title="No objective set">
              <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
            </span>
          )}
        </div>
      </td>

      {/* Phase Badge */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <span
          className={`text-2xs px-1.5 py-0.5 rounded font-medium ${phaseStyle.className}`}
        >
          {phaseStyle.label}
        </span>
      </td>

      {/* Progress Indicators */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
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
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <span className={`flex items-center gap-1.5 ${statusStyle.className}`}>
          <StatusIcon className="h-3.5 w-3.5" />
          <span className="text-xs capitalize">{task.status}</span>
        </span>
      </td>

      {/* Created */}
      <td className="px-3 py-3 cursor-pointer" onClick={onToggle}>
        <span className="text-xs text-slate-500">
          {task.created_at ? formatRelativeTime(task.created_at) : '-'}
        </span>
      </td>

      {/* Actions */}
      {onDelete && (
        <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={() => onDelete(task.id)}
            className="p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400 transition-colors"
            title="Delete task"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </td>
      )}
    </tr>
  )
}
