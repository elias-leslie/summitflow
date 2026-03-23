'use client'

import { Skeleton } from '@/components/ui/skeleton'
import { AutonomousStatusBar } from './AutonomousStatusBar'
import { FixPipelineCard } from './FixPipelineCard'
import { InfraStatusBar } from './InfraStatusBar'
import { NeedsAttentionCard } from './NeedsAttentionCard'
import { PipelineHealthDashboard } from './PipelineHealthDashboard'
import { QualityGateStatus } from './QualityGateStatus'
import { RecentActivityCard } from './RecentActivityCard'
import { summarizeError } from './HealthUtils'
import { useHealthData } from './useHealthData'
import { usePipelineData } from './usePipelineData'

interface HealthTabProps {
  projectId: string
}

export function HealthTab({ projectId }: HealthTabProps) {
  const {
    health,
    healthLoading,
    healthError,
    unfixedResults,
    unfixedResultsError,
    recentResultsError,
    metrics,
  } = useHealthData(projectId)

  const { pipelineData, pipelineLoading, pipelineError } = usePipelineData(projectId)

  if (healthLoading && pipelineLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-12 w-full rounded-lg" />
        <Skeleton className="h-16 w-full rounded-lg" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Skeleton className="h-48 w-full rounded-lg" />
          <Skeleton className="h-48 w-full rounded-lg" />
        </div>
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <InfraStatusBar />

      {(() => {
        const errors = [healthError, pipelineError, unfixedResultsError, recentResultsError].filter(Boolean)
        return errors.length > 0 ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            <div className="font-medium text-amber-100">Some health data is unavailable</div>
            <div className="mt-1 text-xs text-amber-300/90 space-y-0.5">
              {errors.map((err, i) => (
                <div key={i}>{summarizeError(err, 'Health data unavailable')}</div>
              ))}
            </div>
          </div>
        ) : null
      })()}

      {pipelineLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : pipelineData ? (
        <AutonomousStatusBar autonomous={pipelineData.autonomous} />
      ) : null}

      <QualityGateStatus health={health} />

      {pipelineLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-64 w-full" />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        </div>
      ) : pipelineData ? (
        <PipelineHealthDashboard data={pipelineData} />
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <NeedsAttentionCard
          items={unfixedResults?.items ?? []}
          hasChecks={Boolean(health && Object.keys(health.checks).length > 0)}
          totalUnfixed={health?.total_unfixed ?? unfixedResults?.items.length ?? 0}
        />
        <FixPipelineCard
          detected={metrics.detected}
          flashFixed={metrics.flashFixed}
          sonnetFixed={metrics.sonnetFixed}
          escalatedCount={metrics.escalatedCount}
          autoFixRate={metrics.autoFixRate}
        />
      </div>

      <RecentActivityCard projectId={projectId} />
    </div>
  )
}
