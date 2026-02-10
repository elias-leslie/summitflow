import { Bot, Loader2 } from 'lucide-react'
import type { RefObject } from 'react'
import { ChatInput } from './ChatInput'
import { ChatMessage } from './ChatMessage'
import type { ChatMessage as ChatMessageType } from './types'

interface ChatPanelProps {
  messages: ChatMessageType[]
  sending: boolean
  chatEndRef: RefObject<HTMLDivElement | null>
  onSendMessage: (message: string) => void
}

export function ChatPanel({
  messages,
  sending,
  chatEndRef,
  onSendMessage,
}: ChatPanelProps) {
  return (
    <div className="h-3/5 flex flex-col min-h-0">
      {/* Chat Messages */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.map((msg, index) => (
          <ChatMessage key={index} message={msg} />
        ))}
        {sending && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center">
              <Bot className="w-4 h-4 text-slate-400" />
            </div>
            <div className="bg-slate-800 p-3 rounded-lg">
              <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
            </div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Chat Input */}
      <ChatInput onSend={onSendMessage} disabled={sending} />
    </div>
  )
}
