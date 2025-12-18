/**
 * Beads Tab - Issue Tracking via bd CLI
 *
 * Displays beads (issues) for a project with:
 * - Ready work section (unblocked tasks)
 * - Full bead list with status/priority filters
 * - Create/edit modal
 * - Status updates (open/in_progress/close)
 */

"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Bug,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Filter,
  ListTodo,
  Loader2,
  Plus,
  RefreshCw,
  Sparkles,
  Target,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  fetchBeads,
  fetchReadyBeads,
  fetchBeadStats,
  updateBead,
  closeBead,
  createBead,
  type Bead,
  type BeadStatsResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface BeadsTabProps {
  projectId: string;
}

// Priority colors and labels
const priorityConfig: Record<number, { label: string; color: string; bgColor: string }> = {
  0: { label: "P0", color: "text-red-600", bgColor: "bg-red-100 dark:bg-red-900" },
  1: { label: "P1", color: "text-orange-600", bgColor: "bg-orange-100 dark:bg-orange-900" },
  2: { label: "P2", color: "text-yellow-600", bgColor: "bg-yellow-100 dark:bg-yellow-900" },
  3: { label: "P3", color: "text-blue-600", bgColor: "bg-blue-100 dark:bg-blue-900" },
  4: { label: "P4", color: "text-slate-500", bgColor: "bg-slate-100 dark:bg-slate-800" },
};

// Status colors
const statusConfig: Record<string, { label: string; icon: typeof Circle; color: string }> = {
  open: { label: "Open", icon: Circle, color: "text-blue-500" },
  in_progress: { label: "In Progress", icon: Loader2, color: "text-yellow-500" },
  closed: { label: "Closed", icon: CheckCircle2, color: "text-green-500" },
};

