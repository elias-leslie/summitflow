'use client'

import { VoiceOverlay } from '@agent-hub/passport-client'
import { getVoiceWsUrl } from '@/lib/api-config'

/**
 * Wrapper for VoiceOverlay that conditionally renders based on env config.
 * Uses api-config to determine the correct WebSocket URL for the current environment.
 */
export function VoiceOverlayWrapper() {
  const voiceUrl = getVoiceWsUrl()

  // Voice not configured - don't render
  if (!voiceUrl) {
    return null
  }

  return <VoiceOverlay wsUrl={voiceUrl} />
}
