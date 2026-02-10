import { useEffect, useRef, useState } from 'react'
import type { Notification, Task } from '@/lib/api'
import type { ChatMessage } from './types'

export function useChatMessages(
  taskDetails: Task | null,
  notification: Notification | null,
) {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  // Reset chat when notification changes
  useEffect(() => {
    setChatMessages([])
  }, [notification])

  // Add initial assistant message when task details load
  useEffect(() => {
    if (taskDetails && notification) {
      const errorMsg = taskDetails.error_message || notification.message
      setChatMessages([
        {
          role: 'assistant',
          content: `I encountered an error while executing this task:\n\n"${errorMsg}"\n\nHow would you like me to proceed? I can:\n- **Retry** the failed criterion\n- **Skip** this criterion and continue\n- **Modify** the approach\n\nOr tell me what you'd like me to try differently.`,
          timestamp: new Date(),
        },
      ])
    }
  }, [taskDetails, notification])

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const sendMessage = async (userInput: string) => {
    if (!userInput.trim() || sending) return

    const userMessage: ChatMessage = {
      role: 'user',
      content: userInput,
      timestamp: new Date(),
    }

    setChatMessages((prev) => [...prev, userMessage])
    setSending(true)

    // Simulate AI response (in a real implementation, this would call an API)
    setTimeout(() => {
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: `I understand. Let me analyze your request:\n\n"${userMessage.content}"\n\nTo implement this change, I would need to modify the execution approach. Would you like me to:\n\n1. **Retry with modifications** - Apply your suggestion and retry\n2. **Create a new plan** - Generate a new implementation plan\n3. **Escalate** - Mark this for manual review\n\nPlease let me know which option you prefer.`,
        timestamp: new Date(),
      }
      setChatMessages((prev) => [...prev, assistantMessage])
      setSending(false)
    }, 1500)
  }

  const addMessage = (message: ChatMessage) => {
    setChatMessages((prev) => [...prev, message])
  }

  return {
    chatMessages,
    sending,
    chatEndRef,
    sendMessage,
    addMessage,
  }
}
