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
import type { ExplorerType } from '../types'
import { uiTypeToApiType } from '../explorerConstants'
import { explorerKeys } from './useExplorerData'

interface UseExplorerScanReturn {
  isScanning: boolean
  scanProgress: ScanStatusResponse | null
  scanError: string | null
  scanCompletedAt: number | null
  handleScan: () => Promise<void>
}

const POLL_INTERVAL_MS = 500
const SCAN_TIMEOUT_MS = 60000

export function useExplorerScan(
  projectId: string,
  activeType: ExplorerType,
): UseExplorerScanReturn {
  const queryClient = useQueryClient()
  const [isScanning, setIsScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState<ScanStatusResponse | null>(null)
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

  const pollScanStatus = useCallback(async (deadline: number) => {
    try {
      const status = await fetchScanStatus(projectId)
      setScanProgress(status)

      if (status.status === 'completed') {
        setScanCompletedAt(Date.now())
        finishScan()
        void queryClient.invalidateQueries({ queryKey: scanHistoryKeys.all })
        void queryClient.invalidateQueries({
          queryKey: explorerKeys.entries(projectId),
        })
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
  }, [finishScan, projectId, queryClient])

  const handleScan = useCallback(async () => {
    clearPendingPoll()
    setIsScanning(true)
    setScanProgress(null)
    setScanError(null)
    setScanCompletedAt(null)

    try {
      const apiType = uiTypeToApiType[activeType]
      await triggerExplorerScan(
        projectId,
        apiType as 'file' | 'table' | 'task' | 'endpoint' | 'page',
      )
      void pollScanStatus(Date.now() + SCAN_TIMEOUT_MS)
    } catch (err) {
      setScanError(getErrorMessage(err, 'Failed to start scan'))
      finishScan()
    }
  }, [activeType, clearPendingPoll, finishScan, pollScanStatus, projectId])

  useEffect(() => clearPendingPoll, [clearPendingPoll])

  return {
    isScanning,
    scanProgress,
    scanError,
    scanCompletedAt,
    handleScan,
  }
}
