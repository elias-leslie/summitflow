import { useQuery } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { fetchWorktreeDiff, type WorktreeInfo } from '@/lib/api'

interface DiffModalProps {
  projectId: string
  worktree: WorktreeInfo
  onClose: () => void
}

export function DiffModal({ projectId, worktree, onClose }: DiffModalProps) {
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
