'use client'

import { useQuery } from '@tanstack/react-query'
import {
  fetchProjectHealth,
  type Project,
} from '@/lib/api'
import { formatTimeAgo } from '@/lib/format'
import { POLL_STANDARD, STALE_STANDARD } from '@/lib/polling'
import { ActivityFeed } from '../dashboard/ActivityFeed'
import { Badge } from '../ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'

function summarizeError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  if (typeof error === 'string' && error.trim()) {
    return error
  }
  return fallback
}

interface ProjectOverviewProps {
  project: Project
}

export function ProjectOverview({ project }: ProjectOverviewProps) {
  const { data: health, isLoading: healthLoading, error: healthError } = useQuery({
    queryKey: ['project-health', project.id],
    queryFn: () => fetchProjectHealth(project.id),
    staleTime: STALE_STANDARD,
    refetchInterval: POLL_STANDARD * 2,
  })

  return (
    <div className="max-w-4xl space-y-6">
      <Card className="border-slate-800/80 bg-slate-950/55">
        <CardHeader className="flex flex-row items-start justify-between gap-3 pb-3">
          <div>
            <CardTitle className="text-base">Service Status</CardTitle>
            <p className="mt-1 text-xs text-slate-500">
              Public-facing reachability for this app.
            </p>
          </div>
          <Badge
            variant={
              healthLoading
                ? 'slate'
                : health?.healthy
                  ? 'emerald'
                  : 'rose'
            }
          >
            {healthLoading ? 'Checking' : health?.healthy ? 'Healthy' : 'Needs attention'}
          </Badge>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-sm text-slate-300">
            {healthLoading
              ? 'Checking the configured health endpoint.'
              : health
                ? health.healthy
                  ? health.response_time_ms != null
                    ? `${Math.round(health.response_time_ms)}ms response time`
                    : 'Endpoint responded successfully.'
                  : health.error || `HTTP ${health.status_code ?? 'error'}`
                : summarizeError(healthError, 'Health status unavailable')}
          </div>
          <div className="space-y-1.5 text-xs text-slate-500">
            <div>Endpoint: {project.health_endpoint || '/health'}</div>
            {health?.checked_at ? <div>Checked {formatTimeAgo(health.checked_at)}</div> : null}
          </div>
        </CardContent>
      </Card>
      <section className="space-y-3">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-slate-100">Recent Activity</h2>
          <p className="text-sm text-slate-500">
            Project-scoped task, git, and backup activity.
          </p>
        </div>
        <ActivityFeed projectId={project.id} />
      </section>
    </div>
  )
}
