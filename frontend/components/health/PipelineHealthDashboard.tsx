'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import type { PipelineStatsResponse } from './PipelineTypes'

interface PipelineHealthDashboardProps {
  data: PipelineStatsResponse
}

export function PipelineHealthDashboard({ data }: PipelineHealthDashboardProps) {
  const { task_distribution, throughput, self_healing, verification, partial_merge } = data

  // Calculate total tasks for distribution percentages
  const totalTasks =
    task_distribution.pending +
    task_distribution.queue +
    task_distribution.running +
    task_distribution.ai_reviewing +
    task_distribution.completed +
    task_distribution.blocked +
    task_distribution.failed +
    task_distribution.cancelled +
    task_distribution.abandoned

  // Helper to format percentages
  const formatPercent = (value: number) => `${Math.round(value * 100)}%`
  const formatDecimal = (value: number) => value.toFixed(1)

  // Task distribution with colors
  const taskStatuses = [
    { label: 'Completed', count: task_distribution.completed, color: 'bg-emerald-500', variant: 'phosphor' as const },
    { label: 'Running', count: task_distribution.running, color: 'bg-cyan-500', variant: 'phosphor' as const },
    { label: 'Queue', count: task_distribution.queue, color: 'bg-amber-500', variant: 'amber' as const },
    { label: 'Pending', count: task_distribution.pending, color: 'bg-slate-500', variant: 'slate' as const },
    { label: 'AI Review', count: task_distribution.ai_reviewing, color: 'bg-violet-500', variant: 'violet' as const },
    { label: 'Blocked', count: task_distribution.blocked, color: 'bg-rose-500', variant: 'rose' as const },
    { label: 'Failed', count: task_distribution.failed, color: 'bg-rose-600', variant: 'rose' as const },
    { label: 'Cancelled', count: task_distribution.cancelled, color: 'bg-slate-600', variant: 'slate' as const },
    { label: 'Abandoned', count: task_distribution.abandoned, color: 'bg-slate-700', variant: 'slate' as const },
  ]

  return (
    <div className="space-y-6">
      {/* Task Distribution Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Task Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          {totalTasks === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <span className="text-slate-600 text-2xl mb-2">○</span>
              <span className="text-sm text-slate-500">No tasks yet</span>
              <span className="text-xs text-slate-600 mt-1">
                Tasks will appear here as they are created
              </span>
            </div>
          ) : (
            <>
              {/* Horizontal stacked bar */}
              <div className="mb-4">
                <div className="flex h-4 rounded-full overflow-hidden bg-slate-800">
                  {taskStatuses.map((status) => {
                    if (status.count === 0) return null
                    const widthPercent = (status.count / totalTasks) * 100
                    return (
                      <div
                        key={status.label}
                        className={status.color}
                        style={{ width: `${widthPercent}%` }}
                        title={`${status.label}: ${status.count}`}
                      />
                    )
                  })}
                </div>
              </div>

              {/* Status badges grid */}
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
                {taskStatuses.map((status) => (
                  <div key={status.label} className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">{status.label}</span>
                    <Badge variant={status.variant}>{status.count}</Badge>
                  </div>
                ))}
              </div>

              <div className="mt-3 pt-3 border-t border-slate-800 text-center">
                <span className="text-xs text-slate-500">
                  Total: {totalTasks} tasks
                </span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* Metrics Grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Throughput Metrics */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Throughput</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {totalTasks === 0 ? (
              <div className="flex flex-col items-center justify-center py-4 text-center">
                <span className="text-xs text-slate-500">No completed tasks to analyze</span>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Completed Today</span>
                  <span className="text-lg font-semibold text-phosphor-400 tabular-nums">
                    {throughput.completed_today}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Completed This Week</span>
                  <span className="text-lg font-semibold text-phosphor-400 tabular-nums">
                    {throughput.completed_this_week}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Avg Completion Time</span>
                  <span className="text-lg font-semibold text-slate-300 tabular-nums">
                    {formatDecimal(throughput.avg_completion_hours)}h
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Self-Healing Stats */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Self-Healing</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {totalTasks === 0 ? (
              <div className="flex flex-col items-center justify-center py-4 text-center">
                <span className="text-xs text-slate-500">No completed tasks to analyze</span>
              </div>
            ) : (
              <>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-slate-500">First Attempt Pass Rate</span>
                    <span className="text-sm font-semibold text-phosphor-400 tabular-nums">
                      {formatPercent(self_healing.first_attempt_pass_rate)}
                    </span>
                  </div>
                  <Progress
                    value={self_healing.first_attempt_pass_rate * 100}
                    className="h-1.5"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Avg Retries</span>
                  <span className="text-sm font-semibold text-slate-300 tabular-nums">
                    {formatDecimal(self_healing.avg_self_fix_attempts)}
                  </span>
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-slate-500">Supervisor Escalation</span>
                    <span className="text-sm font-semibold text-amber-400 tabular-nums">
                      {formatPercent(self_healing.supervisor_escalation_rate)}
                    </span>
                  </div>
                  <Progress
                    value={self_healing.supervisor_escalation_rate * 100}
                    className="h-1.5 bg-slate-800"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Model Escalations</span>
                  <Badge variant="rose">{self_healing.model_escalation_count}</Badge>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Verification Metrics */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Verification</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {totalTasks === 0 ? (
              <div className="flex flex-col items-center justify-center py-4 text-center">
                <span className="text-xs text-slate-500">No completed tasks to analyze</span>
              </div>
            ) : (
              <>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-slate-500">Step Pass Rate</span>
                    <span className="text-lg font-semibold text-phosphor-400 tabular-nums">
                      {formatPercent(verification.step_pass_rate)}
                    </span>
                  </div>
                  <Progress
                    value={verification.step_pass_rate * 100}
                    className="h-1.5"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">Avg Retries per Step</span>
                  <span className="text-lg font-semibold text-slate-300 tabular-nums">
                    {formatDecimal(verification.avg_retries_per_step)}
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Completion Quality */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Completion Quality</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-500">Full Completion</span>
                <span className="text-sm font-semibold text-phosphor-400 tabular-nums">
                  {formatPercent(partial_merge.full_completion_rate)}
                </span>
              </div>
              <Progress
                value={partial_merge.full_completion_rate * 100}
                className="h-1.5"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-500">Partial Completion</span>
                <span className="text-sm font-semibold text-amber-400 tabular-nums">
                  {formatPercent(partial_merge.partial_completion_rate)}
                </span>
              </div>
              <Progress
                value={partial_merge.partial_completion_rate * 100}
                className="h-1.5 bg-slate-800"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-500">Total Failure</span>
                <span className="text-sm font-semibold text-rose-400 tabular-nums">
                  {formatPercent(partial_merge.total_failure_rate)}
                </span>
              </div>
              <Progress
                value={partial_merge.total_failure_rate * 100}
                className="h-1.5 bg-slate-800"
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
