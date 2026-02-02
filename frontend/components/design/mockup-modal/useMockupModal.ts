import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  deleteMockup,
  fetchMockupHistory,
  updateMockupStatus,
  type Mockup,
} from '@/lib/api/mockups'

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
      onOpenChange(false)
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
      if (newStatus === 'rejected' || newStatus === 'archived') {
        onOpenChange(false)
      }
    } catch (error) {
      console.error('Failed to update status:', error)
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
