'use client'

import { Loader2 } from 'lucide-react'
import { AgentObservabilityTimeline } from '@/components/tasks/AgentObservabilityTimeline'
import { CheckpointStatus } from '@/components/tasks/CheckpointStatus'
import { CollapsibleSection } from '@/components/tasks/CollapsibleSection'
import { CriteriaProgress } from '@/components/tasks/CriteriaProgress'
import { ExecutionTimeline } from '@/components/tasks/ExecutionTimeline'
import { LinkedCapabilitySection } from '@/components/tasks/LinkedCapabilitySection'
import { ObjectiveSection } from '@/components/tasks/ObjectiveSection'
import { SubtasksSection } from '@/components/tasks/SubtasksSection'
import { TaskLabels } from '@/components/tasks/TaskLabels'
import { TaskMetadata } from '@/components/tasks/TaskMetadata'
import { TaskModalActions } from '@/components/tasks/TaskModalActions'
import { WorktreeSection } from '@/components/tasks/WorktreeSection'
import { Textarea } from '@/components/ui/textarea'
import type { Task, Subtask, TaskStatus } from '@/lib/api/tasks'

interface TaskModalContentProps {
  task: Task
  projectId: string
  subtasks: Subtask[]
  isLoadingSubtasks: boolean
  subtasksError: string | null
  isEditing: boolean
  editDescription: string
  isExecuting: boolean
  isStopping: boolean
  isTogglingAutonomous: boolean
  executionError: string | null
  descriptionOpen: boolean
  subtasksOpen: boolean
  timelineOpen: boolean
  agentTimelineOpen: boolean
  onEditDescriptionChange: (value: string) => void
  onDescriptionToggle: () => void
  onSubtasksToggle: () => void
  onTimelineToggle: () => void
  onAgentTimelineToggle: () => void
  onStartExecution: () => void
  onStopExecution: () => void
  onStatusChange: (status: TaskStatus) => Promise<void>
  onToggleAutonomous: () => void
  onAgentOverrideChange: (agentId: string | null) => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onDelete: () => void
  onObjectiveEdit: (objective: string) => void
  onSubtaskToggle: (subtaskId: string, passes: boolean) => Promise<void>
}

