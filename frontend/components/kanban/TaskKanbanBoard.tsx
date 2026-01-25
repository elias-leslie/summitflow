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
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { useMemo, useState } from 'react'
import { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import type { Task, TaskStatus } from '@/lib/api'
import { executeTask } from '@/lib/api/tasks'
import { DragOverlayTaskCard, TaskCard } from './TaskCard'

// ============================================================================
// Types
// ============================================================================

// Kanban columns for git management workflow (7 columns: Ideas + 6 workflow per decision d2/d4/d9)
export type TaskKanbanColumn =
  | 'ideas'
  | 'planning'
  | 'queue'
  | 'in_progress'
  | 'ai_review'
  | 'human_review'
  | 'done'

export interface KanbanColumn {
  id: TaskKanbanColumn
  title: string
  color: string
  icon: 'sparkles' | 'eye' | 'lightbulb' | null
}

interface TaskKanbanBoardProps {
  tasks: Task[]
  projectId: string
  onStatusChange?: (taskId: string, newStatus: TaskStatus) => void
  onTaskClick?: (task: Task) => void
  onNewTask?: () => void
}

// ============================================================================
// Status Mapping (5 columns per decision d2)
// ============================================================================

// Map task status to Kanban column
// Note: 'idea' status handled specially via crowdsourced label check
const statusToColumn: Record<TaskStatus, TaskKanbanColumn> = {
  // Planning column
  pending: 'planning',
  // Queue column (waiting for execution)
  queue: 'queue',
  // In Progress column
  running: 'in_progress',
  paused: 'in_progress',
  blocked: 'in_progress',
  // AI Review column
  pr_created: 'ai_review',
  ai_reviewing: 'ai_review',
  // Human Review column
  human_review: 'human_review',
  // Done column
  completed: 'done',
  failed: 'done',
  cancelled: 'done',
}

// Check if task is a crowdsourced idea (should be in Ideas column)
function isCrowdsourcedIdea(task: Task): boolean {
  // Tasks with crowdsourced label that are still pending go to Ideas column
  // Once they start (running/etc), they move to normal workflow
  return (
    task.status === 'pending' &&
    task.labels?.some((label) => label.toLowerCase() === 'crowdsourced')
  )
}

// Map Kanban column to task status (for drag-drop)
const columnToStatus: Record<TaskKanbanColumn, TaskStatus> = {
  ideas: 'pending', // Ideas are pending tasks with crowdsourced label
  planning: 'pending',
  queue: 'queue',
  in_progress: 'running',
  ai_review: 'ai_reviewing',
  human_review: 'human_review',
  done: 'completed',
}

// ============================================================================
// Column Configuration (6 columns: Ideas + 5 workflow per decision d2/d4)
// ============================================================================

const COLUMNS: KanbanColumn[] = [
  { id: 'ideas', title: 'Ideas', color: 'yellow', icon: 'lightbulb' },
  { id: 'planning', title: 'Planning', color: 'slate', icon: null },
  { id: 'queue', title: 'Queue', color: 'sky', icon: null },
  { id: 'in_progress', title: 'In Progress', color: 'blue', icon: null },
  { id: 'ai_review', title: 'AI Review', color: 'amber', icon: 'sparkles' },
  { id: 'human_review', title: 'Human Review', color: 'violet', icon: 'eye' },
  { id: 'done', title: 'Done', color: 'phosphor', icon: null },
]

// ============================================================================
// Icons for Column Headers
// ============================================================================

function LightbulbIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2a7 7 0 0 0-7 7c0 2.38 1.19 4.47 3 5.74V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.26c1.81-1.27 3-3.36 3-5.74a7 7 0 0 0-7-7zm2 15h-4v-1h4v1zm0-3h-4v-1.26l-.25-.18A5 5 0 0 1 7 9a5 5 0 1 1 10 0 5 5 0 0 1-2.75 4.56l-.25.18V14zm-1 5h-2v1a1 1 0 0 0 1 1 1 1 0 0 0 1-1v-1z" />
    </svg>
  )
}

function SparklesIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L9.5 8.5 3 11l6.5 2.5L12 20l2.5-6.5L21 11l-6.5-2.5L12 2z" />
    </svg>
  )
}

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z" />
    </svg>
  )
}

// ============================================================================
// Droppable Column
// ============================================================================

interface DroppableColumnProps {
  column: KanbanColumn
  tasks: Task[]
  onTaskClick?: (task: Task) => void
  onExecuteNow?: (taskId: string) => void
  executingTaskId?: string | null
  // WebSocket execution state for running tasks
  runningTaskId?: string | null
  executionHook?: ReturnType<typeof useExecutionWebSocket>
}

