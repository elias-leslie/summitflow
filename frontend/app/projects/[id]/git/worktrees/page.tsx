"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  GitBranch,
  Trash2,
  AlertTriangle,
  Loader2,
  HardDrive,
  ArrowLeft,
  FileCode2,
  Plus,
  Minus,
  Clock,
  ExternalLink,
} from "lucide-react";
import Link from "next/link";
import { fetchWorktrees, deleteWorktree, type WorktreeInfo } from "@/lib/api";

export default function WorktreesPage() {
  const params = useParams();
  const projectId = params.id as string;
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const {
    data: worktreesData,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["worktrees", projectId],
    queryFn: () => fetchWorktrees(projectId),
    refetchInterval: 30000,
  });

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteWorktree(projectId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["worktrees", projectId] });
      setDeleteTarget(null);
    },
  });

  const handleDelete = (taskId: string) => {
    if (deleteTarget === taskId) {
      deleteMutation.mutate(taskId);
    } else {
      setDeleteTarget(taskId);
      setTimeout(() => setDeleteTarget(null), 3000);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="card p-8 text-center max-w-md">
          <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-4" />
          <h2 className="display text-lg font-semibold text-white mb-2">
            Failed to Load
          </h2>
          <p className="text-slate-400 mb-6">
            Could not fetch worktree information.
          </p>
          <button onClick={() => refetch()} className="btn-primary">
            Retry
          </button>
        </div>
      </div>
    );
  }

  const worktrees = worktreesData?.worktrees ?? [];

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <header>
        <Link
          href={`/projects/${projectId}/git`}
          className="inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-phosphor-400 transition-colors mb-4"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Git Dashboard
        </Link>

        <div className="flex items-center gap-3 mb-2">
          <span className="mono text-xs text-outrun-500 uppercase tracking-widest">
            Git Control
          </span>
          <div className="h-px flex-1 bg-gradient-to-r from-outrun-500/50 via-slate-700 to-transparent" />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="display text-2xl font-bold text-white tracking-tight">
              Worktree Management
            </h1>
            <p className="text-slate-400 mt-1">
              {worktrees.length} active worktrees for isolated task execution
            </p>
          </div>
        </div>
      </header>

      {/* Worktree List */}
      {worktrees.length > 0 ? (
        <section className="space-y-3">
          {worktrees.map((wt) => (
            <WorktreeCard
              key={wt.task_id}
              worktree={wt}
              projectId={projectId}
              deleteTarget={deleteTarget}
              onDelete={handleDelete}
              isDeleting={
                deleteMutation.isPending && deleteTarget === wt.task_id
              }
            />
          ))}
        </section>
      ) : (
        <div className="card p-12 text-center border border-dashed border-slate-700">
          <HardDrive className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <h3 className="display text-lg font-semibold text-white mb-2">
            No Active Worktrees
          </h3>
          <p className="text-slate-400 max-w-md mx-auto">
            Worktrees are created when agents claim tasks using{" "}
            <code className="mono text-xs bg-slate-800 px-1.5 py-0.5 rounded">
              st claim --agent
            </code>
          </p>
        </div>
      )}
    </div>
  );
}

interface WorktreeCardProps {
  worktree: WorktreeInfo;
  projectId: string;
  deleteTarget: string | null;
  onDelete: (taskId: string) => void;
  isDeleting: boolean;
}

function WorktreeCard({
  worktree,
  projectId,
  deleteTarget,
  onDelete,
  isDeleting,
}: WorktreeCardProps) {
  const isConfirming = deleteTarget === worktree.task_id;

  return (
    <div className="card p-5 group hover:border-outrun-500/30 transition-colors">
      <div className="flex items-start justify-between gap-4">
        {/* Left: Task and Branch Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <Link
              href={`/projects/${projectId}?tab=kanban&task=${worktree.task_id}`}
              className="mono font-medium text-white hover:text-outrun-400 transition-colors"
            >
              {worktree.task_id}
            </Link>
            <ExternalLink className="w-3 h-3 text-slate-500" />
          </div>

          <div className="flex items-center gap-2 text-sm text-slate-400">
            <GitBranch className="w-4 h-4 text-slate-500" />
            <span className="mono truncate">{worktree.branch}</span>
          </div>

          <div className="mono text-xs text-slate-500 truncate mt-1">
            {worktree.path}
          </div>
        </div>

        {/* Middle: Stats */}
        <div className="flex items-center gap-6">
          <div className="text-center">
            <div className="flex items-center gap-1 text-slate-300">
              <FileCode2 className="w-4 h-4 text-slate-500" />
              <span className="font-medium">{worktree.commit_count}</span>
            </div>
            <div className="text-2xs text-slate-500 uppercase mt-0.5">
              Commits
            </div>
          </div>

          <div className="text-center">
            <div className="font-medium text-slate-300">
              {worktree.files_changed}
            </div>
            <div className="text-2xs text-slate-500 uppercase mt-0.5">
              Files
            </div>
          </div>

          <div className="text-center">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-0.5 text-emerald-400">
                <Plus className="w-3 h-3" />
                {worktree.additions}
              </span>
              <span className="flex items-center gap-0.5 text-rose-400">
                <Minus className="w-3 h-3" />
                {worktree.deletions}
              </span>
            </div>
            <div className="text-2xs text-slate-500 uppercase mt-0.5">
              Changes
            </div>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => onDelete(worktree.task_id)}
            disabled={isDeleting}
            className={`
              p-2 rounded transition-all
              ${
                isConfirming
                  ? "bg-rose-500/20 text-rose-400 ring-1 ring-rose-500/50"
                  : "text-slate-500 hover:text-rose-400 hover:bg-slate-800"
              }
              disabled:opacity-50
            `}
            title={isConfirming ? "Click again to confirm" : "Delete worktree"}
          >
            {isDeleting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* Confirmation Message */}
      {isConfirming && (
        <div className="mt-3 pt-3 border-t border-slate-800 text-sm text-rose-400">
          Click delete again to confirm. This will remove the worktree and its
          branch.
        </div>
      )}
    </div>
  );
}
