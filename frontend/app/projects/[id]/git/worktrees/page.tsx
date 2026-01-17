'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Clock,
  ExternalLink,
  Eye,
  FileCode2,
  GitBranch,
  GitMerge,
  GitPullRequest,
  HardDrive,
  Loader2,
  Minus,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import {
  type CleanupResponse,
  cleanupWorktrees,
  createPullRequest,
  deleteWorktree,
  fetchWorktreeDiff,
  fetchWorktrees,
  mergeWorktree,
  pushWorktree,
  type WorktreeInfo,
} from '@/lib/api'

type ModalType = 'diff' | 'merge' | 'pr' | 'cleanup' | null

export default function WorktreesPage() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [activeModal, setActiveModal] = useState<ModalType>(null)
  const [selectedWorktree, setSelectedWorktree] = useState<WorktreeInfo | null>(
    null,
  )
  const [toast, setToast] = useState<{
    message: string
    type: 'success' | 'error'
  } | null>(null)

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const {
    data: worktreesData,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['worktrees', projectId],
    queryFn: () => fetchWorktrees(projectId),
    refetchInterval: 30000,
  })

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteWorktree(projectId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worktrees', projectId] })
      setDeleteTarget(null)
      showToast('Worktree deleted', 'success')
    },
    onError: () => showToast('Failed to delete worktree', 'error'),
  })

  const mergeMutation = useMutation({
    mutationFn: (taskId: string) => mergeWorktree(projectId, taskId, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worktrees', projectId] })
      setActiveModal(null)
      showToast('Merged to main successfully', 'success')
    },
    onError: () => showToast('Merge failed - check for conflicts', 'error'),
  })

  const pushMutation = useMutation({
    mutationFn: (taskId: string) => pushWorktree(projectId, taskId),
    onSuccess: (data) => {
      showToast(`Pushed ${data.branch} to origin`, 'success')
    },
    onError: () => showToast('Push failed', 'error'),
  })

  const prMutation = useMutation({
    mutationFn: ({
      taskId,
      title,
      body,
    }: {
      taskId: string
      title: string
      body: string
    }) => createPullRequest(taskId, { title, body }),
    onSuccess: (data) => {
      setActiveModal(null)
      showToast('Pull request created', 'success')
      window.open(data.pr_url, '_blank')
    },
    onError: () => showToast('Failed to create PR', 'error'),
  })

  const handleDelete = (taskId: string) => {
    if (deleteTarget === taskId) {
      deleteMutation.mutate(taskId)
    } else {
      setDeleteTarget(taskId)
      setTimeout(() => setDeleteTarget(null), 3000)
    }
  }

  const openModal = (modal: ModalType, worktree?: WorktreeInfo) => {
    setActiveModal(modal)
    if (worktree) setSelectedWorktree(worktree)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
      </div>
    )
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
    )
  }

  const worktrees = worktreesData?.worktrees ?? []

  return (
    <div className="p-6 space-y-6">
      {/* Toast */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg flex items-center gap-2 ${
            toast.type === 'success'
              ? 'bg-emerald-500/20 border border-emerald-500/50 text-emerald-400'
              : 'bg-rose-500/20 border border-rose-500/50 text-rose-400'
          }`}
        >
          {toast.type === 'success' ? (
            <Check className="w-4 h-4" />
          ) : (
            <AlertTriangle className="w-4 h-4" />
          )}
          {toast.message}
        </div>
      )}

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
          {worktrees.length > 0 && (
            <button
              onClick={() => openModal('cleanup')}
              className="btn-secondary flex items-center gap-2"
            >
              <Sparkles className="w-4 h-4" />
              Cleanup Old
            </button>
          )}
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
              onViewDiff={() => openModal('diff', wt)}
              onMerge={() => openModal('merge', wt)}
              onPush={() => pushMutation.mutate(wt.task_id)}
              onCreatePR={() => openModal('pr', wt)}
              isPushing={pushMutation.isPending}
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
            Worktrees are created when agents claim tasks using{' '}
            <code className="mono text-xs bg-slate-800 px-1.5 py-0.5 rounded">
              st claim --agent
            </code>
          </p>
        </div>
      )}

      {/* Modals */}
      {activeModal === 'diff' && selectedWorktree && (
        <DiffModal
          projectId={projectId}
          worktree={selectedWorktree}
          onClose={() => setActiveModal(null)}
        />
      )}

      {activeModal === 'merge' && selectedWorktree && (
        <MergeModal
          worktree={selectedWorktree}
          onClose={() => setActiveModal(null)}
          onConfirm={() => mergeMutation.mutate(selectedWorktree.task_id)}
          isPending={mergeMutation.isPending}
        />
      )}

      {activeModal === 'pr' && selectedWorktree && (
        <PRModal
          worktree={selectedWorktree}
          onClose={() => setActiveModal(null)}
          onConfirm={(title, body) =>
            prMutation.mutate({
              taskId: selectedWorktree.task_id,
              title,
              body,
            })
          }
          isPending={prMutation.isPending}
        />
      )}

      {activeModal === 'cleanup' && (
        <CleanupModal
          projectId={projectId}
          onClose={() => setActiveModal(null)}
          onSuccess={() => {
            queryClient.invalidateQueries({
              queryKey: ['worktrees', projectId],
            })
            showToast('Cleanup complete', 'success')
          }}
        />
      )}
    </div>
  )
}

interface WorktreeCardProps {
  worktree: WorktreeInfo
  projectId: string
  deleteTarget: string | null
  onDelete: (taskId: string) => void
  isDeleting: boolean
  onViewDiff: () => void
  onMerge: () => void
  onPush: () => void
  onCreatePR: () => void
  isPushing: boolean
}

function WorktreeCard({
  worktree,
  projectId,
  deleteTarget,
  onDelete,
  isDeleting,
  onViewDiff,
  onMerge,
  onPush,
  onCreatePR,
  isPushing,
}: WorktreeCardProps) {
  const isConfirming = deleteTarget === worktree.task_id

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
        <div className="flex items-center gap-1">
          <button
            onClick={onViewDiff}
            className="p-2 rounded text-slate-500 hover:text-phosphor-400 hover:bg-slate-800 transition-all"
            title="View diff"
          >
            <Eye className="w-4 h-4" />
          </button>

          <button
            onClick={onMerge}
            className="p-2 rounded text-slate-500 hover:text-emerald-400 hover:bg-slate-800 transition-all"
            title="Merge to main"
          >
            <GitMerge className="w-4 h-4" />
          </button>

          <button
            onClick={onPush}
            disabled={isPushing}
            className="p-2 rounded text-slate-500 hover:text-sky-400 hover:bg-slate-800 transition-all disabled:opacity-50"
            title="Push to origin"
          >
            {isPushing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Upload className="w-4 h-4" />
            )}
          </button>

          <button
            onClick={onCreatePR}
            className="p-2 rounded text-slate-500 hover:text-violet-400 hover:bg-slate-800 transition-all"
            title="Create pull request"
          >
            <GitPullRequest className="w-4 h-4" />
          </button>

          <div className="w-px h-6 bg-slate-700 mx-1" />

          <button
            onClick={() => onDelete(worktree.task_id)}
            disabled={isDeleting}
            className={`
              p-2 rounded transition-all
              ${
                isConfirming
                  ? 'bg-rose-500/20 text-rose-400 ring-1 ring-rose-500/50'
                  : 'text-slate-500 hover:text-rose-400 hover:bg-slate-800'
              }
              disabled:opacity-50
            `}
            title={isConfirming ? 'Click again to confirm' : 'Delete worktree'}
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
  )
}

function DiffModal({
  projectId,
  worktree,
  onClose,
}: {
  projectId: string
  worktree: WorktreeInfo
  onClose: () => void
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['worktree-diff', projectId, worktree.task_id],
    queryFn: () => fetchWorktreeDiff(projectId, worktree.task_id),
  })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-3xl max-h-[80vh] overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div>
            <h3 className="display text-lg font-semibold text-white">
              Changes in {worktree.task_id}
            </h3>
            <p className="text-sm text-slate-400 mt-0.5">
              Branch: {worktree.branch}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 overflow-auto max-h-[calc(80vh-80px)]">
          {isLoading && (
            <div className="flex justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-outrun-500" />
            </div>
          )}

          {error && (
            <div className="text-rose-400 text-center py-8">
              Failed to load diff
            </div>
          )}

          {data && (
            <div className="space-y-4">
              <div className="flex items-center gap-4 text-sm">
                <span className="text-slate-400">
                  {data.commit_count} commits
                </span>
                <span className="text-emerald-400">+{data.additions}</span>
                <span className="text-rose-400">-{data.deletions}</span>
              </div>

              <div className="space-y-1">
                {data.files.map((file, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-2 p-2 bg-slate-800/50 rounded text-sm"
                  >
                    <span
                      className={`mono text-xs font-medium w-4 ${
                        file.status === 'A'
                          ? 'text-emerald-400'
                          : file.status === 'D'
                            ? 'text-rose-400'
                            : 'text-amber-400'
                      }`}
                    >
                      {file.status}
                    </span>
                    <span className="mono text-slate-300">{file.path}</span>
                  </div>
                ))}
              </div>

              {data.diff && (
                <pre className="mono text-xs p-4 bg-slate-950 rounded-lg overflow-x-auto text-slate-300">
                  {data.diff}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MergeModal({
  worktree,
  onClose,
  onConfirm,
  isPending,
}: {
  worktree: WorktreeInfo
  onClose: () => void
  onConfirm: () => void
  isPending: boolean
}) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-md">
        <div className="p-6">
          <div className="w-12 h-12 rounded-full bg-emerald-500/20 flex items-center justify-center mx-auto mb-4">
            <GitMerge className="w-6 h-6 text-emerald-400" />
          </div>
          <h3 className="display text-lg font-semibold text-white text-center mb-2">
            Merge to Main?
          </h3>
          <p className="text-slate-400 text-center text-sm mb-6">
            This will merge{' '}
            <span className="mono text-phosphor-400">{worktree.branch}</span>{' '}
            into main and delete the worktree.
          </p>

          <div className="bg-slate-800/50 rounded-lg p-3 mb-6">
            <div className="text-xs text-slate-500 uppercase mb-1">Changes</div>
            <div className="flex items-center gap-4 text-sm">
              <span className="text-slate-300">
                {worktree.commit_count} commits
              </span>
              <span className="text-emerald-400">+{worktree.additions}</span>
              <span className="text-rose-400">-{worktree.deletions}</span>
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="flex-1 btn-secondary"
              disabled={isPending}
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
              disabled={isPending}
            >
              {isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <GitMerge className="w-4 h-4" />
              )}
              Merge
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function PRModal({
  worktree,
  onClose,
  onConfirm,
  isPending,
}: {
  worktree: WorktreeInfo
  onClose: () => void
  onConfirm: (title: string, body: string) => void
  isPending: boolean
}) {
  const [title, setTitle] = useState(`feat: ${worktree.task_id}`)
  const [body, setBody] = useState(
    `## Summary\nImplemented ${worktree.task_id}\n\n## Changes\n- ${worktree.files_changed} files changed\n- +${worktree.additions} / -${worktree.deletions}`,
  )

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <h3 className="display text-lg font-semibold text-white">
            Create Pull Request
          </h3>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1.5">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-outrun-500"
            />
          </div>

          <div>
            <label className="block text-sm text-slate-400 mb-1.5">
              Description
            </label>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={6}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-outrun-500 resize-none"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={onClose}
              className="flex-1 btn-secondary"
              disabled={isPending}
            >
              Cancel
            </button>
            <button
              onClick={() => onConfirm(title, body)}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
              disabled={isPending || !title.trim()}
            >
              {isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <GitPullRequest className="w-4 h-4" />
              )}
              Create PR
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function CleanupModal({
  projectId,
  onClose,
  onSuccess,
}: {
  projectId: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [maxAgeDays, setMaxAgeDays] = useState(30)
  const [previewData, setPreviewData] = useState<CleanupResponse | null>(null)

  const previewMutation = useMutation({
    mutationFn: () => cleanupWorktrees(projectId, maxAgeDays, true),
    onSuccess: setPreviewData,
  })

  const cleanupMutation = useMutation({
    mutationFn: () => cleanupWorktrees(projectId, maxAgeDays, false),
    onSuccess: () => {
      onSuccess()
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <h3 className="display text-lg font-semibold text-white">
            Cleanup Old Worktrees
          </h3>
          <button
            onClick={onClose}
            className="p-2 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <div>
            <label className="block text-sm text-slate-400 mb-1.5">
              Remove worktrees older than
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={maxAgeDays}
                onChange={(e) =>
                  setMaxAgeDays(parseInt(e.target.value, 10) || 30)
                }
                min={1}
                max={365}
                className="w-24 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-outrun-500"
              />
              <span className="text-slate-400">days</span>
              <button
                onClick={() => previewMutation.mutate()}
                className="ml-auto btn-secondary text-sm"
                disabled={previewMutation.isPending}
              >
                {previewMutation.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  'Preview'
                )}
              </button>
            </div>
          </div>

          {previewData && (
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-xs text-slate-500 uppercase mb-2">
                Would Remove
              </div>
              {previewData.would_remove.length > 0 ? (
                <div className="space-y-1 max-h-40 overflow-auto">
                  {previewData.would_remove.map((item, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="mono text-slate-300">
                        {item.task_id}
                      </span>
                      <span className="text-slate-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {item.age_days} days old
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-400 text-sm">
                  No worktrees older than {maxAgeDays} days
                </p>
              )}
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button onClick={onClose} className="flex-1 btn-secondary">
              Cancel
            </button>
            <button
              onClick={() => cleanupMutation.mutate()}
              className="flex-1 btn-primary flex items-center justify-center gap-2"
              disabled={
                cleanupMutation.isPending ||
                !previewData ||
                previewData.would_remove.length === 0
              }
            >
              {cleanupMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              Cleanup
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