function DroppableColumn({
  column,
  tasks,
  onTaskClick,
  onExecuteNow,
  executingTaskId,
  runningTaskId,
  executionHook,
}: DroppableColumnProps) {
  const colorClasses: Record<
    string,
    { header: string; border: string; bg: string }
  > = {
    yellow: {
      header: 'text-yellow-400',
      border: 'border-yellow-500/30',
      bg: 'bg-yellow-950/20',
    },
    slate: {
      header: 'text-slate-400',
      border: 'border-slate-700',
      bg: 'bg-slate-900/30',
    },
    sky: {
      header: 'text-sky-400',
      border: 'border-sky-500/30',
      bg: 'bg-sky-950/20',
    },
    blue: {
      header: 'text-blue-400',
      border: 'border-blue-700/50',
      bg: 'bg-slate-900/30',
    },
    amber: {
      header: 'text-amber-400',
      border: 'border-amber-500/30',
      bg: 'bg-amber-950/20',
    },
    violet: {
      header: 'text-violet-400',
      border: 'border-violet-500/30',
      bg: 'bg-violet-950/20',
    },
    phosphor: {
      header: 'text-phosphor-400',
      border: 'border-phosphor-700/50',
      bg: 'bg-slate-900/30',
    },
  }

  const colors = colorClasses[column.color] || colorClasses.slate

  return (
    <div
      className={`flex-shrink-0 w-[85vw] sm:w-[280px] md:w-auto md:flex-1 md:min-w-[220px] md:max-w-[300px] flex flex-col rounded-lg border ${colors.border} ${colors.bg} snap-start md:snap-align-none`}
    >
      {/* Column Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3
          className={`text-sm font-medium flex items-center gap-1.5 ${colors.header}`}
        >
          {column.icon === 'lightbulb' && <LightbulbIcon className="w-4 h-4" />}
          {column.icon === 'sparkles' && (
            <SparklesIcon className="w-4 h-4 animate-pulse" />
          )}
          {column.icon === 'eye' && <EyeIcon className="w-4 h-4" />}
          {column.title}
        </h3>
        <span className="text-xs mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
          {tasks.length}
        </span>
      </div>

      {/* Column Content */}
      <div className="flex-1 p-2 overflow-y-auto min-h-[200px] max-h-[calc(100vh-300px)]">
        <SortableContext
          items={tasks.map((t) => t.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2">
            {tasks.length > 0 ? (
              tasks.map((task) => {
                const isRunningTask = task.id === runningTaskId
                return (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onClick={() => onTaskClick?.(task)}
                    onExecuteNow={
                      column.id === 'ideas' ? onExecuteNow : undefined
                    }
                    isExecuting={executingTaskId === task.id}
                    execution={
                      isRunningTask ? executionHook?.execution : undefined
                    }
                    wsConnected={
                      isRunningTask ? executionHook?.connected : false
                    }
                    onStopExecution={
                      isRunningTask ? executionHook?.sendStop : undefined
                    }
                    onSendMessage={
                      isRunningTask ? executionHook?.sendMessage : undefined
                    }
                  />
                )
              })
            ) : (
              <div className="flex items-center justify-center h-24 text-xs text-slate-600 italic">
                No tasks
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
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
  const [activeId, setActiveId] = useState<string | null>(null)
  const [executingTaskId, setExecutingTaskId] = useState<string | null>(null)

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

  // Tasks are used directly (filtering can be added via props if needed)
  const filteredTasks = tasks

  // Group tasks by column (using filtered tasks)
  const tasksByColumn = useMemo(() => {
    const grouped: Record<TaskKanbanColumn, Task[]> = {
      ideas: [],
      planning: [],
      queue: [],
      in_progress: [],
      ai_review: [],
      human_review: [],
      done: [],
    }

    for (const task of filteredTasks) {
      // Check if task is a crowdsourced idea (pending tasks with crowdsourced label)
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
  }, [filteredTasks])

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

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }

  const handleDragOver = () => {
    // Handle drag over logic if needed for visual feedback
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

    // Determine target column - could be a column ID or another task ID
    let toColumn: TaskKanbanColumn | null = null

    // Check if dropping on a column
    if (COLUMNS.some((c) => c.id === overId)) {
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

  const handleDragCancel = () => {
    setActiveId(null)
  }

  return (
    <div className="space-y-4">
      {/* TODO: Add task filters if needed */}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDragEnd={handleDragEnd}
        onDragCancel={handleDragCancel}
      >
        <div className="flex gap-4 overflow-x-auto pb-4 snap-x snap-mandatory md:snap-none scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
          {COLUMNS.map((column) => (
            <DroppableColumn
              key={column.id}
              column={column}
              tasks={tasksByColumn[column.id]}
              onTaskClick={onTaskClick}
              onExecuteNow={handleExecuteNow}
              executingTaskId={executingTaskId}
              runningTaskId={runningTask?.id}
              executionHook={executionHook}
            />
          ))}
        </div>

        {/* Drag Overlay */}
        <DragOverlay>
          {activeTask && <DragOverlayTaskCard task={activeTask} />}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
