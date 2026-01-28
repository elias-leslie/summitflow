'use client'

import {
  ChevronDown,
  ChevronUp,
  Loader2,
  Minimize2,
  Maximize2,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Task } from '@/lib/api'
import { ExecutionTimeline } from '@/components/tasks/ExecutionTimeline'

interface RunningTaskInfo {
  task: Task
  currentStep?: string
  lastLog?: string
}

interface BottomExecutionDockProps {
  runningTasks: RunningTaskInfo[]
  onClose?: (taskId: string) => void
}

function AccordionItem({
  task,
  currentStep,
  lastLog,
  isExpanded,
  onToggle,
  onClose: _onClose,
}: RunningTaskInfo & {
  isExpanded: boolean
  onToggle: () => void
  onClose?: () => void
}) {
  return (
    <div className="border-b border-slate-700/50 last:border-b-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/50 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <Loader2 className="h-4 w-4 animate-spin text-phosphor-400 shrink-0" />
          <span className="text-sm font-medium text-white truncate">
            {task.title}
          </span>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {currentStep && (
            <span className="text-xs text-slate-400 truncate max-w-[200px]">
              {currentStep}
            </span>
          )}
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          )}
        </div>
      </button>

      {!isExpanded && lastLog && (
        <div className="px-4 pb-2">
          <p className="text-xs text-slate-500 truncate mono">{lastLog}</p>
        </div>
      )}

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4">
              <ExecutionTimeline
                taskId={task.id}
                projectId={task.project_id}
                autoConnect
                showChatInput
                chatEnabled={task.status === 'running'}
                className="h-[300px]"
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function BottomExecutionDock({
  runningTasks,
  onClose,
}: BottomExecutionDockProps) {
  const [isMinimized, setIsMinimized] = useState(false)
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(
    runningTasks[0]?.task.id || null
  )

  if (runningTasks.length === 0) {
    return null
  }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 pointer-events-none">
      <div className="max-w-6xl mx-auto px-4">
        <motion.div
          initial={{ y: 100, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 100, opacity: 0 }}
          className="bg-slate-900 border border-slate-700 rounded-t-lg shadow-2xl pointer-events-auto"
        >
          <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-phosphor-400" />
              <span className="text-sm font-medium text-white">
                {runningTasks.length} task{runningTasks.length > 1 ? 's' : ''}{' '}
                running
              </span>
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={() => setIsMinimized(!isMinimized)}
                className="p-1.5 rounded hover:bg-slate-800 transition-colors"
                title={isMinimized ? 'Expand' : 'Minimize'}
              >
                {isMinimized ? (
                  <Maximize2 className="h-4 w-4 text-slate-400" />
                ) : (
                  <Minimize2 className="h-4 w-4 text-slate-400" />
                )}
              </button>
            </div>
          </div>

          <AnimatePresence>
            {!isMinimized && (
              <motion.div
                initial={{ height: 0 }}
                animate={{ height: 'auto' }}
                exit={{ height: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden max-h-[500px] overflow-y-auto"
              >
                {runningTasks.map((taskInfo) => (
                  <AccordionItem
                    key={taskInfo.task.id}
                    {...taskInfo}
                    isExpanded={expandedTaskId === taskInfo.task.id}
                    onToggle={() =>
                      setExpandedTaskId(
                        expandedTaskId === taskInfo.task.id
                          ? null
                          : taskInfo.task.id
                      )
                    }
                    onClose={
                      onClose ? () => onClose(taskInfo.task.id) : undefined
                    }
                  />
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>
    </div>
  )
}
