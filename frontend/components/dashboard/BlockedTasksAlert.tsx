'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Clock, Play } from 'lucide-react'
import { fetchBlockedTasks, updateTaskStatus, type Task } from '@/lib/api'

interface BlockedTasksAlertProps {
  projectId: string
  onTaskClick?: (taskId: string) => void
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return '<1h'
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

export function BlockedTasksAlert({
  projectId,
  onTaskClick,
}: BlockedTasksAlertProps) {
  const { data, refetch } = useQuery({
    queryKey: ['tasks', projectId, 'blocked'],
    queryFn: () => fetchBlockedTasks(projectId, 20),
    staleTime: 30000,
  })

  const tasks = data?.tasks ?? []
  if (tasks.length === 0) return null

  const sorted = [...tasks].sort((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : Date.now()
    const bTime = b.created_at ? new Date(b.created_at).getTime() : Date.now()
    return aTime - bTime
  })

  const handleUnblock = async (task: Task) => {
    try {
      await updateTaskStatus(projectId, task.id, 'queue')
      refetch()
    } catch {
      // Silently fail - user can retry
    }
  }

  return (
    <div className="card border-orange-500/30 bg-orange-950/10">
      <div className="px-4 py-3 border-b border-orange-500/20 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-orange-400" />
        <span className="text-sm font-medium text-orange-400">
          {tasks.length} Blocked Task{tasks.length > 1 ? 's' : ''}
        </span>
      </div>
      <div className="divide-y divide-slate-800">
        {sorted.slice(0, 5).map((task) => (
          <div
            key={task.id}
            className="px-4 py-2.5 flex items-center gap-3 hover:bg-slate-800/30 cursor-pointer"
            onClick={() => onTaskClick?.(task.id)}
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm text-white truncate">{task.title}</div>
              <div className="text-xs text-slate-500 truncate">
                {task.error_message?.slice(0, 80) || 'Blocked'}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-[10px] text-slate-500 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {timeAgo(task.created_at)}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleUnblock(task)
                }}
                className="p-1 rounded text-slate-500 hover:text-phosphor-400 hover:bg-slate-800 transition-colors"
                title="Re-queue task"
              >
                <Play className="w-3 h-3" />
              </button>
            </div>
          </div>
        ))}
        {tasks.length > 5 && (
          <div className="px-4 py-2 text-xs text-slate-500 text-center">
            +{tasks.length - 5} more blocked
          </div>
        )}
      </div>
    </div>
  )
}
