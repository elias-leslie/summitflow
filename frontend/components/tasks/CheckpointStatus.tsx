'use client'

import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'motion/react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Database,
  GitBranch,
  Loader2,
  User,
} from 'lucide-react'
import { useState } from 'react'
import { getCheckpoint, type Checkpoint } from '@/lib/api/checkpoints'

interface CheckpointStatusProps {
  taskId: string
  projectId: string
  taskStatus: string
}

export function CheckpointStatus({
  taskId,
  projectId,
  taskStatus,
}: CheckpointStatusProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  const { data: checkpoint, isLoading } = useQuery({
    queryKey: ['checkpoint', taskId, projectId],
    queryFn: () => getCheckpoint(taskId, projectId),
    enabled: taskStatus === 'running',
    staleTime: 30000,
  })

  // Only show when task is running and has a checkpoint
  if (taskStatus !== 'running') return null
  if (isLoading) {
    return (
      <div className="p-4 bg-cyan-950/20 border border-cyan-800/30 rounded-lg">
        <div className="flex items-center gap-2 text-cyan-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Checking for checkpoint...</span>
        </div>
      </div>
    )
  }
  if (!checkpoint) return null

  const activeBranches = checkpoint.branches.filter((b) => b.type === 'subtask')
  const taskBranch = checkpoint.branches.find((b) => b.type === 'task')

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-4 bg-cyan-950/20 border border-cyan-800/30 rounded-lg"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded bg-cyan-900/50">
            <Database className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <h4 className="text-sm font-medium text-cyan-300">
              Checkpoint Active
            </h4>
            <p className="text-xs text-slate-500">
              {checkpoint.age} by {checkpoint.claimed_by}
            </p>
          </div>
        </div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-300 transition-colors"
        >
          {isExpanded ? (
            <>
              Hide <ChevronDown className="w-3 h-3" />
            </>
          ) : (
            <>
              Details <ChevronRight className="w-3 h-3" />
            </>
          )}
        </button>
      </div>

      {/* Summary row */}
      <div className="mt-3 flex items-center gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1">
          <Database className="w-3 h-3" />
          {checkpoint.size}
        </span>
        <span className="flex items-center gap-1">
          <GitBranch className="w-3 h-3" />
          {checkpoint.branches.length} branch
          {checkpoint.branches.length !== 1 ? 'es' : ''}
        </span>
        <span className="flex items-center gap-1">
          <User className="w-3 h-3" />
          {checkpoint.claimed_by}
        </span>
      </div>

      {/* Expanded details */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mt-4 pt-4 border-t border-cyan-800/30 overflow-hidden"
          >
            <div className="space-y-3">
              {/* Base branch */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Base branch</span>
                <span className="text-xs font-mono text-slate-300">
                  {checkpoint.base_branch}
                </span>
              </div>

              {/* Task branch */}
              {taskBranch && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Task branch</span>
                  <span className="text-xs font-mono text-cyan-400">
                    {taskBranch.branch}
                  </span>
                </div>
              )}

              {/* Active subtask branches */}
              {activeBranches.length > 0 && (
                <div>
                  <span className="text-xs text-slate-500">
                    Subtask branches ({activeBranches.length})
                  </span>
                  <div className="mt-1 space-y-1">
                    {activeBranches.map((branch) => (
                      <div
                        key={branch.branch}
                        className="flex items-center gap-2 text-xs"
                      >
                        <span className="w-2 h-2 rounded-full bg-green-500" />
                        <span className="font-mono text-slate-300">
                          {branch.subtask_id}
                        </span>
                        <span className="text-slate-600">→</span>
                        <span className="font-mono text-slate-500 truncate">
                          {branch.branch}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Snapshot info */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Snapshot</span>
                <span className="text-xs text-slate-300">
                  {checkpoint.size}
                </span>
              </div>

              {/* Warning */}
              <div className="flex items-start gap-2 p-2 bg-amber-950/30 border border-amber-800/30 rounded">
                <AlertTriangle className="w-3 h-3 text-amber-500 mt-0.5 flex-shrink-0" />
                <p className="text-xs text-amber-400">
                  If the task fails, use <code className="font-mono">st abandon</code> to
                  rollback DB and discard branches.
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
