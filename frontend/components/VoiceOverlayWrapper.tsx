'use client'

import { VoiceOverlay } from '@agent-hub/passport-client'
import { useEffect, useState } from 'react'
import { getVoiceWsUrl } from '@/lib/api-config'

/**
 * Wrapper for VoiceOverlay that conditionally renders based on env config.
 * Uses api-config to determine the correct WebSocket URL for the current environment.
 *
 * Uses client-side only rendering to avoid hydration mismatch since
 * getVoiceWsUrl() depends on window.location which differs server vs client.
 */
export function VoiceOverlayWrapper() {
  const [voiceUrl, setVoiceUrl] = useState<string | null>(null)

  useEffect(() => {
    setVoiceUrl(getVoiceWsUrl())
  }, [])

  // Voice not configured or not yet determined - don't render
  if (!voiceUrl) {
    return null
  }

  return <VoiceOverlay wsUrl={voiceUrl} />
}
