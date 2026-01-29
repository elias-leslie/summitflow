/**
 * Task Stats Component - Displays task statistics grid
 */

interface TaskStatsProps {
  pendingCount: number
  runningCount: number
  completedCount: number
  totalCount: number
}

export function TaskStats({
  pendingCount,
  runningCount,
  completedCount,
  totalCount,
}: TaskStatsProps) {
  return (
    <div className="grid grid-cols-4 gap-4">
      <div className="card p-4">
        <div className="text-2xl font-bold text-white">
          {pendingCount + runningCount}
        </div>
        <div className="text-xs text-slate-400">Active</div>
      </div>
      <div className="card p-4">
        <div className="text-2xl font-bold text-yellow-500">{runningCount}</div>
        <div className="text-xs text-slate-400">Running</div>
      </div>
      <div className="card p-4">
        <div className="text-2xl font-bold text-green-500">
          {completedCount}
        </div>
        <div className="text-xs text-slate-400">Completed</div>
      </div>
      <div className="card p-4">
        <div className="text-2xl font-bold text-slate-400">{totalCount}</div>
        <div className="text-xs text-slate-400">Total</div>
      </div>
    </div>
  )
}
