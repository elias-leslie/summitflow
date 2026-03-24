import clsx from 'clsx'
import type { Task } from '@/lib/api'
import {
  getPriorityClasses,
  getTaskStatusCardConfig,
  getTaskTypeConfigSmall,
} from '@/lib/task-config'

interface TaskCardHeaderProps {
  task: Task
}

export function TaskCardHeader({ task }: TaskCardHeaderProps) {
  const typeConfig = getTaskTypeConfigSmall(task.task_type)
  const statusConfig = getTaskStatusCardConfig(task.status)

  return (
    <div className="flex items-center justify-between gap-2 mb-1">
      <div className="flex items-center gap-2">
        <span className={typeConfig.className} title={task.task_type}>
          {typeConfig.icon}
        </span>
        <span className="text-xs mono text-slate-500">{task.id}</span>
        <span
          className={clsx('text-xs px-1.5 py-0.5 rounded border mono font-medium', getPriorityClasses(task.priority))}
        >
          P{task.priority}
        </span>
        {task.status === 'running' && statusConfig?.icon && (
          <span
            className={clsx('flex items-center', statusConfig.className)}
            title={statusConfig.title}
          >
            {statusConfig.icon}
          </span>
        )}
      </div>
    </div>
  )
}
