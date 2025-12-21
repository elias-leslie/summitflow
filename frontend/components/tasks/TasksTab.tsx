"use client";

import { useState, useMemo } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
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
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  fetchTasks,
  fetchFeatures,
  updateTaskStatus,
  type Task,
  type TaskType,
  type TaskStatus,
  type Feature,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { TaskFilters, DEFAULT_FILTERS, type TaskFilterValues } from "./TaskFilters";
import { CreateTaskDialog } from "./CreateTaskDialog";
import { TaskLogViewer } from "./TaskLogViewer";

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
};

function TaskRow({
  task,
  feature,
  isExpanded,
  onToggle,
  onStatusChange,
  isUpdating,
  projectId,
}: {
  task: Task;
  feature?: Feature;
  isExpanded: boolean;
  onToggle: () => void;
  onStatusChange: (status: TaskStatus) => void;
  isUpdating: boolean;
  projectId: string;
}) {
  const priority = task.priority ?? 2;
  const taskType = task.task_type ?? "task";
  const priorityStyle = priorityConfig[priority] || priorityConfig[2];
  const typeStyle = typeConfig[taskType];
  const statusStyle = statusConfig[task.status];

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

        {/* Title */}
        <td className="px-3 py-3">
          <span className="text-sm text-slate-200 line-clamp-1">{task.title}</span>
        </td>

        {/* Feature */}
        <td className="px-3 py-3">
          {feature ? (
            <span className="text-xs text-purple-400">{feature.feature_id}</span>
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

      {/* Expanded Details */}
      {isExpanded && (
        <tr className="bg-slate-800/20">
          <td colSpan={7} className="px-4 py-3">
            <div className="space-y-3">
              {/* Description */}
              {task.description && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">Description</h4>
                  <p className="text-sm text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {task.description}
                  </p>
                </div>
              )}

              {/* Labels */}
              {task.labels && task.labels.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {task.labels.map((label) => (
                    <Badge key={label} variant="outline" className="text-xs">
                      {label}
                    </Badge>
                  ))}
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 pt-2 border-t border-slate-700">
                {task.status === "pending" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      onStatusChange("running");
                    }}
                    disabled={isUpdating}
                  >
                    {isUpdating && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
                    Start
                  </Button>
                )}
                {task.status === "running" && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onStatusChange("paused");
                      }}
                      disabled={isUpdating}
                    >
                      Pause
                    </Button>
                    <Button
                      size="sm"
                      className="bg-green-600 hover:bg-green-700"
                      onClick={(e) => {
                        e.stopPropagation();
                        onStatusChange("completed");
                      }}
                      disabled={isUpdating}
                    >
                      {isUpdating && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
                      Complete
                    </Button>
                  </>
                )}
                {task.status === "paused" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      onStatusChange("running");
                    }}
                    disabled={isUpdating}
                  >
                    Resume
                  </Button>
                )}
                {task.status === "failed" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      onStatusChange("pending");
                    }}
                    disabled={isUpdating}
                  >
                    Retry
                  </Button>
                )}
              </div>

              {/* Task Log Viewer for running/paused tasks */}
              {(task.status === "running" || task.status === "paused") && (
                <div className="pt-3 border-t border-slate-700" onClick={(e) => e.stopPropagation()}>
                  <h4 className="text-xs font-medium text-slate-400 mb-2">Task Logs</h4>
                  <TaskLogViewer
                    projectId={projectId}
                    taskId={task.id}
                    className="max-h-[400px]"
                  />
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export function TasksTab({ projectId, initialFilters }: TasksTabProps) {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<TaskFilterValues>({
    ...DEFAULT_FILTERS,
    ...initialFilters,
  });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // Fetch all tasks
  const {
    data: tasksData,
    isLoading: tasksLoading,
    refetch,
  } = useQuery({
    queryKey: ["tasks", projectId, "all"],
    queryFn: () => fetchTasks(projectId, { limit: 500 }),
    staleTime: 30000,
  });

  // Fetch features for linking
  const { data: featuresData } = useQuery({
    queryKey: ["features", projectId],
    queryFn: () => fetchFeatures(projectId, { limit: 100 }),
    staleTime: 60000,
  });

  // Status update mutation
  const statusMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: TaskStatus }) =>
      updateTaskStatus(projectId, taskId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
    },
  });

  const handleStatusChange = (taskId: string, status: TaskStatus) => {
    statusMutation.mutate({ taskId, status });
  };

  // Create feature lookup map
  const featureMap = useMemo(() => {
    const map = new Map<number, Feature>();
    if (featuresData?.features) {
      for (const f of featuresData.features) {
        if (f.id !== null) {
          map.set(f.id, f);
        }
      }
    }
    return map;
  }, [featuresData]);

  // Apply client-side filters
  const filteredTasks = useMemo(() => {
    const tasks = tasksData?.tasks || [];
    return tasks.filter((task) => {
      // Type filter
      if (filters.type !== "all" && task.task_type !== filters.type) {
        return false;
      }

      // Status filter
      if (filters.status !== "all") {
        if (filters.status === "active") {
          if (task.status === "completed" || task.status === "failed") {
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
      if (filters.featureId !== "all" && task.feature_id !== filters.featureId) {
        return false;
      }

      // Standalone only filter
      if (filters.standaloneOnly && task.feature_id !== null) {
        return false;
      }

      return true;
    });
  }, [tasksData, filters]);

  const isUpdating = statusMutation.isPending;

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
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={tasksLoading}
          >
            <RefreshCw className={cn("w-4 h-4", tasksLoading && "animate-spin")} />
          </Button>
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4 mr-1" />
            New Task
          </Button>
        </div>
      </div>

      {/* Tasks Table */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
        {tasksLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <CheckCircle2 className="h-8 w-8 mb-2" />
            <span className="text-sm">No tasks found</span>
            <span className="text-xs text-slate-600">Try adjusting your filters</span>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/50">
                <th className="w-8 px-2 py-2"></th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">Priority</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Type</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-32">ID</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">Title</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Feature</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  feature={task.feature_id ? featureMap.get(task.feature_id) : undefined}
                  isExpanded={expandedId === task.id}
                  onToggle={() => setExpandedId(expandedId === task.id ? null : task.id)}
                  onStatusChange={(status) => handleStatusChange(task.id, status)}
                  isUpdating={isUpdating}
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

      {/* Create Task Dialog */}
      <CreateTaskDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        projectId={projectId}
      />
    </div>
  );
}
