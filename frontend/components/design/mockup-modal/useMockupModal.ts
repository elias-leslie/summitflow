import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import {
  deleteMockup,
  fetchMockupHistory,
  type Mockup,
  updateMockupStatus,
} from '@/lib/api/mockups'
import { getErrorMessage } from '@/lib/utils'

const DETAILS_STORAGE_KEY = 'mockup-modal-details-shown'

function readDetailsPref(): boolean {
  if (typeof window === 'undefined') return true
  try {
    return window.localStorage.getItem(DETAILS_STORAGE_KEY) !== 'false'
  } catch {
    return true
  }
}

export function useMockupModal(
  mockup: Mockup,
  projectId: string,
  open: boolean,
  onOpenChange: (open: boolean) => void,
  onStatusChange: () => void,
) {
  const [updating, setUpdating] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showComparison, setShowComparison] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [showRerunDialog, setShowRerunDialog] = useState(false)
  const [showDetails, setShowDetailsState] = useState<boolean>(readDetailsPref)

  const setShowDetails = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      setShowDetailsState((prev) => {
        const value = typeof next === 'function' ? next(prev) : next
        try {
          window.localStorage.setItem(DETAILS_STORAGE_KEY, String(value))
        } catch {
          // ignore storage failures
        }
        return value
      })
    },
    [],
  )

  const queryClient = useQueryClient()

  const deleteMutation = useMutation({
    mutationFn: () => deleteMockup(projectId, mockup.mockup_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
      queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      toast.success('Mockup deleted')
      onOpenChange(false)
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to delete mockup'))
    },
  })

  const { data: history } = useQuery({
    queryKey: ['mockup-history', projectId, mockup.mockup_id],
    queryFn: () => fetchMockupHistory(projectId, mockup.mockup_id),
    enabled: open && showHistory,
  })

  const handleStatusChange = async (newStatus: string) => {
    setUpdating(true)
    try {
      await updateMockupStatus(
        projectId,
        mockup.mockup_id,
        newStatus,
        newStatus === 'approved' ? 'user' : undefined,
      )
      onStatusChange()
      toast.success('Mockup status updated')
      if (newStatus === 'rejected' || newStatus === 'archived') {
        onOpenChange(false)
      }
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to update mockup status'))
    } finally {
      setUpdating(false)
    }
  }

  return {
    updating,
    showHistory,
    showComparison,
    showDeleteConfirm,
    showRerunDialog,
    showDetails,
    history,
    deleteMutation,
    setShowHistory,
    setShowComparison,
    setShowDeleteConfirm,
    setShowRerunDialog,
    setShowDetails,
    handleStatusChange,
  }
}
