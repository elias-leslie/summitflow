"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bug,
  Wrench,
  CheckSquare,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  Pause,
  Play,
  AlertCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { type Task, type TaskStatus, type TaskType, type TaskListResponse } from "@/lib/api";

// ============================================================================
// Types
// ============================================================================

interface IssuesListProps {
  projectId: string;
}

// ============================================================================
// Priority & Status Config
// ============================================================================

const priorityConfig: Record<number, { label: string; className: string }> = {
  0: { label: "P0", className: "bg-red-500/20 text-red-400 border-red-500/30" },
  1: { label: "P1", className: "bg-rose-500/20 text-rose-400 border-rose-500/30" },
  2: { label: "P2", className: "bg-orange-500/20 text-orange-400 border-orange-500/30" },
  3: { label: "P3", className: "bg-amber-500/20 text-amber-400 border-amber-500/30" },
  4: { label: "P4", className: "bg-slate-500/20 text-slate-400 border-slate-500/30" },
};

const typeConfig: Record<TaskType, { icon: React.ReactNode; label: string; className: string }> = {
  task: {
    icon: <CheckSquare className="h-3.5 w-3.5" />,
    label: "Task",
    className: "text-blue-400",
  },
  bug: {
    icon: <Bug className="h-3.5 w-3.5" />,
    label: "Bug",
    className: "text-rose-400",
  },
  chore: {
    icon: <Wrench className="h-3.5 w-3.5" />,
    label: "Chore",
    className: "text-amber-400",
  },
};

const statusConfig: Record<TaskStatus, { icon: React.ReactNode; className: string }> = {
  pending: { icon: <Clock className="h-3.5 w-3.5" />, className: "text-slate-400" },
  running: { icon: <Play className="h-3.5 w-3.5" />, className: "text-blue-400" },
  paused: { icon: <Pause className="h-3.5 w-3.5" />, className: "text-amber-400" },
  completed: { icon: <CheckCircle2 className="h-3.5 w-3.5" />, className: "text-green-400" },
  failed: { icon: <XCircle className="h-3.5 w-3.5" />, className: "text-rose-400" },
};

// ============================================================================
// Issue Row
// ============================================================================

function IssueRow({ task }: { task: Task }) {
  const priority = task.priority ?? 2;
  const taskType = task.task_type ?? "task";
  const priorityStyle = priorityConfig[priority] || priorityConfig[2];
  const typeStyle = typeConfig[taskType];
  const statusStyle = statusConfig[task.status];

  return (
    <tr className="border-b border-slate-800 hover:bg-slate-800/30 transition-colors">
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

      {/* Status */}
      <td className="px-3 py-3">
        <span className={`flex items-center gap-1.5 ${statusStyle.className}`}>
          {statusStyle.icon}
          <span className="text-xs capitalize">{task.status}</span>
        </span>
      </td>

      {/* Labels */}
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-1">
          {task.labels.slice(0, 2).map((label) => (
            <Badge key={label} variant="slate" className="text-xs">
              {label}
            </Badge>
          ))}
          {task.labels.length > 2 && (
            <Badge variant="slate" className="text-xs">
              +{task.labels.length - 2}
            </Badge>
          )}
        </div>
      </td>

      {/* Created */}
      <td className="px-3 py-3">
        <span className="text-xs text-slate-500">
          {task.created_at ? new Date(task.created_at).toLocaleDateString() : "-"}
        </span>
      </td>
    </tr>
  );
}

// ============================================================================
// Issues List Component
// ============================================================================

async function fetchOrphanTasks(projectId: string): Promise<TaskListResponse> {
  const res = await fetch(
    `/api/projects/${projectId}/tasks?orphans_only=true&limit=100`
  );
  if (!res.ok) throw new Error("Failed to fetch issues");
  return res.json();
}

export function IssuesList({ projectId }: IssuesListProps) {
  // Fetch orphan tasks
  const { data, error, isLoading } = useQuery<TaskListResponse>({
    queryKey: ["issues", projectId],
    queryFn: () => fetchOrphanTasks(projectId),
    enabled: !!projectId,
    staleTime: 1000 * 60, // 1 minute
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-rose-400">
        <AlertCircle className="h-5 w-5" />
        <span>Failed to load issues</span>
      </div>
    );
  }

  const tasks = data?.tasks ?? [];

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
        <CheckCircle2 className="h-8 w-8 mb-2" />
        <span className="text-sm">No issues found</span>
        <span className="text-xs text-slate-600">All tasks are linked to features</span>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-700 bg-slate-800/50">
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">Priority</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-20">Type</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-32">ID</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">Title</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Status</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-40">Labels</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24">Created</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <IssueRow key={task.id} task={task} />
          ))}
        </tbody>
      </table>

      {/* Footer with count */}
      <div className="px-4 py-2 border-t border-slate-700 bg-slate-800/30">
        <span className="text-xs text-slate-500">
          {tasks.length} issue{tasks.length !== 1 ? "s" : ""} (not linked to features)
        </span>
      </div>
    </div>
  );
}
