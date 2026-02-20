'use client'

import { useMemo } from 'react'
import { AlertCircle, X } from 'lucide-react'
import { ChatPanel } from '@agent-hub/chat-ui'
import type { ChatStreamApiConfig } from '@agent-hub/chat-ui'
import type { Notification } from '@/lib/api'
import { getAgentHubProxyBase } from '@/components/tasks/useTaskIdeation'
import { TaskDetailsPanel } from './TaskDetailsPanel'
import { useTaskDetails } from './useTaskDetails'

const PROJECT_ID = 'summitflow'
const AGENT_SLUG = 'johnny'
const MEMORY_GROUP_PREFIX = 'summitflow:'

interface NotificationDetailModalProps {
  notification: Notification | null
  projectId: string
  onClose: () => void
}

export function NotificationDetailModal({
  notification,
  projectId,
  onClose,
}: NotificationDetailModalProps) {
  const { taskDetails, loading } = useTaskDetails(notification, projectId)

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

  // Build initial prompt from notification context
  const initialPrompt = useMemo(() => {
    if (!notification) return undefined
    const parts: string[] = []
    if (notification.task_id) {
      parts.push(`I came from a notification about task ${notification.task_id}.`)
    }
    if (notification.message) {
      parts.push(`The notification said: "${notification.message}"`)
    }
    parts.push('What happened and what do you recommend?')
    return parts.join(' ')
  }, [notification])

  if (!notification) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-2xl h-[85vh] bg-slate-900 border border-slate-700 rounded-lg shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 bg-slate-900/50 flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
            <div className="min-w-0">
              <h2 className="text-sm font-medium text-slate-200 truncate">
                {notification.title}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {notification.task_id || 'No linked task'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="btn-ghost p-2 rounded-lg flex-shrink-0"
            title="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Task Details (collapsible top section) */}
        <div className="max-h-[30%] min-h-[100px] border-b border-slate-700 overflow-auto p-4 flex-shrink-0">
          <TaskDetailsPanel
            loading={loading}
            taskDetails={taskDetails}
            notification={notification}
          />
        </div>

        {/* Real Johnny Chat */}
        <div className="flex-1 min-h-0">
          <ChatPanel
            agentSlug={AGENT_SLUG}
            toolsEnabled
            initialPrompt={initialPrompt}
            apiConfig={apiConfig}
            title="Johnny"
          />
        </div>
      </div>
    </div>
  )
}
