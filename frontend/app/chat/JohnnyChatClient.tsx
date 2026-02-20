'use client'

import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChatPanel } from '@agent-hub/chat-ui'
import type { ChatStreamApiConfig } from '@agent-hub/chat-ui'
import { getVoiceWsUrl, getTtsBaseUrl } from '@/lib/api-config'
import { getAgentHubProxyBase } from '@/components/tasks/useTaskIdeation'
import { fetchNotification, type Notification } from '@/lib/api/notifications'
import { BlockerBanner } from './BlockerBanner'
import { HeartbeatSettings } from './HeartbeatSettings'
import { ResumeBar } from './ResumeBar'

const PROJECT_ID = 'summitflow'
const AGENT_SLUG = 'johnny'
const MEMORY_GROUP_PREFIX = 'summitflow:'

export function JohnnyChatClient() {
  const searchParams = useSearchParams()
  const taskId = searchParams.get('task_id')
  const notificationId = searchParams.get('notification_id')

  const [notification, setNotification] = useState<Notification | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  // Fetch notification context if linked from a push notification
  useEffect(() => {
    if (!notificationId) return
    fetchNotification(PROJECT_ID, notificationId)
      .then(setNotification)
      .catch(() => {}) // Non-critical — chat works without it
  }, [notificationId])

  // Build initial prompt from deep-link context
  const initialPrompt = useMemo(() => {
    if (!taskId) return undefined
    const parts = [`I came from a notification about task ${taskId}.`]
    if (notification?.message) {
      parts.push(`The notification said: "${notification.message}"`)
    }
    parts.push('What happened and what do you recommend?')
    return parts.join(' ')
  }, [taskId, notification])

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
    <div className="flex flex-col h-full">
      <ChatPanel
        agentSlug={AGENT_SLUG}
        toolsEnabled
        initialPrompt={initialPrompt}
        apiConfig={apiConfig}
        modelsEndpoint={`${getAgentHubProxyBase()}/models`}
        voiceWsUrl={voiceWsUrl ?? undefined}
        ttsBaseUrl={ttsBaseUrl ?? undefined}
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
      <div className="flex items-center justify-between px-4 py-2 border-t border-slate-750/60 bg-slate-950/80 backdrop-blur-sm">
        <div className="flex-1">
          {taskId && sessionId && <ResumeBar taskId={taskId} />}
        </div>
        <HeartbeatSettings />
      </div>
    </div>
  )
}
