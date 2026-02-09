/**
 * useExplorerStats - Hook for fetching and managing explorer statistics
 */

import { useEffect, useState } from 'react'
import { fetchExplorerEntries } from '@/lib/api/explorer'
import type { ExplorerStats, ExplorerType } from '../types'
import { explorerTypes, uiTypeToApiType } from '../explorerConstants'

interface UseExplorerStatsReturn {
  statsData: Record<ExplorerType, ExplorerStats>
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

  const fetchAllStats = async () => {
    const newStats: Record<ExplorerType, ExplorerStats> = {
      files: { ...emptyStats },
      database: { ...emptyStats },
      celery: { ...emptyStats },
      api: { ...emptyStats },
      pages: { ...emptyStats },
      dependencies: { ...emptyStats },
      architecture: { ...emptyStats },
    }

    for (const type of explorerTypes) {
      try {
        const apiType = uiTypeToApiType[type]
        const response = await fetchExplorerEntries(projectId, {
          type: apiType,
          limit: 1, // Just need stats, not entries
        })

        // Map API health statuses to UI stats
        const byHealth = response.stats?.byHealth || {}
        newStats[type] = {
          total: response.total || 0,
          fresh: (byHealth.healthy || 0) as number,
          stale: (byHealth.warning || 0) as number,
          orphan: (byHealth.error || 0) as number,
          lastScan: response.stats?.lastScanned || null,
        }
      } catch (err) {
        console.error(`Failed to fetch stats for ${type}:`, err)
      }
    }

    setStatsData(newStats)
  }

  useEffect(() => {
    fetchAllStats()
  }, [projectId])

  return {
    statsData,
    refetchStats: fetchAllStats,
  }
}
