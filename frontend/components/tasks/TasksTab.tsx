"use client";

import { useState, useMemo, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence } from "motion/react";
import {
  Bug,
  Package,
  CheckSquare,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  Pause,
  Play,
  Plus,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  List,
  LayoutGrid,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  fetchTasks,
  fetchBlockedTasks,
  fetchTddCapabilities,
  type Task,
  type TaskType,
  type TaskStatus,
  type TddCapability,
} from "@/lib/api";
import { type Subtask } from "@/lib/api/tasks";
import { cn } from "@/lib/utils";
import { TaskFilters, DEFAULT_FILTERS, type TaskFilterValues } from "./TaskFilters";
import { SimpleCreateDialog } from "./SimpleCreateDialog";
import { TaskExpandedView } from "./TaskExpandedView";
import { CriteriaProgress } from "./CriteriaProgress";
import { SubtaskProgress } from "./SubtaskProgress";
import { EnrichmentStatusBadge } from "./EnrichmentStatusBadge";
import { EnrichmentProgress } from "./EnrichmentProgress";
import { TaskReviewModal } from "./TaskReviewModal";

interface TasksTabProps {
  projectId: string;
  initialFilters?: Partial<TaskFilterValues>;
}

// Priority config
const priorityConfig: Record<number, { label: string; className: string }> = {
  0: { label: "P0", className: "bg-red-500/20 text-red-400 border-red-500/30" },
  1: { label: "P1", className: "bg-rose-500/20 text-rose-400 border-rose-500/30" },
  2: { label: "P2", className: "bg-orange-500/20 text-orange-400 border-orange-500/30" },
  3: { label: "P3", className: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
  4: { label: "P4", className: "bg-slate-500/20 text-slate-400 border-slate-500/30" },
};

// Type config
const typeConfig: Record<TaskType, { icon: React.ReactNode; label: string; className: string }> = {
  feature: {
    icon: <Package className="h-3.5 w-3.5" />,
    label: "Feature",
    className: "text-purple-400",
  },
  bug: {
    icon: <Bug className="h-3.5 w-3.5" />,
    label: "Bug",
    className: "text-rose-400",
  },
  task: {
    icon: <CheckSquare className="h-3.5 w-3.5" />,
    label: "Task",
    className: "text-blue-400",
  },
};

// Status config
const statusConfig: Record<TaskStatus, { icon: React.ReactNode; className: string }> = {
  pending: { icon: <Clock className="h-3.5 w-3.5" />, className: "text-slate-400" },
  running: { icon: <Play className="h-3.5 w-3.5" />, className: "text-blue-400" },
  paused: { icon: <Pause className="h-3.5 w-3.5" />, className: "text-amber-400" },
  completed: { icon: <CheckCircle2 className="h-3.5 w-3.5" />, className: "text-green-400" },
  failed: { icon: <XCircle className="h-3.5 w-3.5" />, className: "text-rose-400" },
  cancelled: { icon: <XCircle className="h-3.5 w-3.5" />, className: "text-slate-500" },
};

function TaskRow({
  task,
  capability,
  isExpanded,
  onToggle,
  onTaskUpdated,
  onTaskDeleted,
  subtasks,
  projectId,
}: {
  task: Task;
  capability?: TddCapability;
  isExpanded: boolean;
  onToggle: () => void;
  onTaskUpdated?: (task: Task) => void;
  onTaskDeleted?: () => void;
  subtasks: Subtask[];
  projectId: string;
}) {
  const priority = task.priority ?? 2;
  const taskType = task.task_type ?? "task";
  const priorityStyle = priorityConfig[priority] || priorityConfig[2];
  const typeStyle = typeConfig[taskType] || typeConfig["task"];
  const statusStyle = statusConfig[task.status] || statusConfig["pending"];

  // Phase badge config
  const phaseConfig: Record<string, { label: string; className: string }> = {
    plan: { label: "Plan", className: "bg-slate-600/50 text-slate-300" },
    implement: { label: "Impl", className: "bg-blue-600/50 text-blue-300" },
    test: { label: "Test", className: "bg-amber-600/50 text-amber-300" },
    verify: { label: "Verify", className: "bg-purple-600/50 text-purple-300" },
    complete: { label: "Done", className: "bg-green-600/50 text-green-300" },
  };
  const currentPhase = task.current_phase || "plan";
  const phaseStyle = phaseConfig[currentPhase] || phaseConfig.plan;

  return (
    <>
      <tr
        className={cn(
          "border-b border-slate-800 hover:bg-slate-800/30 transition-colors cursor-pointer",
          isExpanded && "bg-slate-800/50"
        )}
        onClick={onToggle}
      >
        {/* Expand */}
        <td className="w-8 px-2 py-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </td>

        {/* Priority */}
        <td className="px-3 py-3">
          <span className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityStyle.className}`}>
            {priorityStyle.label}
          </span>
        </td>

        {/* Type */}
        <td className="px-3 py-3">
          <span className={`flex items-center gap-1.5 ${typeStyle.className}`}>
            {typeStyle.icon}
            <span className="text-xs">{typeStyle.label}</span>
          </span>
        </td>

        {/* ID */}
        <td className="px-3 py-3">
          <span className="text-xs mono text-slate-500">{task.id}</span>
        </td>

        {/* Title + Warning */}
        <td className="px-3 py-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-200 line-clamp-1">{task.title}</span>
            {!task.objective && task.enrichment_status !== "enriching" && (
              <span title="No objective set">
                <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
              </span>
            )}
          </div>
        </td>

        {/* Phase Badge */}
        <td className="px-3 py-3">
          <span className={`text-2xs px-1.5 py-0.5 rounded font-medium ${phaseStyle.className}`}>
            {phaseStyle.label}
          </span>
        </td>

        {/* Progress Indicators */}
        <td className="px-3 py-3">
          <div className="flex items-center gap-3">
            {/* Criteria Progress */}
            {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
              <CriteriaProgress criteria={task.acceptance_criteria} maxVisible={4} />
            )}
            {/* Subtask Progress */}
            {subtasks.length > 0 && (
              <SubtaskProgress subtasks={subtasks} maxVisible={5} />
            )}
            {/* Enrichment Status Badge for non-accepted tasks */}
            <EnrichmentStatusBadge status={task.enrichment_status} />
          </div>
        </td>

        {/* Capability */}
        <td className="px-3 py-3">
          {capability ? (
            <span className="text-xs text-purple-400">{capability.capability_id}</span>
          ) : (
            <span className="text-xs text-slate-600">—</span>
          )}
        </td>

        {/* Status */}
        <td className="px-3 py-3">
          <span className={`flex items-center gap-1.5 ${statusStyle.className}`}>
            {statusStyle.icon}
            <span className="text-xs capitalize">{task.status}</span>
          </span>
        </td>
      </tr>

      {/* Expanded Details - now using TaskExpandedView */}
      <AnimatePresence>
        {isExpanded && (
          <tr>
            <td colSpan={9}>
              <TaskExpandedView
                projectId={projectId}
                task={task}
                onTaskUpdated={onTaskUpdated}
                onTaskDeleted={onTaskDeleted}
              />
            </td>
          </tr>
        )}
      </AnimatePresence>
    </>
  );
}

type ViewMode = "list" | "kanban";

export function TasksTab({ projectId, initialFilters }: TasksTabProps) {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<TaskFilterValues>({
    ...DEFAULT_FILTERS,
    ...initialFilters,
  });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("list");

  // Enrichment flow state
  const [enrichingTask, setEnrichingTask] = useState<Task | null>(null);
  const [reviewingTask, setReviewingTask] = useState<Task | null>(null);

  // Fetch all tasks
  const {
    data: tasksData,
    isLoading: tasksLoading,
    refetch: refetchTasks,
  } = useQuery({
    queryKey: ["tasks", projectId, "all"],
    queryFn: () => fetchTasks(projectId, { limit: 500 }),
    staleTime: 30000,
  });

  // Fetch blocked tasks (separate query since it's a different endpoint)
  const {
    data: blockedTasksData,
    isLoading: blockedLoading,
    refetch: refetchBlocked,
  } = useQuery({
    queryKey: ["tasks", projectId, "blocked"],
    queryFn: () => fetchBlockedTasks(projectId, 500),
    staleTime: 30000,
    enabled: filters.status === "blocked", // Only fetch when filter is blocked
  });

  // Unified refetch function
  const refetch = useCallback(() => {
    refetchTasks();
    if (filters.status === "blocked") {
      refetchBlocked();
    }
  }, [refetchTasks, refetchBlocked, filters.status]);

  // Fetch capabilities for linking
  const { data: capabilities = [] } = useQuery({
    queryKey: ["capabilities", projectId],
    queryFn: () => fetchTddCapabilities(projectId),
    staleTime: 60000,
  });

  // Handler for task created from SimpleCreateDialog
  const handleTaskCreated = useCallback((task: Task, mode: "queue" | "verify") => {
    if (mode === "verify" && task.enrichment_status === "review") {
      // Sync mode completed - go directly to review
      setReviewingTask(task);
    } else if (mode === "queue" && task.enrichment_status === "enriching") {
      // Async mode - show enrichment progress
      setEnrichingTask(task);
    }
    // Refresh task list
    refetch();
  }, [refetch]);

  // Handler for task updated
  const handleTaskUpdated = useCallback((updatedTask: Task) => {
    queryClient.setQueryData(["tasks", projectId, "all"], (old: { tasks: Task[] } | undefined) => {
      if (!old) return old;
      return {
        ...old,
        tasks: old.tasks.map((t) => t.id === updatedTask.id ? updatedTask : t),
      };
    });
  }, [queryClient, projectId]);

  // Handler for enrichment complete
  const handleEnrichmentComplete = useCallback((task: Task) => {
    setEnrichingTask(null);
    if (task.enrichment_status === "review") {
      setReviewingTask(task);
    }
    refetch();
  }, [refetch]);

  // Handler for task accepted from review modal
  const handleTaskAccepted = useCallback((acceptedTask: Task) => {
    setReviewingTask(null);
    // Update task in cache
    handleTaskUpdated(acceptedTask);
    refetch();
  }, [refetch, handleTaskUpdated]);

  // Handler for task deleted
  const handleTaskDeleted = useCallback(() => {
    setExpandedId(null);
    refetch();
  }, [refetch]);

  // Create capability lookup map
  const capabilityMap = useMemo(() => {
    const map = new Map<number, TddCapability>();
    for (const cap of capabilities) {
      map.set(cap.id, cap);
    }
    return map;
  }, [capabilities]);

  // Apply client-side filters
  const filteredTasks = useMemo(() => {
    // For "blocked" status, use the blocked tasks endpoint data
    const tasks = filters.status === "blocked"
      ? (blockedTasksData?.tasks || [])
      : (tasksData?.tasks || []);

    return tasks.filter((task) => {
      // Type filter
      if (filters.type !== "all" && task.task_type !== filters.type) {
        return false;
      }

      // Status filter (skip for "blocked" since we already fetched blocked tasks)
      if (filters.status !== "all" && filters.status !== "blocked") {
        if (filters.status === "active") {
          if (task.status === "completed" || task.status === "failed" || task.status === "cancelled") {
            return false;
          }
        } else if (task.status !== filters.status) {
          return false;
        }
      }

      // Priority filter
      if (filters.priority !== "all" && task.priority !== filters.priority) {
        return false;
      }

      // Feature filter
      if (filters.capabilityId !== "all" && task.capability_id !== filters.capabilityId) {
        return false;
      }

      // Standalone only filter
      if (filters.standaloneOnly && task.capability_id !== null) {
        return false;
      }

      return true;
    });
  }, [tasksData, blockedTasksData, filters]);

  const isLoading = filters.status === "blocked" ? blockedLoading : tasksLoading;

  return (
    <div className="space-y-4">
      {/* Header with filters */}
      <div className="flex items-center justify-between">
        <TaskFilters
          projectId={projectId}
          filters={filters}
          onChange={setFilters}
        />
        <div className="flex items-center gap-2">
          {/* View Toggle */}
          <div className="flex items-center border border-slate-700 rounded-md overflow-hidden">
            <button
              onClick={() => setViewMode("list")}
              className={cn(
                "p-1.5 transition-colors",
                viewMode === "list"
                  ? "bg-slate-700 text-white"
                  : "bg-transparent text-slate-500 hover:text-slate-300"
              )}
              title="List view"
            >
              <List className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode("kanban")}
              className={cn(
                "p-1.5 transition-colors",
                viewMode === "kanban"
                  ? "bg-slate-700 text-white"
                  : "bg-transparent text-slate-500 hover:text-slate-300"
              )}
              title="Kanban view"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
          </div>

          <Button
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={isLoading}
          >
            <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4 mr-1" />
            New Task
          </Button>
        </div>
      </div>

      {/* Tasks Table */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <CheckCircle2 className="h-8 w-8 mb-2" />
            <span className="text-sm">No tasks found</span>
            <span className="text-xs text-slate-600">Try adjusting your filters</span>
          </div>
        ) : viewMode === "kanban" ? (
          // Kanban view placeholder
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <LayoutGrid className="h-8 w-8 mb-2" />
            <span className="text-sm">Kanban view coming soon</span>
            <span className="text-xs text-slate-600">Switch to list view for now</span>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/50">
                <th className="w-8 px-2 py-2"></th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">Pri</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-20">Type</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-28">ID</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">Title</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">Phase</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-36">Progress</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Capability</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  capability={task.capability_id ? capabilityMap.get(task.capability_id) : undefined}
                  isExpanded={expandedId === task.id}
                  onToggle={() => setExpandedId(expandedId === task.id ? null : task.id)}
                  onTaskUpdated={handleTaskUpdated}
                  onTaskDeleted={handleTaskDeleted}
                  subtasks={[]}
                  projectId={projectId}
                />
              ))}
            </tbody>
          </table>
        )}

        {/* Footer with count */}
        <div className="px-4 py-2 border-t border-slate-700 bg-slate-800/30">
          <span className="text-xs text-slate-500">
            {filteredTasks.length} task{filteredTasks.length !== 1 ? "s" : ""}
            {filters.standaloneOnly && " (standalone only)"}
          </span>
        </div>
      </div>

      {/* Simple Create Task Dialog */}
      <SimpleCreateDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        projectId={projectId}
        onTaskCreated={handleTaskCreated}
      />

      {/* Enrichment Progress Modal - shown inline when enriching */}
      {enrichingTask && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 max-w-md w-full mx-4 shadow-2xl">
            <EnrichmentProgress
              projectId={projectId}
              task={enrichingTask}
              onComplete={handleEnrichmentComplete}
              onError={(err) => {
                console.error("Enrichment error:", err);
                setEnrichingTask(null);
              }}
            />
            <div className="mt-4 pt-4 border-t border-slate-800 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEnrichingTask(null)}
                className="text-slate-500 hover:text-slate-300"
              >
                Run in Background
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Task Review Modal */}
      {reviewingTask && (
        <TaskReviewModal
          open={!!reviewingTask}
          onOpenChange={(open) => {
            if (!open) setReviewingTask(null);
          }}
          projectId={projectId}
          task={reviewingTask}
          onAccept={handleTaskAccepted}
          onDiscard={() => setReviewingTask(null)}
        />
      )}
    </div>
  );
}
