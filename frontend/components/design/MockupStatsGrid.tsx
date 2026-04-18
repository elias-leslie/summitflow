'use client'

import { Box, CheckCircle2, Clock, Sparkles, XCircle } from 'lucide-react'

export type StatusFilter =
  | 'all'
  | 'generated'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'applied'

interface MockupStatsGridProps {
  byStatus: Record<string, number>
  onStatusClick: (status: StatusFilter) => void
}

const statusIcons: Record<string, React.ReactNode> = {
  generated: <Sparkles className="w-4 h-4 text-blue-400" />,
  pending_approval: <Clock className="w-4 h-4 text-amber-400" />,
  approved: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
  rejected: <XCircle className="w-4 h-4 text-rose-400" />,
  applied: <Box className="w-4 h-4 text-purple-400" />,
}

export function MockupStatsGrid({
  byStatus,
  onStatusClick,
}: MockupStatsGridProps): React.ReactElement {
  return (
    <div className="grid grid-cols-5 gap-4 mb-6">
      {Object.entries(byStatus).map(([status, count]) => (
        <div
          key={status}
          className="card p-3 flex items-center gap-3 cursor-pointer hover:bg-slate-700/50"
          onClick={() => onStatusClick(status as StatusFilter)}
        >
          {statusIcons[status]}
          <div>
            <div className="text-slate-100 font-medium">{count}</div>
            <div className="text-slate-400 text-xs capitalize">
              {status.replace('_', ' ')}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
