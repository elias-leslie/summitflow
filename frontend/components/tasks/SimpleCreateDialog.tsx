'use client'

import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Send, Sparkles, Zap } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  cleanupPrompt,
  enrichTask,
  type Task,
  type TaskType,
} from '@/lib/api/tasks'

interface SimpleCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  onTaskCreated?: (task: Task, mode: 'queue' | 'verify') => void
}

const PRIORITY_OPTIONS = [
  { value: 'auto', label: 'auto' },
  { value: '0', label: 'P0 - Critical' },
  { value: '1', label: 'P1 - High' },
  { value: '2', label: 'P2 - Medium' },
  { value: '3', label: 'P3 - Low' },
  { value: '4', label: 'P4 - Backlog' },
]

const TYPE_OPTIONS = [
  { value: 'auto', label: 'auto' },
  { value: 'feature', label: 'feature' },
  { value: 'bug', label: 'bug' },
  { value: 'task', label: 'task' },
]

export function SimpleCreateDialog({
  open,
  onOpenChange,
  projectId,
  onTaskCreated,
}: SimpleCreateDialogProps) {
  const queryClient = useQueryClient()
  const [rawRequest, setRawRequest] = useState('')
  const [priority, setPriority] = useState('auto')
  const [taskType, setTaskType] = useState('auto')
  const [isCleaningUp, setIsCleaningUp] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState<'queue' | 'verify' | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [cleanupChanges, setCleanupChanges] = useState<string[] | null>(null)

  const resetForm = useCallback(() => {
    setRawRequest('')
    setPriority('auto')
    setTaskType('auto')
    setError(null)
    setCleanupChanges(null)
  }, [])

  const handleClose = useCallback(() => {
    if (!isSubmitting && !isCleaningUp) {
      resetForm()
      onOpenChange(false)
    }
  }, [isSubmitting, isCleaningUp, resetForm, onOpenChange])

  const handleCleanup = async () => {
    if (!rawRequest.trim() || isCleaningUp) return

    setIsCleaningUp(true)
    setError(null)
    setCleanupChanges(null)

    try {
      const result = await cleanupPrompt(projectId, rawRequest)
      setRawRequest(result.cleaned_prompt)
      setCleanupChanges(result.changes_made)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to cleanup prompt')
    } finally {
      setIsCleaningUp(false)
    }
  }

  const handleSubmit = async (mode: 'queue' | 'verify') => {
    if (!rawRequest.trim()) {
      setError('Please describe what you want to do')
      return
    }

    setIsSubmitting(mode)
    setError(null)

    try {
      const task = await enrichTask(
        projectId,
        {
          raw_request: rawRequest.trim(),
          priority: priority !== 'auto' ? parseInt(priority, 10) : undefined,
          task_type: taskType !== 'auto' ? (taskType as TaskType) : undefined,
        },
        mode === 'verify', // sync = true for verify now
      )

      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })

      if (onTaskCreated) {
        onTaskCreated(task, mode)
      }

      resetForm()
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create task')
    } finally {
      setIsSubmitting(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-xl">
        <DialogClose onClose={handleClose} />
        <DialogHeader>
          <DialogTitle className="font-mono tracking-wider text-sm uppercase">
            New Task
          </DialogTitle>
        </DialogHeader>

        <div className="p-5 space-y-5">
          {/* Main Input */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-slate-300">
              What do you want to do?
            </label>
            <div className="relative">
              <textarea
                value={rawRequest}
                onChange={(e) => {
                  setRawRequest(e.target.value)
                  setCleanupChanges(null)
                }}
                placeholder="Describe your task in natural language. The AI will structure it into objective, criteria, and subtasks..."
                rows={5}
                disabled={isSubmitting !== null}
                className="w-full px-4 py-3 pr-12 bg-slate-800/50 border border-slate-700 rounded-lg
                  text-white text-sm leading-relaxed placeholder:text-slate-500
                  focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500 focus:bg-slate-800
                  disabled:opacity-50 disabled:cursor-not-allowed
                  resize-none transition-all duration-200"
              />

              {/* AI Cleanup Button */}
              <button
                type="button"
                onClick={handleCleanup}
                disabled={
                  !rawRequest.trim() || isCleaningUp || isSubmitting !== null
                }
                className="absolute bottom-3 right-3 p-1.5 rounded-md
                  text-slate-500 hover:text-amber-400 hover:bg-amber-500/10
                  disabled:opacity-30 disabled:cursor-not-allowed
                  transition-all duration-200 group"
                title="AI cleanup: fix grammar, clarify intent"
              >
                {isCleaningUp ? (
                  <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
                ) : (
                  <Sparkles className="w-4 h-4 group-hover:animate-pulse" />
                )}
              </button>
            </div>

            {/* Cleanup Changes Feedback */}
            <AnimatePresence>
              {cleanupChanges && cleanupChanges.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="text-xs text-amber-400/80 pl-1"
                >
                  <span className="font-medium">AI refined:</span>{' '}
                  {cleanupChanges.join(', ')}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Optional Priority & Type */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide">
                Priority
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                disabled={isSubmitting !== null}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-md
                  text-sm text-white focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500
                  disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {PRIORITY_OPTIONS.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    className="bg-slate-800"
                  >
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide">
                Type
              </label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                disabled={isSubmitting !== null}
                className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-md
                  text-sm text-white focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500
                  disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {TYPE_OPTIONS.map((opt) => (
                  <option
                    key={opt.value}
                    value={opt.value}
                    className="bg-slate-800"
                  >
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <p className="text-xs text-slate-500 -mt-2">
            Optional - AI will suggest values if left on auto
          </p>

          {/* Error */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="p-3 bg-red-950/50 border border-red-800/50 rounded-md"
              >
                <p className="text-sm text-red-400">{error}</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Action Buttons */}
          <div className="flex gap-3 pt-2">
            <Button
              type="button"
              variant="primary"
              className="flex-1"
              disabled={!rawRequest.trim() || isSubmitting !== null}
              onClick={() => handleSubmit('queue')}
            >
              {isSubmitting === 'queue' ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Submitting...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  Submit to Queue
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="flex-1"
              disabled={!rawRequest.trim() || isSubmitting !== null}
              onClick={() => handleSubmit('verify')}
            >
              {isSubmitting === 'verify' ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Verifying...
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4" />
                  Verify Now
                </>
              )}
            </Button>
          </div>

          <p className="text-xs text-slate-500 text-center">
            <span className="text-phosphor-400">Submit to Queue</span> processes
            in background
            {' · '}
            <span className="text-slate-300">Verify Now</span> shows results
            immediately
          </p>
        </div>
      </DialogContent>
    </Dialog>
  )
}
