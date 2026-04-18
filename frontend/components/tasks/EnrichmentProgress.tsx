'use client'

import { useCallback } from 'react'
import { EnrichmentProgressBar } from './enrichment/EnrichmentProgressBar'
import { EnrichmentProgressError } from './enrichment/EnrichmentProgressError'
import { EnrichmentProgressHeader } from './enrichment/EnrichmentProgressHeader'
import { EnrichmentProgressSteps } from './enrichment/EnrichmentProgressSteps'
import { estimateSteps } from './enrichment/enrichmentSteps'
import type { EnrichmentProgressProps } from './enrichment/types'
import { useEnrichmentPolling } from './enrichment/useEnrichmentPolling'

export function EnrichmentProgress({
  projectId,
  task: initialTask,
  onComplete,
  onError,
}: EnrichmentProgressProps) {
  const { task, elapsedMs, error, pollTask, resetPolling } =
    useEnrichmentPolling({
      projectId,
      initialTask,
      onComplete,
      onError,
    })

  const steps = estimateSteps(task, elapsedMs)
  const completedCount = steps.filter((s) => s.status === 'completed').length

  const handleRetry = useCallback(async () => {
    resetPolling()
    await pollTask()
  }, [resetPolling, pollTask])

  return (
    <div className="relative">
      <EnrichmentProgressHeader elapsedMs={elapsedMs} />
      <EnrichmentProgressSteps steps={steps} />
      <EnrichmentProgressBar
        completedCount={completedCount}
        totalSteps={steps.length}
      />
      <EnrichmentProgressError error={error} onRetry={handleRetry} />

      {/* Subtle background glow when active */}
      <div
        className="absolute inset-0 -z-10 opacity-30 pointer-events-none rounded-lg"
        style={{
          background:
            'radial-gradient(ellipse at top, rgba(16, 185, 129, 0.05) 0%, transparent 60%)',
        }}
      />
    </div>
  )
}
