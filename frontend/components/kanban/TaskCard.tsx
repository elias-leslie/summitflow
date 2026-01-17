"use client";

import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { AnimatePresence } from "motion/react";
import {
  GripVertical,
  Package,
  Bug,
  CheckSquare,
  RefreshCw,
  AlertTriangle,
  ArrowDownCircle,
  Loader2,
  Pause,
  Check,
  X,
  Link2,
  GitPullRequest,
  Bot,
  Eye,
  OctagonX,
  ExternalLink,
  Zap,
  Lightbulb,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import type { Task, TaskStatus, TaskType } from "@/lib/api";
import { ExecutionPanel, type ExecutionState } from "./ExecutionPanel";

// ============================================================================
// Task Status Configuration
// ============================================================================

const taskStatusConfig: Record<
  TaskStatus,
  { icon: React.ReactNode; className: string; title: string }
> = {
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
  blocked: {
    icon: <OctagonX className="h-3.5 w-3.5" />,
    className: "text-orange-400",
    title: "Task blocked",
  },
  pr_created: {
    icon: <GitPullRequest className="h-3.5 w-3.5" />,
    className: "text-amber-400",
    title: "PR created",
  },
  ai_reviewing: {
    icon: <Bot className="h-3.5 w-3.5 animate-pulse" />,
    className: "text-amber-400",
    title: "AI reviewing",
  },
  human_review: {
    icon: <Eye className="h-3.5 w-3.5" />,
    className: "text-violet-400",
    title: "Human review required",
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

const taskTypeConfig: Record<
  TaskType,
  { icon: React.ReactNode; className: string }
> = {
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
  refactor: {
    icon: <RefreshCw className="h-3.5 w-3.5" />,
    className: "text-cyan-400",
  },
  debt: {
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    className: "text-amber-400",
  },
  regression: {
    icon: <ArrowDownCircle className="h-3.5 w-3.5" />,
    className: "text-orange-400",
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
  onExecuteNow?: (taskId: string) => void;
  isExecuting?: boolean;
  // Execution panel props
  execution?: ExecutionState;
  wsConnected?: boolean;
  onStopExecution?: () => void;
  onSendMessage?: (message: string) => void;
}

// Check if task is a crowdsourced idea
function isCrowdsourcedIdea(task: Task): boolean {
  return (
    task.status === "pending" &&
    task.labels?.some((label) => label.toLowerCase() === "crowdsourced")
  );
}

// ============================================================================
// Task Card Component
// ============================================================================

export function TaskCard({
  task,
  onClick,
  onExecuteNow,
  isExecuting,
  execution,
  wsConnected = false,
  onStopExecution,
  onSendMessage,
}: TaskCardProps) {
  const [expanded, setExpanded] = useState(false);
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
  const isIdea = isCrowdsourcedIdea(task);

  // Show expand button for running or ai_reviewing tasks
  const canExpand = task.status === "running" || task.status === "ai_reviewing";

  const handleExpandToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setExpanded(!expanded);
  };

  // Capability context for criteria progress
  const capability = task.capability;
  const hasCriteria = capability && capability.criteria_total > 0;
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total;

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`task-card-${task.id}`}
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

        {/* AI Review Status Bar - shown for relevant states */}
        {(task.status === "ai_reviewing" ||
          task.status === "human_review" ||
          task.status === "pr_created") && (
          <div className="flex items-center gap-2 mb-2 py-1.5 px-2 -mx-1 rounded bg-slate-800/50">
            <span
              className={`flex items-center gap-1.5 ${statusConfig?.className || ""}`}
            >
              {statusConfig?.icon}
              <span className="text-xs font-medium">{statusConfig?.title}</span>
            </span>
            {task.pull_request_url && (
              <a
                href={task.pull_request_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                onClick={(e) => e.stopPropagation()}
              >
                <GitPullRequest className="h-3 w-3" />
                <span>PR</span>
                <ExternalLink className="h-2.5 w-2.5" />
              </a>
            )}
          </div>
        )}

        {/* Capability Link or Standalone Indicator */}
        <div className="flex items-center justify-between">
          {capability ? (
            <div className="flex items-center gap-1.5">
              <Link2 className="h-3 w-3 text-slate-500" />
              <span className="text-xs text-phosphor-400 mono">
                {capability.capability_id}
              </span>
              {hasCriteria && (
                <span
                  className={`text-xs mono ${allPassed ? "text-phosphor-400" : "text-slate-400"}`}
                >
                  ({capability.criteria_passed}/{capability.criteria_total})
                </span>
              )}
            </div>
          ) : task.pull_request_url &&
            task.status !== "ai_reviewing" &&
            task.status !== "human_review" &&
            task.status !== "pr_created" ? (
            <a
              href={task.pull_request_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              <GitPullRequest className="h-3 w-3" />
              <span>View PR</span>
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
          ) : (
            <span className="text-xs text-slate-600 italic">Standalone</span>
          )}

          {/* Criteria Progress Dots for capability-linked tasks */}
          {hasCriteria && (
            <div className="flex items-center gap-0.5">
              {Array.from({ length: capability!.criteria_total }).map(
                (_, i) => (
                  <div
                    key={i}
                    className={`h-1.5 w-1.5 rounded-full ${
                      i < capability!.criteria_passed
                        ? "bg-phosphor-500"
                        : "bg-slate-600"
                    }`}
                  />
                ),
              )}
            </div>
          )}
        </div>

        {/* Execute Now button for crowdsourced ideas */}
        {isIdea && onExecuteNow && (
          <div className="mt-3 pt-2 border-t border-slate-700/50">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onExecuteNow(task.id);
              }}
              disabled={isExecuting}
              className="flex items-center justify-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium rounded bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 border border-yellow-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isExecuting ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Executing...
                </>
              ) : (
                <>
                  <Zap className="h-3 w-3" />
                  Execute Now
                </>
              )}
            </button>
          </div>
        )}

        {/* Idea indicator badge */}
        {isIdea && (
          <div className="absolute top-2 right-2">
            <Lightbulb className="h-4 w-4 text-yellow-400" />
          </div>
        )}

        {/* Expand/Collapse button for running tasks */}
        {canExpand && (
          <button
            onClick={handleExpandToggle}
            className="mt-3 flex items-center justify-center gap-1 w-full py-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                Hide execution details
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                Show execution details
              </>
            )}
          </button>
        )}

        {/* Execution Panel (animated expand/collapse) */}
        <AnimatePresence>
          {expanded &&
            canExpand &&
            execution &&
            onStopExecution &&
            onSendMessage && (
              <ExecutionPanel
                execution={execution}
                connected={wsConnected}
                onStop={onStopExecution}
                onSendMessage={onSendMessage}
              />
            )}
        </AnimatePresence>
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