// Type icons
const typeIcons: Record<string, typeof ListTodo> = {
  task: ListTodo,
  bug: Bug,
  feature: Sparkles,
  epic: Target,
  chore: Clock,
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// Bead Row Component
function BeadRow({
  bead,
  isExpanded,
  onToggle,
  onStatusChange,
  isUpdating,
}: {
  bead: Bead;
  isExpanded: boolean;
  onToggle: () => void;
  onStatusChange: (status: string, reason?: string) => void;
  isUpdating: boolean;
}) {
  const priority = priorityConfig[bead.priority] || priorityConfig[2];
  const status = statusConfig[bead.status] || statusConfig.open;
  const TypeIcon = typeIcons[bead.issue_type] || ListTodo;
  const StatusIcon = status.icon;

  return (
    <>
      <tr
        className={cn(
          "border-b border-slate-700/50 hover:bg-slate-800/50 cursor-pointer transition-colors",
          isExpanded && "bg-slate-800/30"
        )}
        onClick={onToggle}
      >
        {/* Expand */}
        <td className="w-8 px-2 py-2">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </td>

        {/* Priority */}
        <td className="w-12 px-2 py-2">
          <span className={cn("text-xs font-mono font-bold", priority.color)}>
            {priority.label}
          </span>
        </td>

        {/* Type */}
        <td className="w-10 px-2 py-2">
          <TypeIcon className="w-4 h-4 text-slate-400" />
        </td>

        {/* ID */}
        <td className="w-32 px-2 py-2">
          <code className="text-xs text-slate-500">{bead.id}</code>
        </td>

        {/* Title */}
        <td className="px-2 py-2">
          <span className="text-sm text-slate-200">{bead.title}</span>
          {bead.labels && bead.labels.length > 0 && (
            <div className="flex gap-1 mt-1 flex-wrap">
              {bead.labels.slice(0, 3).map((label) => (
                <Badge key={label} variant="outline" className="text-xs py-0 h-5">
                  {label}
                </Badge>
              ))}
              {bead.labels.length > 3 && (
                <Badge variant="outline" className="text-xs py-0 h-5">
                  +{bead.labels.length - 3}
                </Badge>
              )}
            </div>
          )}
        </td>

        {/* Status */}
        <td className="w-28 px-2 py-2">
          <div className={cn("flex items-center gap-1 text-xs", status.color)}>
            <StatusIcon className={cn("w-3 h-3", bead.status === "in_progress" && "animate-spin")} />
            {status.label}
          </div>
        </td>

        {/* Date */}
        <td className="w-24 px-2 py-2 text-xs text-slate-500">
          {formatDate(bead.updated_at || bead.created_at)}
        </td>
      </tr>

      {/* Expanded Details */}
      {isExpanded && (
        <tr className="bg-slate-800/20">
          <td colSpan={7} className="px-4 py-3">
            <div className="space-y-3">
              {/* Description */}
              {bead.description && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">Description</h4>
                  <p className="text-sm text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {bead.description}
                  </p>
                </div>
              )}

              {/* Notes */}
              {bead.notes && (
                <div>
                  <h4 className="text-xs font-medium text-slate-400 mb-1">Notes</h4>
                  <p className="text-sm text-slate-300 whitespace-pre-wrap max-h-24 overflow-y-auto">
                    {bead.notes}
                  </p>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-2 pt-2 border-t border-slate-700">
                {bead.status === "open" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      onStatusChange("in_progress");
                    }}
                    disabled={isUpdating}
                  >
                    {isUpdating ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
                    Start Work
                  </Button>
                )}
                {bead.status === "in_progress" && (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        onStatusChange("open");
                      }}
                      disabled={isUpdating}
                    >
                      Pause
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      className="bg-green-600 hover:bg-green-700"
                      onClick={(e) => {
                        e.stopPropagation();
                        const reason = prompt("Close reason:");
                        if (reason) onStatusChange("closed", reason);
                      }}
                      disabled={isUpdating}
                    >
                      {isUpdating ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
                      Close
                    </Button>
                  </>
                )}
                {bead.status === "closed" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      onStatusChange("open");
                    }}
                    disabled={isUpdating}
                  >
                    Reopen
                  </Button>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// Stats Summary Component
function StatsSummary({ stats }: { stats: BeadStatsResponse }) {
  return (
    <div className="grid grid-cols-4 gap-4 mb-6">
      <div className="card p-4">
        <div className="text-2xl font-bold text-white">{stats.open + stats.in_progress}</div>
        <div className="text-xs text-slate-400">Active</div>
      </div>
      <div className="card p-4">
        <div className="text-2xl font-bold text-yellow-500">{stats.in_progress}</div>
        <div className="text-xs text-slate-400">In Progress</div>
      </div>
      <div className="card p-4">
        <div className="text-2xl font-bold text-green-500">{stats.closed}</div>
        <div className="text-xs text-slate-400">Closed</div>
      </div>
      <div className="card p-4">
        <div className="text-2xl font-bold text-slate-400">{stats.total}</div>
        <div className="text-xs text-slate-400">Total</div>
      </div>
    </div>
  );
}

export function BeadsTab({ projectId }: BeadsTabProps) {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "closed">("open");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // Fetch stats
  const { data: stats } = useQuery({
    queryKey: ["beads", projectId, "stats"],
    queryFn: () => fetchBeadStats(projectId),
    staleTime: 30000,
  });

  // Fetch ready beads
  const { data: readyData, isLoading: readyLoading } = useQuery({
    queryKey: ["beads", projectId, "ready"],
    queryFn: () => fetchReadyBeads(projectId),
    staleTime: 30000,
  });

  // Fetch filtered beads
  const { data: beadsData, isLoading: beadsLoading, refetch } = useQuery({
    queryKey: ["beads", projectId, statusFilter],
    queryFn: () => fetchBeads(projectId, statusFilter, 200),
    staleTime: 30000,
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ beadId, updates }: { beadId: string; updates: Record<string, unknown> }) =>
      updateBead(projectId, beadId, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["beads", projectId] });
    },
  });

  // Close mutation
  const closeMutation = useMutation({
    mutationFn: ({ beadId, reason }: { beadId: string; reason: string }) =>
      closeBead(projectId, beadId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["beads", projectId] });
    },
  });

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (data: { title: string; description?: string; priority?: number; issue_type?: string }) =>
      createBead(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["beads", projectId] });
      setShowCreate(false);
    },
  });

  const handleStatusChange = (beadId: string, status: string, reason?: string) => {
    if (status === "closed" && reason) {
      closeMutation.mutate({ beadId, reason });
    } else {
      updateMutation.mutate({ beadId, updates: { status } });
    }
  };

  const handleCreate = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const formData = new FormData(form);
    createMutation.mutate({
      title: formData.get("title") as string,
      description: formData.get("description") as string || undefined,
      priority: parseInt(formData.get("priority") as string) || 2,
      issue_type: formData.get("type") as string || "task",
    });
  };

  const readyBeads = readyData?.beads || [];
  const beads = beadsData?.beads || [];
  const isUpdating = updateMutation.isPending || closeMutation.isPending;

  return (
    <div className="space-y-6">
      {/* Stats Summary */}
      {stats && <StatsSummary stats={stats} />}

      {/* Ready Work Section */}
      {readyBeads.length > 0 && (
        <div className="card">
          <div className="p-4 border-b border-slate-700">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-phosphor-400" />
              <h3 className="font-medium text-white">Ready for Work</h3>
              <Badge variant="outline" className="ml-auto">
                {readyBeads.length}
              </Badge>
            </div>
          </div>
          <div className="divide-y divide-slate-700/50">
            {readyBeads.slice(0, 5).map((bead) => {
              const priority = priorityConfig[bead.priority] || priorityConfig[2];
              const TypeIcon = typeIcons[bead.issue_type] || ListTodo;
              return (
                <div
                  key={bead.id}
                  className="p-3 flex items-center gap-3 hover:bg-slate-800/30 cursor-pointer"
                  onClick={() => setExpandedId(expandedId === bead.id ? null : bead.id)}
                >
                  <span className={cn("text-xs font-mono font-bold", priority.color)}>
                    {priority.label}
                  </span>
                  <TypeIcon className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-200 flex-1">{bead.title}</span>
                  <code className="text-xs text-slate-500">{bead.id}</code>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* All Beads Section */}
      <div className="card">
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ListTodo className="w-5 h-5 text-slate-400" />
              <h3 className="font-medium text-white">All Beads</h3>
            </div>
            <div className="flex items-center gap-2">
              {/* Status Filter */}
              <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1">
                {(["open", "closed", "all"] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={cn(
                      "px-3 py-1 text-xs rounded transition-colors",
                      statusFilter === s
                        ? "bg-slate-700 text-white"
                        : "text-slate-400 hover:text-white"
                    )}
                  >
                    {s === "all" ? "All" : s === "open" ? "Open" : "Closed"}
                  </button>
                ))}
              </div>

              {/* Refresh */}
              <Button
                size="sm"
                variant="outline"
                onClick={() => refetch()}
                disabled={beadsLoading}
              >
                <RefreshCw className={cn("w-4 h-4", beadsLoading && "animate-spin")} />
              </Button>

              {/* Create */}
              <Button size="sm" onClick={() => setShowCreate(true)}>
                <Plus className="w-4 h-4 mr-1" />
                New
              </Button>
            </div>
          </div>
        </div>

        {/* Beads Table */}
        {beadsLoading ? (
          <div className="p-8 flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          </div>
        ) : beads.length === 0 ? (
          <div className="p-8 text-center text-slate-500">
            No beads found
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="text-xs text-slate-500 border-b border-slate-700">
                  <th className="w-8 px-2 py-2"></th>
                  <th className="w-12 px-2 py-2 text-left">Pri</th>
                  <th className="w-10 px-2 py-2"></th>
                  <th className="w-32 px-2 py-2 text-left">ID</th>
                  <th className="px-2 py-2 text-left">Title</th>
                  <th className="w-28 px-2 py-2 text-left">Status</th>
                  <th className="w-24 px-2 py-2 text-left">Updated</th>
                </tr>
              </thead>
              <tbody>
                {beads.map((bead) => (
                  <BeadRow
                    key={bead.id}
                    bead={bead}
                    isExpanded={expandedId === bead.id}
                    onToggle={() => setExpandedId(expandedId === bead.id ? null : bead.id)}
                    onStatusChange={(status, reason) => handleStatusChange(bead.id, status, reason)}
                    isUpdating={isUpdating}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="card w-full max-w-lg m-4">
            <div className="p-4 border-b border-slate-700">
              <h3 className="font-medium text-white">Create Bead</h3>
            </div>
            <form onSubmit={handleCreate} className="p-4 space-y-4">
              <div>
                <label className="block text-sm text-slate-400 mb-1">Title</label>
                <input
                  name="title"
                  required
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-white"
                  placeholder="Brief description of the issue"
                />
              </div>
              <div>
                <label className="block text-sm text-slate-400 mb-1">Description</label>
                <textarea
                  name="description"
                  rows={4}
                  className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-white resize-none"
                  placeholder="Detailed description (optional)"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Priority</label>
                  <select
                    name="priority"
                    defaultValue="2"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-white"
                  >
                    <option value="0">P0 - Critical</option>
                    <option value="1">P1 - High</option>
                    <option value="2">P2 - Medium</option>
                    <option value="3">P3 - Low</option>
                    <option value="4">P4 - Backlog</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-slate-400 mb-1">Type</label>
                  <select
                    name="type"
                    defaultValue="task"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-white"
                  >
                    <option value="task">Task</option>
                    <option value="bug">Bug</option>
                    <option value="feature">Feature</option>
                    <option value="chore">Chore</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={createMutation.isPending}>
                  {createMutation.isPending && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
                  Create
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