export function TaskModalContent({
  task,
  projectId,
  subtasks,
  isLoadingSubtasks,
  subtasksError,
  isEditing,
  editDescription,
  isExecuting,
  isStopping,
  isTogglingAutonomous,
  executionError,
  descriptionOpen,
  subtasksOpen,
  timelineOpen,
  agentTimelineOpen,
  onEditDescriptionChange,
  onDescriptionToggle,
  onSubtasksToggle,
  onTimelineToggle,
  onAgentTimelineToggle,
  onStartExecution,
  onStopExecution,
  onStatusChange,
  onToggleAutonomous,
  onAgentOverrideChange,
  onEditStart,
  onEditCancel,
  onEditSave,
  onDelete,
  onObjectiveEdit,
  onSubtaskToggle,
}: TaskModalContentProps) {
  // Status checks for timeline visibility
  const isRunning = task.status === 'running'
  const isPaused = task.status === 'paused'
  const isAiReviewing = task.status === 'ai_reviewing'
  const isCompleted = task.status === 'completed'
  const isPending = task.status === 'pending'
  const isBlocked = task.status === 'blocked'

  // Show timeline for all task states to view execution history
  const showTimeline = isRunning || isPaused || isAiReviewing || isCompleted || isPending || isBlocked

  const capability = task.capability

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
      {/* Execution Error */}
      {executionError && (
        <div className="p-3 bg-red-950/30 border border-red-800/30 rounded-lg mb-4">
          <p className="text-sm text-red-400">{executionError}</p>
        </div>
      )}

      {/* Action Buttons */}
      <TaskModalActions
        task={task}
        isExecuting={isExecuting}
        isStopping={isStopping}
        isTogglingAutonomous={isTogglingAutonomous}
        isEditing={isEditing}
        onStartExecution={onStartExecution}
        onStopExecution={onStopExecution}
        onStatusChange={onStatusChange}
        onToggleAutonomous={onToggleAutonomous}
        onAgentOverrideChange={onAgentOverrideChange}
        onEditStart={onEditStart}
        onEditCancel={onEditCancel}
        onEditSave={onEditSave}
        onDelete={onDelete}
      />

      {/* Checkpoint Status */}
      <CheckpointStatus
        taskId={task.id}
        projectId={projectId}
        taskStatus={task.status}
      />

      {/* Objective Section */}
      <ObjectiveSection objective={task.objective} onEdit={onObjectiveEdit} />

      {/* Worktree Section */}
      {task.worktree && <WorktreeSection worktree={task.worktree} />}

      {/* Description */}
      <CollapsibleSection
        title="Description"
        isOpen={descriptionOpen}
        onToggle={onDescriptionToggle}
        testId="description-toggle"
      >
        {isEditing ? (
          <Textarea
            value={editDescription}
            onChange={(e) => onEditDescriptionChange(e.target.value)}
            rows={3}
            placeholder="Enter task description..."
          />
        ) : (
          <p className="text-sm text-slate-300">
            {task.description || (
              <span className="italic text-slate-500">No description</span>
            )}
          </p>
        )}
      </CollapsibleSection>

      {/* Linked Capability */}
      {capability && (
        <LinkedCapabilitySection capability={capability} projectId={projectId} />
      )}

      {/* Criteria Progress */}
      {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-slate-400">
              Acceptance Criteria
            </h3>
            <CriteriaProgress
              criteria={task.acceptance_criteria}
              maxVisible={10}
            />
          </div>
          <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
            {capability
              ? `From: ${capability.capability_id}`
              : 'Task-specific'}
          </span>
        </div>
      )}

      {/* Subtasks Section */}
      {isLoadingSubtasks ? (
        <div className="flex items-center justify-center py-4">
          <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
        </div>
      ) : subtasksError ? (
        <CollapsibleSection
          title="Subtasks"
          isOpen={subtasksOpen}
          onToggle={onSubtasksToggle}
          testId="subtasks-toggle"
        >
          <p className="text-sm text-rose-400">{subtasksError}</p>
        </CollapsibleSection>
      ) : subtasks.length > 0 ? (
        <CollapsibleSection
          title={`Subtasks (${subtasks.filter((s) => s.passes).length}/${subtasks.length})`}
          isOpen={subtasksOpen}
          onToggle={onSubtasksToggle}
          testId="subtasks-toggle"
        >
          <SubtasksSection
            projectId={projectId}
            taskId={task.id}
            subtasks={subtasks}
            onTogglePass={onSubtaskToggle}
          />
        </CollapsibleSection>
      ) : (
        <CollapsibleSection
          title="Subtasks"
          isOpen={subtasksOpen}
          onToggle={onSubtasksToggle}
          testId="subtasks-toggle"
        >
          <p className="text-sm text-slate-500 italic">
            No subtasks. Use st autocode to auto-plan or add subtasks via API.
          </p>
        </CollapsibleSection>
      )}

      {/* Execution Timeline */}
      {showTimeline && (
        <CollapsibleSection
          title="Execution Timeline"
          isOpen={timelineOpen}
          onToggle={onTimelineToggle}
          testId="timeline-toggle"
        >
          <ExecutionTimeline
            taskId={task.id}
            projectId={projectId}
            autoConnect={isRunning || isAiReviewing}
            showChatInput={true}
            chatEnabled={isRunning}
            className="border border-slate-700 rounded-lg overflow-hidden"
          />
        </CollapsibleSection>
      )}

      {/* Agent Observability Timeline */}
      {showTimeline && (
        <CollapsibleSection
          title="Agent Observability"
          isOpen={agentTimelineOpen}
          onToggle={onAgentTimelineToggle}
          testId="agent-timeline-toggle"
        >
          <AgentObservabilityTimeline
            taskId={task.id}
            projectId={projectId}
            isLive={isRunning || isAiReviewing}
            pollInterval={3000}
            maxHeight="600px"
            className="border border-slate-700 rounded-lg overflow-hidden"
          />
        </CollapsibleSection>
      )}

      {/* Labels */}
      <TaskLabels labels={task.labels || []} />

      {/* Metadata */}
      <TaskMetadata task={task} />
    </div>
  )
}
