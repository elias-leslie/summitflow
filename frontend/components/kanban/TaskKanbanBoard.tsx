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
  type DragOverEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

import type { Task, TaskStatus } from "@/lib/api";
import { TaskCard, DragOverlayTaskCard } from "./TaskCard";
import { KanbanFilters, KanbanFilterValues, DEFAULT_KANBAN_FILTERS } from "./KanbanFilters";

// ============================================================================
// Types
// ============================================================================

// Kanban columns for tasks
export type TaskKanbanColumn = "backlog" | "in_progress" | "done";

export interface KanbanColumn {
  id: TaskKanbanColumn;
  title: string;
  color: string;
}

interface TaskKanbanBoardProps {
  tasks: Task[];
  projectId: string;
  onStatusChange?: (taskId: string, newStatus: TaskStatus) => void;
  onTaskClick?: (task: Task) => void;
  onNewTask?: () => void;
}

// ============================================================================
// Status Mapping
// ============================================================================

// Map task status to Kanban column
const statusToColumn: Record<TaskStatus, TaskKanbanColumn> = {
  pending: "backlog",
  running: "in_progress",
  paused: "in_progress",
  failed: "in_progress",
  completed: "done",
};

// Map Kanban column to task status (for drag-drop)
const columnToStatus: Record<TaskKanbanColumn, TaskStatus> = {
  backlog: "pending",
  in_progress: "running",
  done: "completed",
};

// ============================================================================
// Column Configuration
// ============================================================================

const COLUMNS: KanbanColumn[] = [
  { id: "backlog", title: "Backlog", color: "slate" },
  { id: "in_progress", title: "In Progress", color: "blue" },
  { id: "done", title: "Done", color: "phosphor" },
];

// ============================================================================
// Droppable Column
// ============================================================================

interface DroppableColumnProps {
  column: KanbanColumn;
  tasks: Task[];
  onTaskClick?: (task: Task) => void;
}

function DroppableColumn({ column, tasks, onTaskClick }: DroppableColumnProps) {
  const colorClasses: Record<string, { header: string; border: string }> = {
    slate: { header: "text-slate-400", border: "border-slate-700" },
    blue: { header: "text-blue-400", border: "border-blue-700/50" },
    phosphor: { header: "text-phosphor-400", border: "border-phosphor-700/50" },
  };

  const colors = colorClasses[column.color] || colorClasses.slate;

  return (
    <div className={`flex-shrink-0 w-[85vw] sm:w-[320px] md:w-auto md:flex-1 md:min-w-[280px] md:max-w-[400px] flex flex-col rounded-lg border ${colors.border} bg-slate-900/30 snap-start md:snap-align-none`}>
      {/* Column Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className={`text-sm font-medium ${colors.header}`}>{column.title}</h3>
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
  projectId,
  onStatusChange,
  onTaskClick,
  onNewTask,
}: TaskKanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [filters, setFilters] = useState<KanbanFilterValues>(DEFAULT_KANBAN_FILTERS);

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
    })
  );

  // Apply filters to tasks
  const filteredTasks = useMemo(() => {
    return tasks.filter((task) => {
      // Type filter
      if (filters.type !== "all" && task.task_type !== filters.type) {
        return false;
      }
      // Priority filter
      if (filters.priority !== "all" && task.priority !== filters.priority) {
        return false;
      }
      // Feature filter
      if (filters.featureId !== "all" && task.feature_id !== filters.featureId) {
        return false;
      }
      return true;
    });
  }, [tasks, filters]);

  // Group tasks by column (using filtered tasks)
  const tasksByColumn = useMemo(() => {
    const grouped: Record<TaskKanbanColumn, Task[]> = {
      backlog: [],
      in_progress: [],
      done: [],
    };

    for (const task of filteredTasks) {
      const column = statusToColumn[task.status] || "backlog";
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

  const handleDragOver = (_event: DragOverEvent) => {
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
      {/* Filters */}
      <KanbanFilters
        projectId={projectId}
        filters={filters}
        onChange={setFilters}
        onNewTask={onNewTask}
      />

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
