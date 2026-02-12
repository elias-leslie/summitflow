'use client'

import {
  closestCorners,
  DndContext,
  type DragEndEvent,
  DragOverlay,
  type DragStartEvent,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import type { Task, TaskStatus } from '@/lib/api'
import { deleteTask, executeTask } from '@/lib/api/tasks'
import { DragOverlayTaskCard } from './TaskCard'
import { KanbanRow } from './KanbanRow'
import { DeleteConfirmDialog } from './DeleteConfirmDialog'
import {
  ROWS,
  columnToStatus,
  statusToColumn,
  type TaskKanbanColumn,
} from './columnConfig'
import { useRowCollapse } from './hooks/useRowCollapse'

// ============================================================================
// Types
// ============================================================================

interface TaskKanbanBoardProps {
  tasks: Task[]
  projectId: string
  onStatusChange?: (taskId: string, newStatus: TaskStatus) => void
  onTaskClick?: (task: Task) => void
  onNewTask?: () => void
}

// ============================================================================
// Utility Functions
// ============================================================================

// Check if task is a crowdsourced idea (should be in Ideas column)
function isCrowdsourcedIdea(task: Task): boolean {
  // Tasks with crowdsourced label that are still pending go to Ideas column
  // Once they start (running/etc), they move to normal workflow
  return (
    task.status === 'pending' &&
    task.labels?.some((label) => label.toLowerCase() === 'crowdsourced')
  )
}

// ============================================================================
// Task Kanban Board
// ============================================================================

export function TaskKanbanBoard({
  tasks,
  projectId,
  onStatusChange,
  onTaskClick,
}: TaskKanbanBoardProps) {
  const queryClient = useQueryClient()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [executingTaskId, setExecutingTaskId] = useState<string | null>(null)
  const [deleteConfirmTask, setDeleteConfirmTask] = useState<Task | null>(null)
  const { isCollapsed, toggleRow } = useRowCollapse(projectId)

  // Find the first running task to connect WebSocket
  const runningTask = useMemo(
    () => tasks.find((t) => t.status === 'running'),
    [tasks],
  )

  // WebSocket connection for the running task
  const executionHook = useExecutionWebSocket({
    taskId: runningTask?.id || '',
    enabled: !!runningTask,
  })

  // Group tasks by column
  const tasksByColumn = useMemo(() => {
    const grouped: Record<TaskKanbanColumn, Task[]> = {
      ideas: [],
      planning: [],
      queue: [],
      active: [],
      blocked: [],
      done: [],
    }

    for (const task of tasks) {
      if (isCrowdsourcedIdea(task)) {
        grouped.ideas.push(task)
      } else {
        const column = statusToColumn[task.status] || 'planning'
        grouped[column].push(task)
      }
    }

    // Sort each column by priority (lower is higher priority)
    for (const column of Object.values(grouped)) {
      column.sort((a, b) => a.priority - b.priority)
    }

    return grouped
  }, [tasks])

  const activeTask = useMemo(() => {
    if (!activeId) return null
    return tasks.find((t) => t.id === activeId) ?? null
  }, [activeId, tasks])

  // Find which column contains a task
  const findColumn = (taskId: string): TaskKanbanColumn | null => {
    for (const [column, columnTasks] of Object.entries(tasksByColumn)) {
      if (columnTasks.some((t) => t.id === taskId)) {
        return column as TaskKanbanColumn
      }
    }
    return null
  }

  // ============================================================================
  // Event Handlers
  // ============================================================================

  const handleExecuteNow = async (taskId: string) => {
    setExecutingTaskId(taskId)
    try {
      await executeTask(projectId, taskId)
      // Task is now queued for execution via orchestrator
    } catch (error) {
      console.error('Execute now failed:', error)
      // Could show toast notification here
    } finally {
      setExecutingTaskId(null)
    }
  }

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(projectId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
      setDeleteConfirmTask(null)
    },
  })

  const handleDeleteClick = (taskId: string) => {
    const task = tasks.find((t) => t.id === taskId)
    if (task) {
      setDeleteConfirmTask(task)
    }
  }

  const handleDeleteConfirm = () => {
    if (deleteConfirmTask) {
      deleteMutation.mutate(deleteConfirmTask.id)
    }
  }

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event

    if (!over) {
      setActiveId(null)
      return
    }

    const activeTaskId = active.id as string
    const overId = over.id as string

    // Find current and target columns
    const fromColumn = findColumn(activeTaskId)

    // Determine target column - could be a row ID or another task ID
    let toColumn: TaskKanbanColumn | null = null

    // Check if dropping on a row (droppable zone)
    if (ROWS.some((r) => r.id === overId)) {
      toColumn = overId as TaskKanbanColumn
    } else {
      // Dropping on another task - find its column
      toColumn = findColumn(overId)
    }

    if (fromColumn && toColumn && fromColumn !== toColumn) {
      // Convert column to task status
      const newStatus = columnToStatus[toColumn]
      onStatusChange?.(activeTaskId, newStatus)
    }

    setActiveId(null)
  }

  // ============================================================================
  // Drag and Drop Sensors
  // ============================================================================

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(TouchSensor, {
      activationConstraint: {
        delay: 250,
        tolerance: 5,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="space-y-4">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        onDragCancel={() => setActiveId(null)}
      >
        <div className="space-y-3">
          {ROWS.map((column) => (
            <KanbanRow
              key={column.id}
              column={column}
              tasks={tasksByColumn[column.id]}
              isCollapsed={isCollapsed(column.id)}
              isDragging={!!activeId}
              onToggle={() => toggleRow(column.id)}
              onTaskClick={onTaskClick}
              onExecuteNow={handleExecuteNow}
              onDelete={handleDeleteClick}
              executingTaskId={executingTaskId}
              runningTaskId={runningTask?.id}
              executionHook={executionHook}
            />
          ))}
        </div>

        <DragOverlay>
          {activeTask && <DragOverlayTaskCard task={activeTask} />}
        </DragOverlay>
      </DndContext>

      {deleteConfirmTask && (
        <DeleteConfirmDialog
          task={deleteConfirmTask}
          isDeleting={deleteMutation.isPending}
          isError={deleteMutation.isError}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteConfirmTask(null)}
        />
      )}
    </div>
  )
}
