/**
 * useExplorerScan - Hook for managing explorer scan operations
 */

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchScanStatus,
  type ScanStatusResponse,
  triggerExplorerScan,
} from '@/lib/api/explorer-scan'
import { scanHistoryKeys } from '@/lib/hooks/useScanHistory'
import { getErrorMessage } from '@/lib/utils'
import { uiTypeToApiType } from '../explorerConstants'
import type { ExplorerType } from '../types'
import { explorerKeys } from './useExplorerData'
import { overviewKeys } from './useExplorerOverview'

interface UseExplorerScanReturn {
  isScanning: boolean
  scanProgress: ScanStatusResponse | null
  scanError: string | null
  scanCompletedAt: number | null
  handleScan: () => Promise<void>
  handleFullScan: () => Promise<void>
}

const POLL_INTERVAL_MS = 2000
const SCAN_TIMEOUT_MS = 5 * 60 * 1000
type ScanTriggerType = Parameters<typeof triggerExplorerScan>[1]

export function useExplorerScan(
  projectId: string,
  activeType: ExplorerType,
): UseExplorerScanReturn {
  const queryClient = useQueryClient()
  const [isScanning, setIsScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState<ScanStatusResponse | null>(
    null,
  )
  const [scanError, setScanError] = useState<string | null>(null)
  const [scanCompletedAt, setScanCompletedAt] = useState<number | null>(null)
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearPendingPoll = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current)
      pollTimeoutRef.current = null
    }
  }, [])

  const finishScan = useCallback(() => {
    clearPendingPoll()
    setIsScanning(false)
    setScanProgress(null)
  }, [clearPendingPoll])

  const pollScanStatus = useCallback(
    async (deadline: number) => {
      try {
        const status = await fetchScanStatus(projectId)
        setScanProgress(status)

        if (status.status === 'completed') {
          setScanCompletedAt(Date.now())
          finishScan()
          void Promise.all([
            queryClient.invalidateQueries({ queryKey: scanHistoryKeys.all }),
            queryClient.invalidateQueries({ queryKey: overviewKeys.all }),
            queryClient.invalidateQueries({
              queryKey: explorerKeys.entries(projectId),
            }),
            queryClient.invalidateQueries({
              queryKey: explorerKeys.stats(projectId),
            }),
          ])
          return
        }

        if (status.status === 'failed') {
          setScanError(status.error || 'Scan failed')
          finishScan()
          return
        }

        if (Date.now() >= deadline) {
          setScanError('Scan timed out')
          finishScan()
          return
        }

        pollTimeoutRef.current = setTimeout(() => {
          void pollScanStatus(deadline)
        }, POLL_INTERVAL_MS)
      } catch (pollErr) {
        setScanError(getErrorMessage(pollErr, 'Failed to poll scan status'))
        finishScan()
      }
    },
    [finishScan, projectId, queryClient],
  )

  const startScan = useCallback(
    async (scanType?: ScanTriggerType) => {
      clearPendingPoll()
      setIsScanning(true)
      setScanProgress(null)
      setScanError(null)
      setScanCompletedAt(null)

      try {
        await triggerExplorerScan(projectId, scanType)
        void pollScanStatus(Date.now() + SCAN_TIMEOUT_MS)
      } catch (err) {
        setScanError(getErrorMessage(err, 'Failed to start scan'))
        finishScan()
      }
    },
    [clearPendingPoll, finishScan, pollScanStatus, projectId],
  )

  const handleScan = useCallback(async () => {
    const apiType = uiTypeToApiType[activeType]
    await startScan(apiType)
  }, [activeType, startScan])

  const handleFullScan = useCallback(async () => {
    await startScan(undefined)
  }, [startScan])

  useEffect(() => {
    let cancelled = false

    async function resumeScanIfNeeded() {
      try {
        const status = await fetchScanStatus(projectId)
        if (cancelled || status.status !== 'running') {
          return
        }
        setIsScanning(true)
        setScanProgress(status)
        void pollScanStatus(Date.now() + SCAN_TIMEOUT_MS)
      } catch {
        // Ignore bootstrap polling failures; explicit scan actions surface errors.
      }
    }

    void resumeScanIfNeeded()
    return () => {
      cancelled = true
      clearPendingPoll()
    }
  }, [clearPendingPoll, pollScanStatus, projectId])

  return {
    isScanning,
    scanProgress,
    scanError,
    scanCompletedAt,
    handleScan,
    handleFullScan,
  }
}
