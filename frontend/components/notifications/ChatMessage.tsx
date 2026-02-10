import { clsx } from 'clsx'
import { Bot, User } from 'lucide-react'
import type { ChatMessage as ChatMessageType } from './types'

interface ChatMessageProps {
  message: ChatMessageType
}

export function ChatMessage({ message }: ChatMessageProps) {
  return (
    <div
      className={clsx(
        'flex gap-3',
        message.role === 'user' ? 'flex-row-reverse' : '',
      )}
    >
      <div
        className={clsx(
          'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0',
          message.role === 'user' ? 'bg-phosphor-500/20' : 'bg-slate-700',
        )}
      >
        {message.role === 'user' ? (
          <User className="w-4 h-4 text-phosphor-400" />
        ) : (
          <Bot className="w-4 h-4 text-slate-400" />
        )}
      </div>
      <div
        className={clsx(
          'max-w-[80%] p-3 rounded-lg text-sm',
          message.role === 'user'
            ? 'bg-phosphor-500/20 text-slate-200'
            : 'bg-slate-800 text-slate-300',
        )}
      >
        <div className="whitespace-pre-wrap">{message.content}</div>
        <span className="text-xs text-slate-500 mt-1 block">
          {message.timestamp.toLocaleTimeString()}
        </span>
      </div>
    </div>
  )
}
