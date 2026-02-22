'use client'

import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChatPanel } from '@agent-hub/chat-ui'
import type { ChatStreamApiConfig } from '@agent-hub/chat-ui'
import { getVoiceWsUrl, getTtsBaseUrl } from '@/lib/api-config'
import { getAgentHubProxyBase } from '@/components/tasks/useTaskIdeation'
import { fetchNotification, type Notification } from '@/lib/api/notifications'
import { usePersonaName } from '@/hooks/usePersonaName'
import { BlockerBanner } from './BlockerBanner'
import { ResumeBar } from './ResumeBar'

const PROJECT_ID = 'summitflow'
const AGENT_SLUG = 'persona'
const MEMORY_GROUP_PREFIX = 'summitflow:'

export function PersonaChatClient() {
  const searchParams = useSearchParams()
  const taskId = searchParams.get('task_id')
  const notificationId = searchParams.get('notification_id')
  const personaName = usePersonaName()

  const [notification, setNotification] = useState<Notification | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

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
          title={personaName}
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
      {taskId && sessionId && (
        <div className="px-3 sm:px-4 py-2 border-t border-slate-800 bg-slate-950/80 backdrop-blur-sm flex-shrink-0">
          <ResumeBar taskId={taskId} personaName={personaName} />
        </div>
      )}
    </div>
  )
}
