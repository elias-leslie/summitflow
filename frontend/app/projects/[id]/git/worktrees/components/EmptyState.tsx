import { HardDrive } from 'lucide-react'

export function EmptyState() {
  return (
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
  )
}
