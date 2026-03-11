/**
 * useExplorerStats - Hook for fetching and managing explorer statistics
 */

import { useCallback, useEffect, useState } from 'react'
import { fetchExplorerEntries } from '@/lib/api/explorer'
import { getErrorMessage } from '@/lib/utils'
import type { ExplorerStats, ExplorerType } from '../types'
import { explorerTypes, uiTypeToApiType } from '../explorerConstants'

interface UseExplorerStatsReturn {
  statsData: Record<ExplorerType, ExplorerStats>
  statsError: string | null
  refetchStats: () => Promise<void>
}

const emptyStats: ExplorerStats = {
  total: 0,
  fresh: 0,
  stale: 0,
  orphan: 0,
  lastScan: null,
}

const initialStatsData: Record<ExplorerType, ExplorerStats> = {
  files: { ...emptyStats },
  database: { ...emptyStats },
  celery: { ...emptyStats },
  api: { ...emptyStats },
  pages: { ...emptyStats },
  dependencies: { ...emptyStats },
  architecture: { ...emptyStats },
}

export function useExplorerStats(projectId: string): UseExplorerStatsReturn {
  const [statsData, setStatsData] = useState<Record<ExplorerType, ExplorerStats>>(
    initialStatsData,
  )
  const [statsError, setStatsError] = useState<string | null>(null)

  const fetchAllStats = useCallback(async () => {
    setStatsError(null)
    const results = await Promise.allSettled(
      explorerTypes.map(async (type) => {
        const apiType = uiTypeToApiType[type]
        const response = await fetchExplorerEntries(projectId, {
          type: apiType,
          limit: 1,
        })

        const byHealth = response.stats?.byHealth || {}
        return [
          type,
          {
            total: response.total || 0,
            fresh: (byHealth.healthy || 0) as number,
            stale: (byHealth.warning || 0) as number,
            orphan: (byHealth.error || 0) as number,
            lastScan: response.stats?.lastScanned || null,
          },
        ] as const
      }),
    )

    const newStats = { ...initialStatsData }
    const failedTypes: string[] = []
    let firstError: string | null = null

    results.forEach((result, index) => {
      const type = explorerTypes[index]
      if (result.status === 'fulfilled') {
        const [resolvedType, stats] = result.value
        newStats[resolvedType] = stats
        return
      }

      failedTypes.push(type)
      firstError ??= getErrorMessage(
        result.reason,
        `Failed to load ${type} stats`,
      )
    })

    setStatsData(newStats)
    if (failedTypes.length > 1) {
      setStatsError(`Failed to load stats for ${failedTypes.join(', ')}`)
    } else if (firstError) {
      setStatsError(firstError)
    }
  }, [projectId])

  useEffect(() => {
    void fetchAllStats()
  }, [fetchAllStats])

  return {
    statsData,
    statsError,
    refetchStats: fetchAllStats,
  }
}
