'use client'

import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Pause,
  Play,
  Trash2,
  XCircle,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import type { Task, TaskStatus } from '@/lib/api/tasks'

export type TaskAction =
  | 'execute'
  | 'pause'
  | 'resume'
  | 'complete'
  | 'cancel'
  | 'delete'

interface ActionsSectionProps {
  task: Task
  onAction: (action: TaskAction) => Promise<void>
}

export function ActionsSection({ task, onAction }: ActionsSectionProps) {
  const [loadingAction, setLoadingAction] = useState<TaskAction | null>(null)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const handleAction = async (action: TaskAction) => {
    if (action === 'delete' && !showDeleteConfirm) {
      setShowDeleteConfirm(true)
      return
    }

    setLoadingAction(action)
    try {
      await onAction(action)
      setShowDeleteConfirm(false)
    } finally {
      setLoadingAction(null)
    }
  }

  const isLoading = loadingAction !== null
  const status = task.status as TaskStatus

  // Determine which actions are available based on status
  const canExecute = status === 'pending' || status === 'paused'
  const canPause = status === 'running'
  const canComplete = status === 'running' || status === 'paused'
  const canCancel =
    status === 'pending' || status === 'running' || status === 'paused'

  return (
    <section>
      <div className="flex items-center flex-wrap gap-2">
        {/* Execute/Resume */}
        {canExecute && (
          <Button
            variant="primary"
            size="sm"
            onClick={() =>
              handleAction(status === 'paused' ? 'resume' : 'execute')
            }
            disabled={isLoading}
          >
            {loadingAction === 'execute' || loadingAction === 'resume' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            <span className="ml-1.5">
              {status === 'paused' ? 'Resume' : 'Execute'}
            </span>
          </Button>
        )}

        {/* Pause */}
        {canPause && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleAction('pause')}
            disabled={isLoading}
          >
            {loadingAction === 'pause' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Pause className="w-4 h-4" />
            )}
            <span className="ml-1.5">Pause</span>
          </Button>
        )}

        {/* Complete */}
        {canComplete && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleAction('complete')}
            disabled={isLoading}
            className="text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/10 hover:border-emerald-500/50"
          >
            {loadingAction === 'complete' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <CheckCircle2 className="w-4 h-4" />
            )}
            <span className="ml-1.5">Complete</span>
          </Button>
        )}

        {/* Cancel */}
        {canCancel && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleAction('cancel')}
            disabled={isLoading}
            className="text-amber-400 hover:bg-amber-500/10"
          >
            {loadingAction === 'cancel' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <XCircle className="w-4 h-4" />
            )}
            <span className="ml-1.5">Cancel</span>
          </Button>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Delete */}
        <AnimatePresence mode="wait">
          {showDeleteConfirm ? (
            <motion.div
              key="confirm"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="flex items-center gap-2 px-3 py-1.5 bg-red-950/50 border border-red-800/50 rounded-lg"
            >
              <AlertTriangle className="w-4 h-4 text-red-400" />
              <span className="text-xs text-red-400">Delete task?</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowDeleteConfirm(false)}
                disabled={isLoading}
                className="h-6 px-2 text-xs"
              >
                No
              </Button>
              <Button
                size="sm"
                onClick={() => handleAction('delete')}
                disabled={isLoading}
                className="h-6 px-2 text-xs bg-red-600 hover:bg-red-700 text-white"
              >
                {loadingAction === 'delete' ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  'Yes, delete'
                )}
              </Button>
            </motion.div>
          ) : (
            <motion.div
              key="button"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
            >
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleAction('delete')}
                disabled={isLoading}
                className="text-red-400 hover:bg-red-500/10"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Status-specific messages */}
      {status === 'completed' && (
        <p className="mt-3 text-xs text-slate-500">
          Task completed
          {task.completed_at &&
            ` on ${new Date(task.completed_at).toLocaleDateString()}`}
        </p>
      )}
      {status === 'failed' && task.error_message && (
        <div className="mt-3 p-2 bg-red-950/30 border border-red-800/30 rounded text-xs text-red-400">
          {task.error_message}
        </div>
      )}
    </section>
  )
}
