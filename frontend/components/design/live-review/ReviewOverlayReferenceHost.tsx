'use client'

import { attachReviewOverlay } from '@summitflow/review-overlay'
import { useEffect } from 'react'

export interface ReviewOverlayReferenceRequest {
  projectId: string
  summitflowBaseUrl: string
  agentHubEmbedUrl: string
  overlayId?: string
  pageKey?: string
  pageUrlSnapshot?: string
  title?: string
}

interface ReviewOverlayReferenceHostProps {
  request: ReviewOverlayReferenceRequest | null
  getAuthHeaders: () => Promise<Record<string, string>> | Record<string, string>
}

export function ReviewOverlayReferenceHost({
  request,
  getAuthHeaders,
}: ReviewOverlayReferenceHostProps): React.ReactElement | null {
  useEffect(() => {
    if (!request) {
      return
    }

    const handle = attachReviewOverlay({
      projectId: request.projectId,
      summitflowBaseUrl: request.summitflowBaseUrl,
      agentHubEmbedUrl: request.agentHubEmbedUrl,
      getAuthHeaders,
      pageKey: request.pageKey,
      pageUrlSnapshot: request.pageUrlSnapshot,
      overlayId: request.overlayId,
    })
    handle.open()

    return () => {
      handle.destroy()
    }
  }, [request, getAuthHeaders])

  return null
}
