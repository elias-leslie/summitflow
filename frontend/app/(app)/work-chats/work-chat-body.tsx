'use client'

import {
  type ChatMessage,
  MessageInput,
  type StreamStatus,
  useChatStream,
} from '@agent-hub/chat-ui'
import { useCallback, useEffect, useRef } from 'react'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import { buildWorkChatApiConfig } from '@/lib/api/agent-hub-work-chats'
import { WorkChatMessageList } from './work-chat-message-list'
import type { MockupEditorTarget, WorkChatController, WorkChatPane, WorkStartCommand } from './types'

export function WorkChatBody({
  pane,
  apiConfig,
  workingDir,
  startCommand,
  onOpenMockup,
  onRuntimeChange,
  onMessagesChange,
  onTurnFinished,
  onControllerReady,
  onSessionCreated,
}: {
  pane: WorkChatPane
  apiConfig: ReturnType<typeof buildWorkChatApiConfig>
  workingDir?: string
  startCommand?: WorkStartCommand
  onOpenMockup: (target: MockupEditorTarget) => void
  onRuntimeChange: (state: {
    status: StreamStatus
    error: string | null
  }) => void
  onMessagesChange?: (messages: ChatMessage[]) => void
  onTurnFinished?: () => void
  onControllerReady?: (controller: WorkChatController) => void
  onSessionCreated: (sessionId: string) => void
}) {
  const {
    messages,
    status,
    error,
    currentSessionId,
    sendMessage,
    cancelStream,
    editMessage,
    regenerateMessage,
  } = useChatStream({
    agentSlug: pane.agentSlug,
    sessionId: pane.sessionId ?? undefined,
    workingDir,
    toolsEnabled: true,
    apiConfig,
  })
  const lastNotifiedSessionId = useRef<string | null>(null)
  const lastAutoSendKey = useRef<number | null>(null)
  const previousStatus = useRef<StreamStatus>('idle')
  const turnInFlight = useRef(false)

  const sendTurn = useCallback(
    (content: string, targetModels?: string[]) => {
      turnInFlight.current = true
      sendMessage(content, targetModels)
    },
    [sendMessage],
  )

  useEffect(() => {
    onRuntimeChange({ status, error })
  }, [error, onRuntimeChange, status])

  useEffect(() => {
    onMessagesChange?.(messages)
  }, [messages, onMessagesChange])

  useEffect(() => {
    onControllerReady?.({
      sendMessage: (content: string) => sendTurn(content),
      cancelStream,
      sessionId: currentSessionId,
      status,
    })
  }, [cancelStream, currentSessionId, onControllerReady, sendTurn, status])

  useEffect(() => {
    const wasActive =
      previousStatus.current === 'streaming' ||
      previousStatus.current === 'connecting' ||
      previousStatus.current === 'reconnecting' ||
      previousStatus.current === 'cancelling'
    if (wasActive && status === 'idle' && turnInFlight.current) {
      turnInFlight.current = false
      onTurnFinished?.()
    }
    if (status === 'error') {
      turnInFlight.current = false
    }
    previousStatus.current = status
  }, [onTurnFinished, status])

  useEffect(() => {
    if (
      !currentSessionId ||
      currentSessionId === lastNotifiedSessionId.current
    ) {
      return
    }
    lastNotifiedSessionId.current = currentSessionId
    onSessionCreated(currentSessionId)
  }, [currentSessionId, onSessionCreated])

  useEffect(() => {
    if (!startCommand || lastAutoSendKey.current === startCommand.key) return
    if (status !== 'idle' && status !== 'error') return
    lastAutoSendKey.current = startCommand.key
    sendTurn(startCommand.prompt)
  }, [sendTurn, startCommand, status])

  const isStreaming =
    status === 'streaming' ||
    status === 'reconnecting' ||
    status === 'cancelling' ||
    status === 'connecting'

  return (
    <div className="flex h-full min-h-0 flex-col chat-outrun">
      {error ? (
        <div className="shrink-0 border-b border-rose-500/20 bg-rose-500/10 px-3 py-1 text-xs text-rose-300">
          {error}
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <WorkChatMessageList
          messages={messages}
          isStreaming={isStreaming}
          pane={pane}
          onEditMessage={editMessage}
          onRegenerateMessage={regenerateMessage}
          onOpenMockup={onOpenMockup}
        />
      </div>
      <div className="shrink-0 border-t border-slate-800 bg-slate-950/85">
        <MessageInput
          onSend={(message, targetModels) => sendTurn(message, targetModels)}
          onCancel={cancelStream}
          status={status}
          compact
          allowModelMentions={false}
          preferencesEndpoint={`${getAgentHubProxyBase()}/preferences`}
        />
      </div>
    </div>
  )
}
