'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
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
    },
    onError: (error: Error) => {
      console.error('Failed to update feedback status:', error.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteFeedbackItem(itemId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['feedback-items'] })
      queryClient.invalidateQueries({ queryKey: ['feedback-summary'] })
      onClose()
    },
    onError: (error: Error) => {
      console.error('Failed to delete feedback item:', error.message)
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
      />
    </div>
  )
}
