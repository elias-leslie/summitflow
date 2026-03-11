'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import {
  deleteFeedbackItem,
  fetchFeedbackItem,
  type FeedbackStatus,
  updateFeedbackStatus,
} from '@/lib/api/feedback'
import { FeedbackDetailActions } from './FeedbackDetailActions'
import { FeedbackDetailBody } from './FeedbackDetailBody'
import { FeedbackDetailHeader } from './FeedbackDetailHeader'

// ============================================================================
// Component
// ============================================================================

interface FeedbackDetailProps {
  itemId: string
  onClose: () => void
}

export function FeedbackDetail({ itemId, onClose }: FeedbackDetailProps) {
  const queryClient = useQueryClient()
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const { data: item, isLoading } = useQuery({
    queryKey: ['feedback-item', itemId],
    queryFn: () => fetchFeedbackItem(itemId),
  })

  const statusMutation = useMutation({
    mutationFn: (data: { status: FeedbackStatus; resolution_note?: string }) =>
      updateFeedbackStatus(itemId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback-item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['feedback-items'] })
      queryClient.invalidateQueries({ queryKey: ['feedback-summary'] })
      toast.success('Feedback updated')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update feedback')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteFeedbackItem(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback-item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['feedback-items'] })
      queryClient.invalidateQueries({ queryKey: ['feedback-summary'] })
      toast.success('Feedback deleted')
      setShowDeleteConfirm(false)
      onClose()
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to delete feedback')
    },
  })

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
      </div>
    )
  }

  if (!item) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-slate-500">
        Feedback item not found
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <FeedbackDetailHeader
        feedbackType={item.feedback_type}
        componentId={item.component_id}
        title={item.title}
        onClose={onClose}
      />
      <FeedbackDetailBody item={item} />
      <FeedbackDetailActions
        currentStatus={item.status}
        statusMutation={statusMutation}
        deleteMutation={deleteMutation}
        onDelete={() => setShowDeleteConfirm(true)}
      />
      {showDeleteConfirm && (
        <ConfirmDeleteDialog
          entityType="feedback"
          entityName={item.title}
          isDeleting={deleteMutation.isPending}
          isError={deleteMutation.isError}
          onConfirm={() => deleteMutation.mutate()}
          onCancel={() => setShowDeleteConfirm(false)}
        />
      )}
    </div>
  )
}
