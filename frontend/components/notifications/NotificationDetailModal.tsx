'use client'

import { useState } from 'react'
import { type Notification, startTask } from '@/lib/api'
import { ChatPanel } from './ChatPanel'
import { ModalHeader } from './ModalHeader'
import { TaskDetailsPanel } from './TaskDetailsPanel'
import { useChatMessages } from './useChatMessages'
import { useTaskDetails } from './useTaskDetails'

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
  const [retrying, setRetrying] = useState(false)
  const { taskDetails, loading } = useTaskDetails(notification, projectId)
  const { chatMessages, sending, chatEndRef, sendMessage, addMessage } =
    useChatMessages(taskDetails, notification)

  if (!notification) return null

  const handleRetry = async () => {
    if (!notification.task_id || retrying) return
    setRetrying(true)

    try {
      await startTask(projectId, notification.task_id, {
        agent_type: 'gemini',
      })
      addMessage({
        role: 'assistant',
        content:
          'Task has been restarted. You can close this dialog and monitor progress in the task view.',
        timestamp: new Date(),
      })
    } catch {
      addMessage({
        role: 'assistant',
        content:
          'Failed to restart the task. Please try again or check the task status.',
        timestamp: new Date(),
      })
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-2xl max-h-[90vh] bg-slate-900 border border-slate-700 rounded-lg shadow-xl flex flex-col overflow-hidden">
        <ModalHeader
          notification={notification}
          retrying={retrying}
          onRetry={handleRetry}
          onClose={onClose}
        />

        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Top: Task Details */}
          <div className="h-2/5 min-h-[150px] border-b border-slate-700 overflow-auto p-4">
            <TaskDetailsPanel
              loading={loading}
              taskDetails={taskDetails}
              notification={notification}
            />
          </div>

          {/* Bottom: Chat */}
          <ChatPanel
            messages={chatMessages}
            sending={sending}
            chatEndRef={chatEndRef}
            onSendMessage={sendMessage}
          />
        </div>
      </div>
    </div>
  )
}
