'use client'

import { useQuery } from '@tanstack/react-query'
import { BarChart3, CheckCircle2, RefreshCw, Zap } from 'lucide-react'

interface AutonomousStatus {
  enabled: boolean
  pending_tasks: number
  in_progress: number
  pending_review: number
  completed_24h: number
  failed_24h: number
  approval_rate: number
  iteration_metrics: {
    avg_iterations_to_success: number
    exhausted_count: number
    first_try_success_rate: number
  }
}

async function fetchAutonomousStatus(
  projectId: string,
): Promise<AutonomousStatus> {
  const res = await fetch(`/api/projects/${projectId}/autonomous/status`)
  if (!res.ok) throw new Error('Failed to fetch autonomous status')
  return res.json()
}

interface SuccessMetricsProps {
  projectId: string
}

export function SuccessMetrics({ projectId }: SuccessMetricsProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['autonomous-status', projectId],
    queryFn: () => fetchAutonomousStatus(projectId),
    staleTime: 60000,
  })

  if (isLoading || !data) {
    return (
      <div className="card p-4 animate-pulse">
        <div className="h-16 bg-slate-800 rounded" />
      </div>
    )
  }

  const total24h = data.completed_24h + data.failed_24h
  const successRate =
    total24h > 0 ? ((data.completed_24h / total24h) * 100).toFixed(0) : '--'
  const metrics = data.iteration_metrics

  return (
    <div className="card p-4">
      <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
        <BarChart3 className="w-3.5 h-3.5" />
        Pipeline Metrics (24h)
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricCard
          icon={<CheckCircle2 className="w-4 h-4 text-phosphor-400" />}
          label="Success Rate"
          value={`${successRate}%`}
          detail={`${data.completed_24h} / ${total24h}`}
        />
        <MetricCard
          icon={<Zap className="w-4 h-4 text-amber-400" />}
          label="First-Try"
          value={`${(metrics.first_try_success_rate * 100).toFixed(0)}%`}
          detail="No retries needed"
        />
        <MetricCard
          icon={<RefreshCw className="w-4 h-4 text-blue-400" />}
          label="Avg Iterations"
          value={metrics.avg_iterations_to_success.toFixed(1)}
          detail={`${metrics.exhausted_count} exhausted`}
        />
        <MetricCard
          icon={<CheckCircle2 className="w-4 h-4 text-violet-400" />}
          label="Approval"
          value={`${(data.approval_rate * 100).toFixed(0)}%`}
          detail="7-day review rate"
        />
      </div>
    </div>
  )
}

function MetricCard({
  icon,
  label,
  value,
  detail,
}: {
  icon: React.ReactNode
  label: string
  value: string
  detail: string
}) {
  return (
    <div className="p-2.5 rounded-lg bg-slate-800/50">
      <div className="flex items-center gap-1.5 mb-1">
        {icon}
        <span className="text-[10px] text-slate-400">{label}</span>
      </div>
      <div className="text-lg font-bold text-white">{value}</div>
      <div className="text-[10px] text-slate-500">{detail}</div>
    </div>
  )
}
