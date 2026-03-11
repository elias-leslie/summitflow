'use client'

import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChatPanel } from '@agent-hub/chat-ui'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import { getVoiceWsUrl, getTtsBaseUrl } from '@/lib/api-config'
import { buildAgentHubChatApiConfig } from '@/lib/agent-hub-chat-config'
import { fetchNotification, type Notification } from '@/lib/api/notifications'
import { usePersonaName } from '@/hooks/usePersonaName'
import { getChatProjectId } from './chat-routing'
import { BlockerBanner } from './BlockerBanner'
import { ResumeBar } from './ResumeBar'

const AGENT_SLUG = 'persona'

export function PersonaChatClient() {
  const searchParams = useSearchParams()
  const projectId = getChatProjectId(searchParams)
  const taskId = searchParams.get('task_id')
  const notificationId = searchParams.get('notification_id')
  const personaName = usePersonaName()

  const [notification, setNotification] = useState<Notification | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  // Fetch notification context if linked from a push notification
  useEffect(() => {
    if (!notificationId) return
    fetchNotification(projectId, notificationId)
      .then(setNotification)
      .catch(() => {}) // Non-critical — chat works without it
  }, [notificationId, projectId])

  const agentHubProxyBase = getAgentHubProxyBase()

  const apiConfig = useMemo(
    () =>
      buildAgentHubChatApiConfig({
        proxyBase: agentHubProxyBase,
        projectId,
      }),
    [agentHubProxyBase, projectId],
  )

  const voiceWsUrl = getVoiceWsUrl()
  const ttsBaseUrl = getTtsBaseUrl()

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
          modelsEndpoint={`${agentHubProxyBase}/models`}
          voiceWsUrl={voiceWsUrl ?? undefined}
          ttsBaseUrl={ttsBaseUrl ?? undefined}
          title={personaName}
          renderBanner={
            taskId
              ? () => (
                  <BlockerBanner
                    projectId={projectId}
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
          <ResumeBar
            projectId={projectId}
            taskId={taskId}
            personaName={personaName}
          />
        </div>
      )}
    </div>
  )
}
