"use client";

import { useState, useMemo } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

import type { Task, TaskStatus } from "@/lib/api";
import { TaskCard, DragOverlayTaskCard } from "./TaskCard";

// ============================================================================
// Types
// ============================================================================

// Kanban columns for git management workflow (5 columns per decision d2)
export type TaskKanbanColumn =
  | "planning"
  | "in_progress"
  | "ai_review"
  | "human_review"
  | "done";

export interface KanbanColumn {
  id: TaskKanbanColumn;
  title: string;
  color: string;
  icon: "sparkles" | "eye" | null;
}

interface TaskKanbanBoardProps {
  tasks: Task[];
  projectId: string;
  onStatusChange?: (taskId: string, newStatus: TaskStatus) => void;
  onTaskClick?: (task: Task) => void;
  onNewTask?: () => void;
}

// ============================================================================
// Status Mapping (5 columns per decision d2)
// ============================================================================

// Map task status to Kanban column
const statusToColumn: Record<TaskStatus, TaskKanbanColumn> = {
  // Planning column
  pending: "planning",
  // In Progress column
  running: "in_progress",
  paused: "in_progress",
  blocked: "in_progress",
  // AI Review column
  pr_created: "ai_review",
  ai_reviewing: "ai_review",
  pending_review: "ai_review", // Legacy
  // Human Review column
  human_review: "human_review",
  // Done column
  completed: "done",
  failed: "done",
  cancelled: "done",
};

// Map Kanban column to task status (for drag-drop)
const columnToStatus: Record<TaskKanbanColumn, TaskStatus> = {
  planning: "pending",
  in_progress: "running",
  ai_review: "ai_reviewing",
  human_review: "human_review",
  done: "completed",
};

// ============================================================================
// Column Configuration (5 columns per decision d2)
// ============================================================================

const COLUMNS: KanbanColumn[] = [
  { id: "planning", title: "Planning", color: "slate", icon: null },
  { id: "in_progress", title: "In Progress", color: "blue", icon: null },
  { id: "ai_review", title: "AI Review", color: "amber", icon: "sparkles" },
  { id: "human_review", title: "Human Review", color: "violet", icon: "eye" },
  { id: "done", title: "Done", color: "phosphor", icon: null },
];

// ============================================================================
// Icons for Review Columns
// ============================================================================

function SparklesIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 2L9.5 8.5 3 11l6.5 2.5L12 20l2.5-6.5L21 11l-6.5-2.5L12 2z" />
    </svg>
  );
}

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z" />
    </svg>
  );
}

// ============================================================================
// Droppable Column
// ============================================================================

interface DroppableColumnProps {
  column: KanbanColumn;
  tasks: Task[];
  onTaskClick?: (task: Task) => void;
}

function DroppableColumn({ column, tasks, onTaskClick }: DroppableColumnProps) {
  const colorClasses: Record<
    string,
    { header: string; border: string; bg: string }
  > = {
    slate: {
      header: "text-slate-400",
      border: "border-slate-700",
      bg: "bg-slate-900/30",
    },
    blue: {
      header: "text-blue-400",
      border: "border-blue-700/50",
      bg: "bg-slate-900/30",
    },
    amber: {
      header: "text-amber-400",
      border: "border-amber-500/30",
      bg: "bg-amber-950/20",
    },
    violet: {
      header: "text-violet-400",
      border: "border-violet-500/30",
      bg: "bg-violet-950/20",
    },
    phosphor: {
      header: "text-phosphor-400",
      border: "border-phosphor-700/50",
      bg: "bg-slate-900/30",
    },
  };

  const colors = colorClasses[column.color] || colorClasses.slate;

  return (
    <div
      className={`flex-shrink-0 w-[85vw] sm:w-[280px] md:w-auto md:flex-1 md:min-w-[220px] md:max-w-[300px] flex flex-col rounded-lg border ${colors.border} ${colors.bg} snap-start md:snap-align-none`}
    >
      {/* Column Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3
          className={`text-sm font-medium flex items-center gap-1.5 ${colors.header}`}
        >
          {column.icon === "sparkles" && (
            <SparklesIcon className="w-4 h-4 animate-pulse" />
          )}
          {column.icon === "eye" && <EyeIcon className="w-4 h-4" />}
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
              tasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onClick={() => onTaskClick?.(task)}
                />
              ))
            ) : (
              <div className="flex items-center justify-center h-24 text-xs text-slate-600 italic">
                No tasks
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
  );
}

// ============================================================================
// Task Kanban Board
// ============================================================================

export function TaskKanbanBoard({
  tasks,
  onStatusChange,
  onTaskClick,
}: TaskKanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null);

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
  );

  // Tasks are used directly (filtering can be added via props if needed)
  const filteredTasks = tasks;

  // Group tasks by column (using filtered tasks)
  const tasksByColumn = useMemo(() => {
    const grouped: Record<TaskKanbanColumn, Task[]> = {
      planning: [],
      in_progress: [],
      ai_review: [],
      human_review: [],
      done: [],
    };

    for (const task of filteredTasks) {
      const column = statusToColumn[task.status] || "planning";
      grouped[column].push(task);
    }

    // Sort each column by priority (lower is higher priority)
    for (const column of Object.values(grouped)) {
      column.sort((a, b) => a.priority - b.priority);
    }

    return grouped;
  }, [filteredTasks]);

  const activeTask = useMemo(() => {
    if (!activeId) return null;
    return tasks.find((t) => t.id === activeId) ?? null;
  }, [activeId, tasks]);

  // Find which column contains a task
  const findColumn = (taskId: string): TaskKanbanColumn | null => {
    for (const [column, columnTasks] of Object.entries(tasksByColumn)) {
      if (columnTasks.some((t) => t.id === taskId)) {
        return column as TaskKanbanColumn;
      }
    }
    return null;
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragOver = () => {
    // Handle drag over logic if needed for visual feedback
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over) {
      setActiveId(null);
      return;
    }

    const activeTaskId = active.id as string;
    const overId = over.id as string;

    // Find current and target columns
    const fromColumn = findColumn(activeTaskId);

    // Determine target column - could be a column ID or another task ID
    let toColumn: TaskKanbanColumn | null = null;

    // Check if dropping on a column
    if (COLUMNS.some((c) => c.id === overId)) {
      toColumn = overId as TaskKanbanColumn;
    } else {
      // Dropping on another task - find its column
      toColumn = findColumn(overId);
    }

    if (fromColumn && toColumn && fromColumn !== toColumn) {
      // Convert column to task status
      const newStatus = columnToStatus[toColumn];
      onStatusChange?.(activeTaskId, newStatus);
    }

    setActiveId(null);
  };

  const handleDragCancel = () => {
    setActiveId(null);
  };

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
            />
          ))}
        </div>

        {/* Drag Overlay */}
        <DragOverlay>
          {activeTask && <DragOverlayTaskCard task={activeTask} />}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
