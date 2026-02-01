'use client'

import { useEffect, useState } from 'react'
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  Edit2,
  FastForward,
  Loader2,
  Play,
  Save,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { CodingAgent, Task, TaskStatus } from '@/lib/api/tasks'
import { fetchCodingAgents } from '@/lib/api/tasks'

interface TaskModalActionsProps {
  task: Task
  isExecuting: boolean
  isStopping: boolean
  isTogglingAutonomous: boolean
  isEditing: boolean
  onStartExecution: () => void
  onStopExecution: () => void
  onStatusChange: (status: TaskStatus) => void
  onToggleAutonomous: () => void
  onAgentOverrideChange?: (agentSlug: string | null) => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onDelete?: () => void
}

// Map task_type to default agent slug (mirrors backend TASK_TYPE_AGENT_MAP)
const TASK_TYPE_AGENT_MAP: Record<string, string> = {
  refactor: 'refactor',
}
const DEFAULT_AGENT = 'coder'

function getDefaultAgentForTask(taskType: string): string {
  return TASK_TYPE_AGENT_MAP[taskType] || DEFAULT_AGENT
}

export function TaskModalActions({
  task,
  isExecuting,
  isStopping,
  isTogglingAutonomous,
  isEditing,
  onStartExecution,
  onStopExecution,
  onStatusChange,
  onToggleAutonomous,
  onAgentOverrideChange,
  onEditStart,
  onEditCancel,
  onEditSave,
  onDelete,
}: TaskModalActionsProps) {
  const [codingAgents, setCodingAgents] = useState<CodingAgent[]>([])
  const [isLoadingAgents, setIsLoadingAgents] = useState(false)
  const [isAgentDropdownOpen, setIsAgentDropdownOpen] = useState(false)

  // Fetch coding agents when autonomous is enabled
  useEffect(() => {
    if (task.autonomous && codingAgents.length === 0) {
      setIsLoadingAgents(true)
      fetchCodingAgents()
        .then((data) => setCodingAgents(data.agents))
        .catch(() => setCodingAgents([]))
        .finally(() => setIsLoadingAgents(false))
    }
  }, [task.autonomous, codingAgents.length])

  const isRunning = task.status === 'running'
  const isPaused = task.status === 'paused'
  const isCompleted = task.status === 'completed'
  const isPending = task.status === 'pending'
  const isHumanReview = task.status === 'human_review'
  const isAiReviewing = task.status === 'ai_reviewing'

  // Resolve which agent will be used
  const resolvedAgent = task.agent_override || getDefaultAgentForTask(task.task_type)
  const currentAgentName =
    codingAgents.find((a) => a.slug === resolvedAgent)?.name || resolvedAgent

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {isPending && (
        <Button
          variant="outline"
          className="gap-2"
          onClick={onStartExecution}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {isExecuting ? 'Starting...' : 'Start Execution'}
        </Button>
      )}
      {isPaused && (
        <Button
          variant="outline"
          className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
          onClick={onStartExecution}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FastForward className="h-4 w-4" />
          )}
          {isExecuting ? 'Resuming...' : 'Continue'}
        </Button>
      )}
      {isRunning && (
        <>
          <Button
            variant="outline"
            className="gap-2 border-blue-500/30 text-blue-400"
            disabled
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Executing...
          </Button>
          <Button
            variant="outline"
            className="gap-2 border-red-500/30 text-red-400 hover:bg-red-500/10"
            onClick={onStopExecution}
            disabled={isStopping}
          >
            <Square className="h-4 w-4" />
            {isStopping ? 'Stopping at next checkpoint...' : 'Stop'}
          </Button>
        </>
      )}
      {isHumanReview && (
        <>
          <Button
            variant="outline"
            className="gap-2 border-phosphor-500/30 text-phosphor-400 hover:bg-phosphor-500/10"
            onClick={() => onStatusChange('running')}
          >
            <CheckCircle2 className="h-4 w-4" />
            Approve
          </Button>
          <Button
            variant="outline"
            className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            onClick={() => onStatusChange('pending')}
          >
            <Edit2 className="h-4 w-4" />
            Request Changes
          </Button>
        </>
      )}
      {isCompleted && (
        <Button
          variant="outline"
          className="gap-2 border-phosphor-500/30 text-phosphor-400"
          disabled
        >
          <CheckCircle2 className="h-4 w-4" />
          Completed
        </Button>
      )}
      {isAiReviewing && (
        <Button
          variant="outline"
          className="gap-2 border-cyan-500/30 text-cyan-400"
          disabled
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          AI Reviewing...
        </Button>
      )}
      {/* Autonomous Toggle */}
      <Button
        variant="outline"
        className={`gap-2 ${
          task.autonomous
            ? 'border-purple-500/30 text-purple-400 bg-purple-500/10'
            : 'border-slate-600 text-slate-400'
        }`}
        onClick={onToggleAutonomous}
        disabled={isTogglingAutonomous || isRunning}
        title={
          task.autonomous
            ? 'Autonomous execution enabled - task will be picked up by auto-exec when enabled'
            : 'Click to enable autonomous execution for this task'
        }
      >
        {isTogglingAutonomous ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Bot className="h-4 w-4" />
        )}
        {task.autonomous ? 'Autonomous' : 'Manual'}
      </Button>

      {/* Coding Agent Selector - only show when autonomous is enabled */}
      {task.autonomous && onAgentOverrideChange && (
        <div className="relative">
          <Button
            variant="outline"
            className={`gap-2 min-w-[140px] justify-between ${
              task.agent_override
                ? 'border-cyan-500/30 text-cyan-400'
                : 'border-slate-600 text-slate-400'
            }`}
            onClick={() => setIsAgentDropdownOpen(!isAgentDropdownOpen)}
            disabled={isRunning || isLoadingAgents}
            title="Select which agent executes this task"
          >
            {isLoadingAgents ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <span className="truncate">
                  {currentAgentName}
                  {!task.agent_override && (
                    <span className="text-slate-500 ml-1">(auto)</span>
                  )}
                </span>
                <ChevronDown className="h-4 w-4 shrink-0" />
              </>
            )}
          </Button>

          {isAgentDropdownOpen && (
            <>
              {/* Backdrop to close dropdown */}
              <div
                className="fixed inset-0 z-40"
                onClick={() => setIsAgentDropdownOpen(false)}
              />
              {/* Dropdown menu */}
              <div className="absolute top-full left-0 mt-1 z-50 min-w-[180px] bg-slate-800 border border-slate-700 rounded-md shadow-lg py-1">
                {/* Auto option */}
                <button
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-700 flex items-center justify-between ${
                    !task.agent_override ? 'text-cyan-400' : 'text-slate-300'
                  }`}
                  onClick={() => {
                    onAgentOverrideChange(null)
                    setIsAgentDropdownOpen(false)
                  }}
                >
                  <span>Auto</span>
                  <span className="text-slate-500 text-xs">
                    ({getDefaultAgentForTask(task.task_type)})
                  </span>
                </button>

                <div className="border-t border-slate-700 my-1" />

                {/* Agent options */}
                {codingAgents.map((agent) => (
                  <button
                    key={agent.slug}
                    className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-700 ${
                      task.agent_override === agent.slug
                        ? 'text-cyan-400'
                        : 'text-slate-300'
                    }`}
                    onClick={() => {
                      onAgentOverrideChange(agent.slug)
                      setIsAgentDropdownOpen(false)
                    }}
                  >
                    <div className="font-medium">{agent.name}</div>
                    {agent.description && (
                      <div className="text-xs text-slate-500 truncate">
                        {agent.description}
                      </div>
                    )}
                  </button>
                ))}

                {codingAgents.length === 0 && !isLoadingAgents && (
                  <div className="px-3 py-2 text-sm text-slate-500">
                    No coding agents available
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
      <div className="ml-auto flex items-center gap-2">
        {isEditing ? (
          <>
            <Button variant="outline" size="sm" onClick={onEditCancel}>
              <X className="h-4 w-4" />
            </Button>
            <Button variant="primary" size="sm" onClick={onEditSave}>
              <Save className="h-4 w-4" />
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" size="sm" onClick={onEditStart}>
              <Edit2 className="h-4 w-4" />
            </Button>
            {onDelete && (
              <Button
                variant="outline"
                size="sm"
                onClick={onDelete}
                className="border-red-600 text-red-400 hover:bg-red-500/20"
                title="Delete task"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
