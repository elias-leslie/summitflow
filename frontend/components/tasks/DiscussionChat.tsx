'use client'

import { AlertCircle, Bot, Loader2, RefreshCw, Send, User } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { type DiscussionMessage, discussTask, type Task } from '@/lib/api/tasks'

interface IdentifiedMessage extends DiscussionMessage {
  _key: string
}
import { getErrorMessage } from '@/lib/utils'

interface DiscussionChatProps {
  projectId: string
  taskId: string
  initialHistory?: DiscussionMessage[]
  onTaskUpdated?: (task: Task) => void
}

export function DiscussionChat({
  projectId,
  taskId,
  initialHistory = [],
  onTaskUpdated,
}: DiscussionChatProps) {
  const idPrefix = useId()
  const nextId = useRef(0)
  const makeKey = () => `${idPrefix}-${nextId.current++}`
  const [messages, setMessages] = useState<IdentifiedMessage[]>(
    initialHistory.map((m) => ({ ...m, _key: `init-${nextId.current++}` })),
  )
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [scrollToBottom])

  const handleSend = async () => {
    const trimmedInput = input.trim()
    if (!trimmedInput || isLoading) return

    const userMessage: IdentifiedMessage = {
      role: 'user',
      content: trimmedInput,
      timestamp: new Date().toISOString(),
      _key: makeKey(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsLoading(true)
    setError(null)

    try {
      const response = await discussTask(projectId, taskId, trimmedInput)

      // Add agent response
      const agentMessage: IdentifiedMessage = {
        role: 'assistant',
        content: response.response,
        timestamp: new Date().toISOString(),
        _key: makeKey(),
      }
      setMessages((prev) => [...prev, agentMessage])

      // If task was updated, notify parent
      if (response.updated_task && onTaskUpdated) {
        onTaskUpdated(response.updated_task)
      }
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to send message'))
      // Remove the user message on error
      setMessages((prev) => prev.slice(0, -1))
      setInput(trimmedInput) // Restore input
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleRetry = () => {
    setError(null)
    handleSend()
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto min-h-0 p-4 space-y-4">
        {messages.length === 0 && !isLoading && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center py-8">
              <Bot className="w-10 h-10 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-500">
                Ask questions or request changes to the task
              </p>
              <p className="text-xs text-slate-600 mt-1">
                e.g., &quot;Should this also add tests?&quot;
              </p>
            </div>
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {messages.map((message) => (
            <motion.div
              key={message._key}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              {/* Avatar */}
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${
                  message.role === 'user'
                    ? 'bg-phosphor-500/20'
                    : 'bg-slate-800'
                }`}
              >
                {message.role === 'user' ? (
                  <User className="w-3.5 h-3.5 text-phosphor-400" />
                ) : (
                  <Bot className="w-3.5 h-3.5 text-slate-400" />
                )}
              </div>

              {/* Message Bubble */}
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 ${
                  message.role === 'user'
                    ? 'bg-phosphor-600/20 text-phosphor-100'
                    : 'bg-slate-800 text-slate-200'
                }`}
              >
                <p className="text-sm whitespace-pre-wrap leading-relaxed">
                  {message.content}
                </p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Typing Indicator */}
        <AnimatePresence>
          {isLoading && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex gap-3"
            >
              <div className="w-7 h-7 rounded-full bg-slate-800 flex items-center justify-center">
                <Bot className="w-3.5 h-3.5 text-slate-400" />
              </div>
              <div className="bg-slate-800 rounded-lg px-4 py-3">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <motion.div
                      key={i}
                      className="w-2 h-2 rounded-full bg-slate-600"
                      animate={{
                        y: [0, -4, 0],
                        opacity: [0.5, 1, 0.5],
                      }}
                      transition={{
                        duration: 0.8,
                        repeat: Infinity,
                        delay: i * 0.15,
                      }}
                    />
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="px-4"
          >
            <div className="flex items-center gap-2 p-2 bg-red-950/50 border border-red-800/50 rounded-md mb-2">
              <AlertCircle className="w-4 h-4 text-red-400" />
              <span className="text-xs text-red-400 flex-1">{error}</span>
              <button
                type="button"
                onClick={handleRetry}
                className="p-1 hover:bg-red-900/50 rounded transition-colors"
              >
                <RefreshCw className="w-3 h-3 text-red-400" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input Area */}
      <div className="p-4 border-t border-slate-800">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about this task or request changes..."
            disabled={isLoading}
            rows={1}
            className="flex-1 px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg
              text-sm text-white placeholder:text-slate-500 resize-none
              focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500
              disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            style={{ minHeight: '40px', maxHeight: '120px' }}
          />
          <Button
            variant="primary"
            size="sm"
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="px-3"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </Button>
        </div>
        <p className="text-2xs text-slate-600 mt-1.5">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
