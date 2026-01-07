"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  GripVertical,
  Package,
  Bug,
  CheckSquare,
  Loader2,
  Pause,
  Check,
  X,
  Link2,
} from "lucide-react";

import type { Task, TaskStatus, TaskType } from "@/lib/api";

// ============================================================================
// Task Status Configuration
// ============================================================================

const taskStatusConfig: Record<TaskStatus, { icon: React.ReactNode; className: string; title: string }> = {
  pending: { icon: null, className: "", title: "" },
  running: {
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    className: "text-blue-400",
    title: "Task running",
  },
  paused: {
    icon: <Pause className="h-3.5 w-3.5" />,
    className: "text-yellow-400",
    title: "Task paused",
  },
  completed: {
    icon: <Check className="h-3.5 w-3.5" />,
    className: "text-green-400",
    title: "Task completed",
  },
  failed: {
    icon: <X className="h-3.5 w-3.5" />,
    className: "text-red-400",
    title: "Task failed",
  },
  cancelled: {
    icon: <X className="h-3.5 w-3.5" />,
    className: "text-slate-500",
    title: "Task cancelled",
  },
};

// ============================================================================
// Task Type Configuration
// ============================================================================

const taskTypeConfig: Record<TaskType, { icon: React.ReactNode; className: string }> = {
  feature: {
    icon: <Package className="h-3.5 w-3.5" />,
    className: "text-purple-400",
  },
  bug: {
    icon: <Bug className="h-3.5 w-3.5" />,
    className: "text-red-400",
  },
  task: {
    icon: <CheckSquare className="h-3.5 w-3.5" />,
    className: "text-blue-400",
  },
};

// ============================================================================
// Priority Colors
// ============================================================================

const priorityColors: Record<number, string> = {
  0: "bg-rose-500/30 text-rose-300 border-rose-500/40", // Critical
  1: "bg-orange-500/20 text-orange-400 border-orange-500/30", // High
  2: "bg-amber-500/20 text-amber-400 border-amber-500/30", // Medium
  3: "bg-blue-500/20 text-blue-400 border-blue-500/30", // Low
  4: "bg-slate-500/20 text-slate-400 border-slate-500/30", // Backlog
};

// ============================================================================
// Types
// ============================================================================

interface TaskCardProps {
  task: Task;
  onClick?: () => void;
}

// ============================================================================
// Task Card Component
// ============================================================================

export function TaskCard({ task, onClick }: TaskCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const typeConfig = taskTypeConfig[task.task_type] || taskTypeConfig.task;
  const statusConfig = taskStatusConfig[task.status];

  // Capability context for criteria progress
  const capability = task.capability;
  const hasCriteria = capability && capability.criteria_total > 0;
  const allPassed = hasCriteria && capability.criteria_passed === capability.criteria_total;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group relative rounded-lg border border-slate-700 bg-slate-900/80 p-3 shadow-sm hover:border-slate-600 hover:bg-slate-850 transition-colors cursor-pointer"
      onClick={onClick}
    >
      {/* Drag Handle */}
      <div
        {...attributes}
        {...listeners}
        className="absolute left-1 top-3 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-4 w-4 text-slate-500" />
      </div>

      {/* Card Content */}
      <div className="pl-4">
        {/* Header: Type Icon + ID + Priority + Status */}
        <div className="flex items-center justify-between gap-2 mb-1">
          <div className="flex items-center gap-2">
            {/* Type Icon */}
            <span className={typeConfig.className} title={task.task_type}>
              {typeConfig.icon}
            </span>
            {/* Task ID */}
            <span className="text-xs mono text-slate-500">{task.id}</span>
            {/* Priority Badge */}
            <span
              className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityColors[task.priority] || priorityColors[2]}`}
            >
              P{task.priority}
            </span>
            {/* Running Indicator */}
            {task.status === "running" && statusConfig?.icon && (
              <span
                className={`flex items-center ${statusConfig.className}`}
                title={statusConfig.title}
              >
                {statusConfig.icon}
              </span>
            )}
          </div>
        </div>

        {/* Title */}
        <h4 className="text-sm font-medium text-white leading-tight mb-2 line-clamp-2">
          {task.title}
        </h4>

        {/* Capability Link or Standalone Indicator */}
        <div className="flex items-center justify-between">
          {capability ? (
            <div className="flex items-center gap-1.5">
              <Link2 className="h-3 w-3 text-slate-500" />
              <span className="text-xs text-phosphor-400 mono">{capability.capability_id}</span>
              {hasCriteria && (
                <span className={`text-xs mono ${allPassed ? "text-phosphor-400" : "text-slate-400"}`}>
                  ({capability.criteria_passed}/{capability.criteria_total})
                </span>
              )}
            </div>
          ) : (
            <span className="text-xs text-slate-600 italic">Standalone</span>
          )}

          {/* Criteria Progress Dots for capability-linked tasks */}
          {hasCriteria && (
            <div className="flex items-center gap-0.5">
              {Array.from({ length: capability!.criteria_total }).map((_, i) => (
                <div
                  key={i}
                  className={`h-1.5 w-1.5 rounded-full ${
                    i < capability!.criteria_passed ? "bg-phosphor-500" : "bg-slate-600"
                  }`}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Drag Overlay Card (for visual feedback during drag)
// ============================================================================

interface DragOverlayTaskCardProps {
  task: Task;
}

export function DragOverlayTaskCard({ task }: DragOverlayTaskCardProps) {
  const typeConfig = taskTypeConfig[task.task_type] || taskTypeConfig.task;

  return (
    <div className="rounded-lg border border-phosphor-500 bg-slate-900 p-3 shadow-xl shadow-phosphor-500/20 rotate-2 max-w-[300px]">
      <div className="flex items-center gap-2 mb-1">
        <span className={typeConfig.className}>{typeConfig.icon}</span>
        <span className="text-xs mono text-slate-500">{task.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityColors[task.priority] || priorityColors[2]}`}
        >
          P{task.priority}
        </span>
      </div>
      <h4 className="text-sm font-medium text-white line-clamp-2">
        {task.title}
      </h4>
    </div>
  );
}
