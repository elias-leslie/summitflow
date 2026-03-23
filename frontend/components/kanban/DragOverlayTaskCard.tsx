import type { Task } from '@/lib/api'
import {
  getPriorityClasses,
  getTaskTypeConfigSmall,
} from '@/lib/task-config'

interface DragOverlayTaskCardProps {
  task: Task
}

export function DragOverlayTaskCard({ task }: DragOverlayTaskCardProps) {
  const typeConfig = getTaskTypeConfigSmall(task.task_type)

  return (
    <div className="rounded-lg border border-phosphor-500 bg-slate-900 p-3 shadow-xl shadow-phosphor-500/20 rotate-2 max-w-[300px]">
      <div className="flex items-center gap-2 mb-1">
        <span className={typeConfig.className}>{typeConfig.icon}</span>
        <span className="text-xs mono text-slate-500">{task.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${getPriorityClasses(task.priority)}`}
        >
          P{task.priority}
        </span>
      </div>
      <h4 className="text-sm font-medium text-slate-100 line-clamp-2">
        {task.title}
      </h4>
    </div>
  )
}
