'use client'

import {
  type ChatMessage,
  groupMessages,
  MessageBubble,
} from '@agent-hub/chat-ui'
import { useEffect, useRef } from 'react'
import { MockupMentionCards } from './mockup-mentions'
import type { MockupEditorTarget, WorkChatPane } from './types'

export function WorkChatMessageList({
  messages,
  isStreaming,
  pane,
  onEditMessage,
  onRegenerateMessage,
  onOpenMockup,
}: {
  messages: ChatMessage[]
  isStreaming: boolean
  pane: WorkChatPane
  onEditMessage?: (messageId: string, newContent: string) => void
  onRegenerateMessage?: (messageId: string) => void
  onOpenMockup: (target: MockupEditorTarget) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!messages.length) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-500">
        <p>Start a conversation</p>
      </div>
    )
  }

  const groupedMessages = groupMessages(messages)

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {groupedMessages.map((item, index) => {
        if (Array.isArray(item)) {
          return (
            <div
              key={item[0].responseGroupId}
              className="flex flex-col gap-3 md:flex-row"
            >
              {item.map((message) => (
                <div key={message.id} className="min-w-0 flex-1">
                  <MessageBubble
                    message={message}
                    isStreaming={
                      isStreaming &&
                      message.role === 'assistant' &&
                      !message.content
                    }
                    onEdit={onEditMessage}
                    onRegenerate={onRegenerateMessage}
                    canEdit={!isStreaming}
                    canRegenerate={!isStreaming}
                    canContinue={!isStreaming}
                  />
                  <MockupMentionCards
                    content={message.content}
                    projectId={pane.projectId}
                    paneId={pane.id}
                    onOpenMockup={onOpenMockup}
                  />
                </div>
              ))}
            </div>
          )
        }

        const message = item
        const isLastMessage = index === groupedMessages.length - 1
        return (
          <div key={message.id}>
            <MessageBubble
              message={message}
              isStreaming={
                isStreaming && message.role === 'assistant' && isLastMessage
              }
              onEdit={onEditMessage}
              onRegenerate={onRegenerateMessage}
              canEdit={!isStreaming}
              canRegenerate={!isStreaming}
              canContinue={!isStreaming}
            />
            <MockupMentionCards
              content={message.content}
              projectId={pane.projectId}
              paneId={pane.id}
              onOpenMockup={onOpenMockup}
            />
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
