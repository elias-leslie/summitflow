/**
 * Task Row Component - Displays a single task row with expand/collapse
 */

'use client'

import { ChevronDown, ChevronRight, ListTodo, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Task, TaskStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import { ExecutionTimeline } from './ExecutionTimeline'
import {
  formatDate,
  priorityConfig,
  statusConfig,
  typeIcons,
} from './taskConfig'

interface TaskRowProps {
  task: Task
  isExpanded: boolean
  onToggle: () => void
  onStatusChange: (status: TaskStatus) => void
  isUpdating: boolean
  projectId: string
}

export function TaskRow({
  task,
  isExpanded,
  onToggle,
  onStatusChange,
  isUpdating,
  projectId,
}: TaskRowProps) {
  const priority = priorityConfig[task.priority] || priorityConfig[2]
  const status = statusConfig[task.status] || statusConfig.pending
  const TypeIcon = typeIcons[task.task_type] || ListTodo
  const StatusIcon = status.icon

  return (
    <>
      <tr
        className={cn(
          'border-b border-slate-700/50 hover:bg-slate-800/50 cursor-pointer transition-colors',
          isExpanded && 'bg-slate-800/30',
        )}
        onClick={onToggle}
      >
        {/* Expand */}
        <td className="w-8 px-2 py-2">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </td>

        {/* Priority */}
        <td className="w-12 px-2 py-2">
          <span className={cn('text-xs font-mono font-bold', priority.color)}>
            {priority.label}
          </span>
        </td>

        {/* Type */}
        <td className="w-10 px-2 py-2">
          <TypeIcon className="w-4 h-4 text-slate-400" />
        </td>

        {/* ID */}
        <td className="w-28 px-2 py-2">
          <code className="text-xs text-slate-500">{task.id}</code>
        </td>

        {/* Title */}
        <td className="px-2 py-2">
          <span className="text-sm text-slate-200">{task.title}</span>
          {task.labels && task.labels.length > 0 && (
            <div className="flex gap-1 mt-1 flex-wrap">
              {task.labels.slice(0, 3).map((label) => (
                <Badge
                  key={label}
                  variant="outline"
                  className="text-xs py-0 h-5"
                >
                  {label}
                </Badge>
              ))}
              {task.labels.length > 3 && (
                <Badge variant="outline" className="text-xs py-0 h-5">
                  +{task.labels.length - 3}
                </Badge>
              )}
            </div>
          )}
        </td>

        {/* Status */}
        <td className="w-28 px-2 py-2">
          <div
            className={cn('flex items-center gap-1 text-xs', status.className)}
          >
            <StatusIcon
              className={cn(
                'w-3 h-3',
                task.status === 'running' && 'animate-spin',
              )}
            />
            {status.label}
          </div>
        </td>

        {/* Date */}
        <td className="w-24 px-2 py-2 text-xs text-slate-500">
          {formatDate(task.created_at)}
        </td>
      </tr>

      {/* Expanded Details */}
      {isExpanded && (
        <tr className="bg-slate-800/20">
          <td colSpan={7} className="px-4 py-3">
            <div className="space-y-3">
              {/* Description */}
              {task.description && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">
                    Description
                  </h4>
                  <p className="text-sm text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {task.description}
                  </p>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 pt-2 border-t border-slate-700">
                {task.status === 'pending' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onStatusChange('running')
                    }}
                    disabled={isUpdating}
                  >
                    {isUpdating ? (
                      <Loader2 className="w-3 h-3 animate-spin mr-1" />
                    ) : null}
                    Start
                  </Button>
                )}
                {task.status === 'running' && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation()
                        onStatusChange('paused')
                      }}
                      disabled={isUpdating}
                    >
                      Pause
                    </Button>
                    <Button
                      size="sm"
                      className="bg-green-600 hover:bg-green-700"
                      onClick={(e) => {
                        e.stopPropagation()
                        onStatusChange('completed')
                      }}
                      disabled={isUpdating}
                    >
                      {isUpdating ? (
                        <Loader2 className="w-3 h-3 animate-spin mr-1" />
                      ) : null}
                      Complete
                    </Button>
                  </>
                )}
                {task.status === 'paused' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onStatusChange('running')
                    }}
                    disabled={isUpdating}
                  >
                    Resume
                  </Button>
                )}
                {task.status === 'completed' && (
                  <span className="text-xs text-green-500">Completed</span>
                )}
                {task.status === 'failed' && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      onStatusChange('pending')
                    }}
                    disabled={isUpdating}
                  >
                    Retry
                  </Button>
                )}
              </div>

              {/* Execution Timeline for running/paused tasks */}
              {(task.status === 'running' || task.status === 'paused') && (
                <div
                  className="pt-3 border-t border-slate-700"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExecutionTimeline
                    taskId={task.id}
                    projectId={projectId}
                    className="max-h-[400px]"
                  />
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
