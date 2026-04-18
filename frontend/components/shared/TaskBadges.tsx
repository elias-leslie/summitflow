import clsx from 'clsx'
import type { Task } from '@/lib/api/tasks'
import { getPriorityColors, getTaskTypeConfig } from '@/lib/task-config'

interface TaskBadgesProps {
  task: Task
  children?: React.ReactNode
}

export function TaskBadges({ task, children }: TaskBadgesProps) {
  const colors = getPriorityColors(task.priority)
  const typeConfig = getTaskTypeConfig(task.task_type)

  return (
    <div className="flex items-center gap-2 mb-2 flex-wrap">
      <span className="mono text-sm text-slate-500">{task.id}</span>
      <span
        className={clsx(
          'text-xs px-1.5 py-0.5 rounded border mono font-medium',
          colors.bg,
          colors.text,
          colors.border,
        )}
      >
        P{task.priority}
      </span>
      <span
        className={clsx(
          'text-xs px-1.5 py-0.5 rounded border flex items-center gap-1',
          typeConfig.className,
        )}
      >
        {typeConfig.icon}
        {typeConfig.label}
      </span>
      {children}
    </div>
  )
}
