'use client'

import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Volume2, VolumeX } from 'lucide-react'
import { ChatPanel } from '@agent-hub/chat-ui'
import type { ChatStreamApiConfig } from '@agent-hub/chat-ui'
import { getVoiceWsUrl, getTtsBaseUrl } from '@/lib/api-config'
import { getAgentHubProxyBase } from '@/components/tasks/useTaskIdeation'
import { fetchNotification, type Notification } from '@/lib/api/notifications'
import { BlockerBanner } from './BlockerBanner'
import { HeartbeatSettings } from './HeartbeatSettings'
import { ResumeBar } from './ResumeBar'

const TTS_STORAGE_KEY = 'johnny-tts-enabled'

const PROJECT_ID = 'summitflow'
const AGENT_SLUG = 'johnny'
const MEMORY_GROUP_PREFIX = 'summitflow:'

export function JohnnyChatClient() {
  const searchParams = useSearchParams()
  const taskId = searchParams.get('task_id')
  const notificationId = searchParams.get('notification_id')

  const [notification, setNotification] = useState<Notification | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem(TTS_STORAGE_KEY) === 'true'
  })

  const toggleTts = useCallback(() => {
    setTtsEnabled(prev => {
      const next = !prev
      localStorage.setItem(TTS_STORAGE_KEY, String(next))
      return next
    })
  }, [])

  // Fetch notification context if linked from a push notification
  useEffect(() => {
    if (!notificationId) return
    fetchNotification(PROJECT_ID, notificationId)
      .then(setNotification)
      .catch(() => {}) // Non-critical — chat works without it
  }, [notificationId])

  const apiConfig: ChatStreamApiConfig = useMemo(() => {
    const proxyBase = getAgentHubProxyBase()
    return {
      completeEndpoint: `${proxyBase}/complete`,
      sessionsEndpoint: `${proxyBase}/sessions`,
      preferencesEndpoint: `${proxyBase}/preferences`,
      projectId: PROJECT_ID,
      memoryGroupPrefix: MEMORY_GROUP_PREFIX,
    }
  }, [])

  const voiceWsUrl = useMemo(() => getVoiceWsUrl(), [])
  const ttsBaseUrl = useMemo(() => getTtsBaseUrl(), [])

  const handleSessionCreated = useCallback((id: string) => {
    setSessionId(id)
  }, [])

  return (
    <div className="flex flex-col h-[calc(100dvh-4rem)] bg-slate-950 chat-outrun">
      <div className="flex-1 min-h-0">
        <ChatPanel
          agentSlug={AGENT_SLUG}
          toolsEnabled
          apiConfig={apiConfig}
          modelsEndpoint={`${getAgentHubProxyBase()}/models`}
          voiceWsUrl={voiceWsUrl ?? undefined}
          ttsBaseUrl={ttsBaseUrl ?? undefined}
          alwaysSpeak={ttsEnabled}
          title="Johnny"
          renderBanner={
            taskId
              ? () => (
                  <BlockerBanner
                    taskId={taskId}
                    notification={notification}
                  />
                )
              : undefined
          }
          onSessionCreated={handleSessionCreated}
        />
      </div>
      <div className="flex items-center justify-between gap-2 px-3 sm:px-4 py-2 border-t border-slate-800 bg-slate-950/80 backdrop-blur-sm flex-shrink-0">
        <div className="flex-1 min-w-0">
          {taskId && sessionId && <ResumeBar taskId={taskId} />}
        </div>
        <button
          onClick={toggleTts}
          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title={ttsEnabled ? 'Disable auto-speak' : 'Enable auto-speak'}
        >
          {ttsEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
        </button>
        <HeartbeatSettings />
      </div>
    </div>
  )
}
