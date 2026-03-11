import { useCallback, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { ChatMessage } from '@agent-hub/chat-ui'
import { buildAgentHubChatApiConfig } from '@/lib/agent-hub-chat-config'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import { getApiBaseUrl } from '@/lib/api-config'
import {
  CREATE_TASK_TOOL_NAME,
  DEFAULT_COMPLEXITY,
  DEFAULT_PRIORITY,
  DEFAULT_TASK_TYPE,
} from './taskIdeationTypes'
import type { Complexity, IdeationTaskData, IdeationTaskResponse } from './taskIdeationTypes'
import type { TaskType } from '@/lib/api/tasks-types'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

function extractCreateTaskTool(messages: ChatMessage[]): IdeationTaskData | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i]
    if (msg.role !== 'assistant' || !msg.toolExecutions) continue

    for (const tool of msg.toolExecutions) {
      if (tool.name === CREATE_TASK_TOOL_NAME && tool.status !== 'error') {
        const input = tool.input as Record<string, unknown>
        return {
          title: (input.title as string) || '',
          description: (input.description as string) || '',
          priority: typeof input.priority === 'number' ? input.priority : DEFAULT_PRIORITY,
          task_type: (input.task_type as TaskType) || DEFAULT_TASK_TYPE,
          labels: Array.isArray(input.labels) ? (input.labels as string[]) : [],
          complexity: (input.complexity as Complexity) || DEFAULT_COMPLEXITY,
        }
      }
    }
  }
  return null
}

export function useTaskIdeation(projectId: string, onOpenChange: (open: boolean) => void) {
  const { invalidateTasks } = useTaskMutationSync(projectId)
  const [taskData, setTaskData] = useState<IdeationTaskData | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesRef = useRef<ChatMessage[]>([])

  const apiConfig = useMemo(
    () =>
      buildAgentHubChatApiConfig({
        proxyBase: getAgentHubProxyBase(),
        projectId,
      }),
    [projectId],
  )

  const handleMessagesChange = useCallback((messages: ChatMessage[]) => {
    messagesRef.current = messages
    const extracted = extractCreateTaskTool(messages)
    if (extracted) {
      setTaskData(extracted)
    }
  }, [])

  const handleClose = useCallback(() => {
    if (!isSubmitting) {
      setTaskData(null)
      setError(null)
      onOpenChange(false)
    }
  }, [isSubmitting, onOpenChange])

  const handleBackToChat = useCallback(() => {
    setTaskData(null)
    setError(null)
  }, [])

  const handleCreateAndStart = useCallback(async () => {
    if (!taskData) return

    setIsSubmitting(true)
    setError(null)

    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(
        `${apiBase}/api/projects/${projectId}/tasks/from-ideation`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: taskData.title,
            description: taskData.description,
            priority: taskData.priority,
            task_type: taskData.task_type,
            labels: taskData.labels,
            complexity: taskData.complexity,
            auto_dispatch: true,
          }),
        },
      )

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null)
        throw new Error(
          errorBody?.detail || `Failed to create task (${response.status})`,
        )
      }

      const result: IdeationTaskResponse = await response.json()

      invalidateTasks()

      toast.success(`Task created: ${result.task_id}`, {
        description: result.dispatched
          ? `Dispatched to ${result.dispatch_stage ?? 'pipeline'}`
          : 'Task created successfully',
      })

      setTaskData(null)
      setError(null)
      onOpenChange(false)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to create task'))
    } finally {
      setIsSubmitting(false)
    }
  }, [invalidateTasks, onOpenChange, projectId, taskData])

  const updateField = useCallback(
    <K extends keyof IdeationTaskData>(field: K, value: IdeationTaskData[K]) => {
      setTaskData((prev) => (prev ? { ...prev, [field]: value } : null))
    },
    [],
  )

  const handleAddLabel = useCallback(
    (label: string) => {
      if (!taskData || !label.trim()) return
      const trimmed = label.trim()
      if (!taskData.labels.includes(trimmed)) {
        updateField('labels', [...taskData.labels, trimmed])
      }
    },
    [taskData, updateField],
  )

  const handleRemoveLabel = useCallback(
    (label: string) => {
      if (!taskData) return
      updateField('labels', taskData.labels.filter((l) => l !== label))
    },
    [taskData, updateField],
  )

  return {
    taskData,
    isSubmitting,
    error,
    apiConfig,
    handleMessagesChange,
    handleClose,
    handleBackToChat,
    handleCreateAndStart,
    updateField,
    handleAddLabel,
    handleRemoveLabel,
  }
}
