import { AlertCircle, Loader2 } from 'lucide-react'
import type { Notification, Task } from '@/lib/api'

interface TaskDetailsPanelProps {
  loading: boolean
  taskDetails: Task | null
  notification: Notification
}

export function TaskDetailsPanel({
  loading,
  taskDetails,
  notification,
}: TaskDetailsPanelProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    )
  }

  if (!taskDetails) {
    return (
      <div className="text-center text-slate-500 py-8">
        <AlertCircle className="w-8 h-8 mx-auto mb-2 text-slate-600" />
        <p className="text-sm">{notification.message}</p>
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm">
      <div>
        <span className="text-slate-500">Task:</span>
        <span className="ml-2 text-slate-300">
          {taskDetails.title || 'Unknown'}
        </span>
      </div>
      <div>
        <span className="text-slate-500">Status:</span>
        <span className="ml-2 text-rose-400">
          {taskDetails.status || 'unknown'}
        </span>
      </div>
      {taskDetails.error_message && (
        <div>
          <span className="text-slate-500 block mb-1">Error:</span>
          <pre className="p-2 bg-rose-950/30 border border-rose-900/50 rounded text-xs text-rose-300 overflow-auto">
            {taskDetails.error_message}
          </pre>
        </div>
      )}
      {taskDetails.progress_log && (
        <div>
          <span className="text-slate-500 block mb-1">Recent Log:</span>
          <pre className="p-2 bg-slate-800/50 border border-slate-700 rounded text-xs text-slate-400 overflow-auto max-h-24">
            {(taskDetails.progress_log || '').split('\n').slice(-5).join('\n')}
          </pre>
        </div>
      )}
    </div>
  )
}
