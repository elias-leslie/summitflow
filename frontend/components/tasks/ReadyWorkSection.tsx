/**
 * Ready Work Section - Displays unblocked tasks ready for work
 */

import { ListTodo, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { Task } from '@/lib/api'
import { cn } from '@/lib/utils'
import { priorityConfig, typeIcons } from '@/lib/task-config'

interface ReadyWorkSectionProps {
  tasks: Task[]
  onTaskClick: (taskId: string) => void
}

export function ReadyWorkSection({
  tasks,
  onTaskClick,
}: ReadyWorkSectionProps) {
  if (tasks.length === 0) {
    return null
  }

  return (
    <div className="card">
      <div className="p-4 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <Zap className="w-5 h-5 text-phosphor-400" />
          <h3 className="font-medium text-white">Ready for Work</h3>
          <Badge variant="outline" className="ml-auto">
            {tasks.length}
          </Badge>
        </div>
      </div>
      <div className="divide-y divide-slate-700/50">
        {tasks.slice(0, 5).map((task) => {
          const priority = priorityConfig[task.priority] || priorityConfig[2]
          const TypeIcon = typeIcons[task.task_type] || ListTodo
          return (
            <div
              key={task.id}
              className="p-3 flex items-center gap-3 hover:bg-slate-800/30 cursor-pointer"
              onClick={() => onTaskClick(task.id)}
            >
              <span
                className={cn('text-xs font-mono font-bold', priority.color)}
              >
                {priority.label}
              </span>
              <TypeIcon className="w-4 h-4 text-slate-400" />
              <span className="text-sm text-slate-200 flex-1">
                {task.title}
              </span>
              <code className="text-xs text-slate-500">{task.id}</code>
            </div>
          )
        })}
      </div>
    </div>
  )
}
