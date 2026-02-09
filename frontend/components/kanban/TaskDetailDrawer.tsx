'use client'

import { Loader2 } from 'lucide-react'
import {
  type Checkpoint,
  CheckpointViewer,
} from '@/components/tasks/CheckpointViewer'
import { CriteriaProgress } from '@/components/tasks/CriteriaProgress'
import { ObjectiveSection } from '@/components/tasks/ObjectiveSection'
import { SubtasksSection } from '@/components/tasks/SubtasksSection'
import { Sheet, SheetBody, SheetContent } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import type { Task, TaskStatus } from '@/lib/api'
import { TaskDetailActions } from './TaskDetailActions'
import { TaskDetailCapability } from './TaskDetailCapability'
import { TaskDetailHeader } from './TaskDetailHeader'
import { TaskDetailMetadata } from './TaskDetailMetadata'
import { useTaskEditing } from './hooks/useTaskEditing'
import { useTaskSubtasks } from './hooks/useTaskSubtasks'

interface TaskDetailDrawerProps {
  task: Task | null
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onStatusChange?: (taskId: string, status: TaskStatus) => void
  onTaskUpdate?: (taskId: string, updates: Partial<Task>) => void
  checkpoint?: Checkpoint | null
}

export function TaskDetailDrawer({
  task,
  projectId,
  open,
  onOpenChange,
  onStatusChange,
  onTaskUpdate,
  checkpoint,
}: TaskDetailDrawerProps) {
  const editing = useTaskEditing({
    task: task!,
    onTaskUpdate,
  })

  const { subtasks, isLoadingSubtasks, setSubtasks } = useTaskSubtasks({
    projectId,
    taskId: task?.id,
    open,
  })

  if (!task) {
    return null
  }

  const capability = task.capability

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="max-w-lg">
        <TaskDetailHeader
          task={task}
          isEditing={editing.isEditing}
          editTitle={editing.editTitle}
          onEditTitleChange={editing.setEditTitle}
          onEditStart={editing.handleEditStart}
          onEditCancel={editing.handleEditCancel}
          onEditSave={editing.handleEditSave}
          onClose={() => onOpenChange(false)}
        />

        <SheetBody className="space-y-6">
          <TaskDetailActions task={task} onStatusChange={onStatusChange} />

          {/* Description */}
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-2">
              Description
            </h3>
            {editing.isEditing ? (
              <Textarea
                value={editing.editDescription}
                onChange={(e) => editing.setEditDescription(e.target.value)}
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
          </div>

          <TaskDetailCapability task={task} projectId={projectId} />

          <ObjectiveSection
            objective={task.objective}
            onEdit={async (newObjective) => {
              console.log('Edit objective:', newObjective)
            }}
          />

          {/* Acceptance Criteria */}
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

          {/* Subtasks */}
          {isLoadingSubtasks ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
            </div>
          ) : subtasks.length > 0 ? (
            <SubtasksSection
              projectId={projectId}
              taskId={task.id}
              subtasks={subtasks}
              onTogglePass={async (subtaskId, passes) => {
                setSubtasks((prev) =>
                  prev.map((s) =>
                    s.subtask_id === subtaskId ? { ...s, passes } : s,
                  ),
                )
              }}
            />
          ) : null}

          {/* Labels */}
          {task.labels && task.labels.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-slate-400 mb-2">
                Labels
              </h3>
              <div className="flex flex-wrap gap-2">
                {task.labels.map((label) => (
                  <span
                    key={label}
                    className="text-xs px-2 py-1 rounded bg-slate-700/50 text-slate-400 border border-slate-600"
                  >
                    {label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {checkpoint && (
            <CheckpointViewer
              checkpoint={checkpoint}
              onResume={(prompt) => {
                console.log(
                  'Resume prompt copied:',
                  `${prompt.substring(0, 100)}...`,
                )
              }}
            />
          )}

          <TaskDetailMetadata task={task} />
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}
