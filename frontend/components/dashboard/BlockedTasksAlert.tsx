'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Clock, Play } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { fetchBlockedTasks, updateTaskStatus, type Task } from '@/lib/api'
import { taskQueryKeys } from '@/lib/task-cache'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

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
  const { syncUpdatedTask } = useTaskMutationSync(projectId)
  const [retryingTaskId, setRetryingTaskId] = useState<string | null>(null)
  const { data, refetch, isLoading, isError, error } = useQuery({
    queryKey: taskQueryKeys.blocked(projectId),
    queryFn: () => fetchBlockedTasks(projectId, 20),
    staleTime: 30000,
  })

  if (isLoading) {
    return (
      <div className="card border-orange-500/20 bg-orange-950/5 px-4 py-3 text-sm text-slate-400">
        Loading blocked tasks...
      </div>
    )
  }

  if (isError) {
    return (
      <div className="card border-rose-500/30 bg-rose-950/10 px-4 py-3">
        <div className="text-sm font-medium text-rose-300">Blocked task status unavailable</div>
        <div className="mt-1 text-xs text-slate-400">
          {getErrorMessage(error, 'Failed to load blocked tasks')}
        </div>
        <button
          onClick={() => refetch()}
          className="mt-2 text-xs text-rose-300 hover:text-rose-200"
        >
          Retry
        </button>
      </div>
    )
  }

  const tasks = data?.tasks ?? []
  if (tasks.length === 0) return null

  const sorted = [...tasks].sort((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : Date.now()
    const bTime = b.created_at ? new Date(b.created_at).getTime() : Date.now()
    return aTime - bTime
  })

  const handleUnblock = async (task: Task) => {
    setRetryingTaskId(task.id)
    try {
      const updated = await updateTaskStatus(projectId, task.id, 'queue')
      syncUpdatedTask(updated)
      refetch()
      toast.success('Task re-queued')
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to re-queue task'))
    } finally {
      setRetryingTaskId(null)
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
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onTaskClick?.(task.id)
              }
            }}
            role="button"
            tabIndex={0}
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm text-white truncate">{task.title}</div>
              <div
                className="text-xs text-slate-500 truncate"
                title={task.error_message ?? 'Blocked'}
              >
                {task.error_message?.slice(0, 80) || 'Blocked'}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span
                className="text-[10px] text-slate-500 flex items-center gap-1"
                title={task.created_at ?? undefined}
              >
                <Clock className="w-3 h-3" />
                {timeAgo(task.created_at)}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleUnblock(task)
                }}
                disabled={retryingTaskId === task.id}
                className="p-1 rounded text-slate-500 hover:text-phosphor-400 hover:bg-slate-800 transition-colors"
                title="Re-queue task"
                aria-label={`Re-queue ${task.title}`}
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
