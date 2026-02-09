/**
 * useExplorerScan - Hook for managing explorer scan operations
 */

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import {
  fetchScanStatus,
  type ScanStatusResponse,
  triggerExplorerScan,
} from '@/lib/api/explorer-scan'
import { scanHistoryKeys } from '@/lib/hooks/useScanHistory'
import type { ExplorerType } from '../types'
import { uiTypeToApiType } from '../explorerConstants'
import { explorerKeys } from './useExplorerData'

interface UseExplorerScanReturn {
  isScanning: boolean
  scanProgress: ScanStatusResponse | null
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

  const handleScan = useCallback(async () => {
    setIsScanning(true)
    setScanProgress(null)

    try {
      const apiType = uiTypeToApiType[activeType]
      await triggerExplorerScan(
        projectId,
        apiType as 'file' | 'table' | 'task' | 'endpoint' | 'page',
      )

      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const status = await fetchScanStatus(projectId)
          setScanProgress(status)

          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval)
            setIsScanning(false)
            setScanProgress(null)

            // Invalidate caches to update UI
            queryClient.invalidateQueries({ queryKey: scanHistoryKeys.all })
            queryClient.invalidateQueries({
              queryKey: explorerKeys.entries(projectId),
            })
            queryClient.invalidateQueries({
              queryKey: explorerKeys.stats(projectId),
            })

            if (status.status === 'failed' && status.error) {
              console.error('Scan completed with error:', status.error)
            }
          }
        } catch (pollErr) {
          console.error('Poll failed:', pollErr)
          clearInterval(pollInterval)
          setIsScanning(false)
          setScanProgress(null)
        }
      }, POLL_INTERVAL_MS)

      // Safety timeout
      setTimeout(() => {
        clearInterval(pollInterval)
        setIsScanning(false)
        setScanProgress(null)
      }, SCAN_TIMEOUT_MS)
    } catch (err) {
      console.error('Scan failed:', err)
      setIsScanning(false)
      setScanProgress(null)
    }
  }, [projectId, activeType, queryClient])

  return {
    isScanning,
    scanProgress,
    handleScan,
  }
}
