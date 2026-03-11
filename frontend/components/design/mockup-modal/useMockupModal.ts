import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import {
  deleteMockup,
  fetchMockupHistory,
  updateMockupStatus,
  type Mockup,
} from '@/lib/api/mockups'
import { getErrorMessage } from '@/lib/utils'

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
    history,
    deleteMutation,
    setShowHistory,
    setShowComparison,
    setShowDeleteConfirm,
    handleStatusChange,
  }
}
