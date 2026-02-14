'use client'

import { clsx } from 'clsx'
import { Bot, Loader2, Mic, MicOff, Send, Terminal, User } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { executeCommand } from '@/lib/api/commands'
import type { ChatMessage } from '../notifications/types'

/**
 * Command panel — chat/voice interface for sending commands to Agent Hub.
 *
 * Features:
 * - Text input with Enter-to-send
 * - Press-to-speak voice via Web Speech API (browser-native)
 * - Conversation history within the session
 * - Mobile-friendly layout (primary use case: PWA on phone)
 */
export function CommandPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [speechError, setSpeechError] = useState<string | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || sending) return

      const userMsg: ChatMessage = {
        role: 'user',
        content: text.trim(),
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, userMsg])
      setInput('')
      setSending(true)

      try {
        const result = await executeCommand(text.trim())
        const assistantMsg: ChatMessage = {
          role: 'assistant',
          content: result.response || '(no response)',
          timestamp: new Date(),
        }
        setMessages((prev) => [...prev, assistantMsg])
      } catch (err) {
        const errorMsg: ChatMessage = {
          role: 'assistant',
          content: `Error: ${err instanceof Error ? err.message : 'Command failed'}`,
          timestamp: new Date(),
        }
        setMessages((prev) => [...prev, errorMsg])
      } finally {
        setSending(false)
      }
    },
    [sending],
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  // Web Speech API — press-to-speak
  const toggleListening = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop()
      setIsListening(false)
      return
    }

    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setSpeechError('Speech recognition not supported in this browser')
      return
    }

    setSpeechError(null)
    const recognition = new SpeechRecognition()
    recognition.continuous = false
    recognition.interimResults = true
    recognition.lang = 'en-US'
    recognitionRef.current = recognition

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join('')
      setInput(transcript)

      // Auto-send on final result
      const isFinal = event.results[event.results.length - 1].isFinal
      if (isFinal) {
        sendMessage(transcript)
      }
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error !== 'aborted') {
        setSpeechError(`Speech error: ${event.error}`)
      }
      setIsListening(false)
    }

    recognition.onend = () => {
      setIsListening(false)
    }

    recognition.start()
    setIsListening(true)
  }, [isListening, sendMessage])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      recognitionRef.current?.stop()
    }
  }, [])

  return (
    <div className="flex flex-col h-full bg-slate-900">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-700">
        <Terminal className="w-4 h-4 text-phosphor-400" />
        <h2 className="text-sm font-medium text-slate-200">Commands</h2>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-slate-500 text-sm py-8">
            <Bot className="w-8 h-8 mx-auto mb-2 text-slate-600" />
            <p>Send a command or tap the mic to speak.</p>
            <p className="text-xs mt-1 text-slate-600">
              Try: &quot;task status&quot; or &quot;what needs attention?&quot;
            </p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={clsx(
              'flex gap-3',
              msg.role === 'user' ? 'flex-row-reverse' : '',
            )}
          >
            <div
              className={clsx(
                'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0',
                msg.role === 'user' ? 'bg-phosphor-500/20' : 'bg-slate-700',
              )}
            >
              {msg.role === 'user' ? (
                <User className="w-4 h-4 text-phosphor-400" />
              ) : (
                <Bot className="w-4 h-4 text-slate-400" />
              )}
            </div>
            <div
              className={clsx(
                'max-w-[80%] p-3 rounded-lg text-sm',
                msg.role === 'user'
                  ? 'bg-phosphor-500/20 text-slate-200'
                  : 'bg-slate-800 text-slate-300',
              )}
            >
              <div className="whitespace-pre-wrap">{msg.content}</div>
              <span className="text-xs text-slate-500 mt-1 block">
                {msg.timestamp.toLocaleTimeString()}
              </span>
            </div>
          </div>
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

      {/* Input area */}
      <div className="p-4 border-t border-slate-700 bg-slate-900/50">
        {speechError && (
          <p className="text-xs text-amber-400 mb-2">{speechError}</p>
        )}
        <div className="flex gap-2">
          <button
            onClick={toggleListening}
            className={clsx(
              'p-3 rounded-lg transition-colors',
              isListening
                ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700',
            )}
            aria-label={isListening ? 'Stop listening' : 'Start voice input'}
          >
            {isListening ? (
              <MicOff className="w-4 h-4" />
            ) : (
              <Mic className="w-4 h-4" />
            )}
          </button>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isListening ? 'Listening...' : 'Type a command...'
            }
            className="flex-1 p-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-phosphor-500"
            rows={2}
            disabled={sending}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || sending}
            className={clsx(
              'p-3 rounded-lg transition-colors',
              input.trim() && !sending
                ? 'bg-phosphor-500 text-white hover:bg-phosphor-600'
                : 'bg-slate-700 text-slate-500 cursor-not-allowed',
            )}
            aria-label="Send command"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-slate-600 mt-2">
          Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
