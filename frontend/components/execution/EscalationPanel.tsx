'use client'

import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Send,
  X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { ExecutionTimeline } from '@/components/tasks/ExecutionTimeline'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Task } from '@/lib/api'

interface SupervisorRecommendation {
  problem: string
  solution: string
  reasoning?: string
}

interface EscalationPanelProps {
  task: Task
  recommendation?: SupervisorRecommendation
  isOpen: boolean
  onClose: () => void
  onApproveAndResume: (message?: string) => Promise<void>
}

export function EscalationPanel({
  task,
  recommendation,
  isOpen,
  onClose,
  onApproveAndResume,
}: EscalationPanelProps) {
  const [message, setMessage] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [chatMessages, setChatMessages] = useState<
    Array<{ role: 'user' | 'system'; content: string }>
  >([])

  const handleApprove = async () => {
    setIsSubmitting(true)
    try {
      await onApproveAndResume(message || undefined)
      onClose()
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSendMessage = () => {
    if (!message.trim()) return
    setChatMessages((prev) => [...prev, { role: 'user', content: message }])
    setMessage('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  useEffect(() => {
    if (!isOpen) return
    const handleEscapeKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleEscapeKey)
    return () => document.removeEventListener('keydown', handleEscapeKey)
  }, [isOpen, onClose])

  const needsAttention = task.status === 'blocked'

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          className="bg-slate-900 border border-slate-700 rounded-lg shadow-2xl w-[90vw] max-w-5xl h-[80vh] max-h-[700px] flex flex-col overflow-hidden"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700">
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 text-orange-400" />
              <div>
                <h2 className="text-lg font-medium text-white">
                  Escalation Required
                </h2>
                <p className="text-sm text-slate-400">{task.title}</p>
              </div>
              {needsAttention && (
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-orange-500/20 text-orange-400 border border-orange-500/30">
                  BLOCKED
                </span>
              )}
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="p-2 rounded-md hover:bg-slate-800 transition-colors"
            >
              <X className="h-5 w-5 text-slate-400" />
            </button>
          </div>

          {/* Vertical split layout: left execution context, right chat panel */}
          <div className="flex-1 flex min-h-0">
            <div className="w-1/2 border-r border-slate-700 flex flex-col">
              <div className="px-4 py-2 border-b border-slate-800 bg-slate-800/30">
                <h3 className="text-sm font-medium text-slate-300">
                  Execution Context
                </h3>
              </div>
              <div className="flex-1 overflow-hidden">
                <ExecutionTimeline
                  taskId={task.id}
                  projectId={task.project_id}
                  autoConnect
                  showChatInput={false}
                  className="h-full"
                />
              </div>
            </div>

            <div className="w-1/2 flex flex-col">
              <div className="px-4 py-2 border-b border-slate-800 bg-slate-800/30">
                <h3 className="text-sm font-medium text-slate-300">
                  Resolution Chat
                </h3>
              </div>

              {recommendation && (
                <div className="p-4 border-b border-slate-700 bg-orange-500/5">
                  <div className="flex items-start gap-3">
                    <MessageSquare className="h-5 w-5 text-orange-400 shrink-0 mt-0.5" />
                    <div className="space-y-2">
                      <div>
                        <span className="text-xs font-medium text-orange-400 uppercase">
                          Problem
                        </span>
                        <p className="text-sm text-slate-300">
                          {recommendation.problem}
                        </p>
                      </div>
                      <div>
                        <span className="text-xs font-medium text-phosphor-400 uppercase">
                          Recommended Solution
                        </span>
                        <p className="text-sm text-slate-300">
                          {recommendation.solution}
                        </p>
                      </div>
                      {recommendation.reasoning && (
                        <p className="text-xs text-slate-500">
                          {recommendation.reasoning}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {chatMessages.map((msg, i) => (
                  <div
                    key={`${msg.role}-${i}-${msg.content?.slice(0, 12)}`}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[80%] px-3 py-2 rounded-lg text-sm ${
                        msg.role === 'user'
                          ? 'bg-phosphor-500/20 text-phosphor-200'
                          : 'bg-slate-800 text-slate-300'
                      }`}
                    >
                      {msg.content}
                    </div>
                  </div>
                ))}
                {chatMessages.length === 0 && !recommendation && (
                  <div className="flex items-center justify-center h-full text-sm text-slate-500">
                    No messages yet
                  </div>
                )}
              </div>

              <div className="p-4 border-t border-slate-700 space-y-3">
                <div className="flex gap-2">
                  <Input
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Add context or modify direction..."
                    className="flex-1"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleSendMessage}
                    disabled={!message.trim()}
                  >
                    <Send className="h-4 w-4" />
                  </Button>
                </div>

                <Button
                  onClick={handleApprove}
                  disabled={isSubmitting}
                  className="w-full bg-phosphor-500/20 text-phosphor-400 hover:bg-phosphor-500/30 border border-phosphor-500/30"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Resuming...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="h-4 w-4 mr-2" />
                      Approve & Resume
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
