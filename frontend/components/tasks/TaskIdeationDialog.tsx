'use client'

import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Rocket,
  X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  ChatPanel,
  type ChatMessage,
  type ChatStreamApiConfig,
} from '@agent-hub/chat-ui'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { getApiBaseUrl } from '@/lib/api-config'
import type { TaskType } from '@/lib/api/tasks-types'

interface TaskIdeationDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
}

interface IdeationTaskData {
  title: string
  description: string
  priority: number
  task_type: TaskType
  labels: string[]
  complexity: 'simple' | 'standard' | 'complex'
}

interface IdeationTaskResponse {
  task_id: string
  project_id: string
  status: string
  dispatched: boolean
  dispatch_stage: string | null
}

type Complexity = 'simple' | 'standard' | 'complex'

const PRIORITY_OPTIONS = [
  { value: '0', label: 'P0 - Critical' },
  { value: '1', label: 'P1 - High' },
  { value: '2', label: 'P2 - Medium' },
  { value: '3', label: 'P3 - Low' },
  { value: '4', label: 'P4 - Backlog' },
]

const TYPE_OPTIONS: { value: TaskType; label: string }[] = [
  { value: 'feature', label: 'Feature' },
  { value: 'bug', label: 'Bug' },
  { value: 'task', label: 'Task' },
  { value: 'refactor', label: 'Refactor' },
  { value: 'debt', label: 'Tech Debt' },
  { value: 'regression', label: 'Regression' },
]

const COMPLEXITY_OPTIONS: { value: Complexity; label: string }[] = [
  { value: 'simple', label: 'Simple' },
  { value: 'standard', label: 'Standard' },
  { value: 'complex', label: 'Complex' },
]

function getAgentHubBaseUrl(): string {
  if (typeof window === 'undefined') {
    return 'http://localhost:8003'
  }
  const host = window.location.hostname
  if (host === 'localhost' || host === '127.0.0.1') {
    return 'http://localhost:8003'
  }
  return 'https://agentapi.summitflow.dev'
}

function extractCreateTaskTool(
  messages: ChatMessage[],
): IdeationTaskData | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i]
    if (msg.role !== 'assistant' || !msg.toolExecutions) continue

    for (const tool of msg.toolExecutions) {
      if (tool.name === 'create_task' && tool.status !== 'error') {
        const input = tool.input as Record<string, unknown>
        return {
          title: (input.title as string) || '',
          description: (input.description as string) || '',
          priority: typeof input.priority === 'number' ? input.priority : 2,
          task_type: (input.task_type as TaskType) || 'task',
          labels: Array.isArray(input.labels)
            ? (input.labels as string[])
            : [],
          complexity: (input.complexity as Complexity) || 'standard',
        }
      }
    }
  }
  return null
}

function ComplexityBadge({ complexity }: { complexity: Complexity }) {
  const variantMap: Record<Complexity, 'phosphor' | 'amber' | 'rose'> = {
    simple: 'phosphor',
    standard: 'amber',
    complex: 'rose',
  }
  return <Badge variant={variantMap[complexity]}>{complexity}</Badge>
}

function PriorityBadge({ priority }: { priority: number }) {
  const labels: Record<number, string> = {
    0: 'P0',
    1: 'P1',
    2: 'P2',
    3: 'P3',
    4: 'P4',
  }
  const variants: Record<number, 'rose' | 'amber' | 'default' | 'slate'> = {
    0: 'rose',
    1: 'amber',
    2: 'default',
    3: 'slate',
    4: 'slate',
  }
  return (
    <Badge variant={variants[priority] ?? 'default'}>
      {labels[priority] ?? `P${priority}`}
    </Badge>
  )
}

export function TaskIdeationDialog({
  open,
  onOpenChange,
  projectId,
}: TaskIdeationDialogProps) {
  const queryClient = useQueryClient()
  const [taskData, setTaskData] = useState<IdeationTaskData | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesRef = useRef<ChatMessage[]>([])

  const apiConfig: ChatStreamApiConfig = useMemo(() => {
    const hubBase = getAgentHubBaseUrl()
    return {
      completeEndpoint: `${hubBase}/api/complete`,
      sessionsEndpoint: `${hubBase}/api/sessions`,
      projectId: projectId,
      memoryGroupPrefix: 'summitflow:',
    }
  }, [projectId])

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

      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })

      toast.success(`Task created: ${result.task_id}`, {
        description: result.dispatched
          ? `Dispatched to ${result.dispatch_stage ?? 'pipeline'}`
          : 'Task created successfully',
      })

      setTaskData(null)
      setError(null)
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create task')
    } finally {
      setIsSubmitting(false)
    }
  }, [taskData, projectId, queryClient, onOpenChange])

  const updateField = useCallback(
    <K extends keyof IdeationTaskData>(
      field: K,
      value: IdeationTaskData[K],
    ) => {
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
      updateField(
        'labels',
        taskData.labels.filter((l) => l !== label),
      )
    },
    [taskData, updateField],
  )

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden">
        <DialogClose onClose={handleClose} />
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-mono tracking-wider text-sm uppercase">
            <MessageSquare className="w-4 h-4 text-phosphor-400" />
            Task Ideation
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 min-h-0 relative">
          <AnimatePresence mode="wait">
            {taskData ? (
              <motion.div
                key="summary"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.2 }}
                className="h-full overflow-y-auto p-5"
              >
                <TaskSummaryCard
                  taskData={taskData}
                  isSubmitting={isSubmitting}
                  error={error}
                  onUpdateField={updateField}
                  onAddLabel={handleAddLabel}
                  onRemoveLabel={handleRemoveLabel}
                  onCreateAndStart={handleCreateAndStart}
                  onBackToChat={handleBackToChat}
                />
              </motion.div>
            ) : (
              <motion.div
                key="chat"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="h-full [&_.dark\:border-gray-700]:border-slate-800 [&_.dark\:bg-gray-800]:bg-slate-800/50"
              >
                <ChatPanel
                  agentSlug="ideator"
                  toolsEnabled
                  apiConfig={apiConfig}
                  title="Task Ideation"
                  onMessagesChange={handleMessagesChange}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </DialogContent>
    </Dialog>
  )
}

interface TaskSummaryCardProps {
  taskData: IdeationTaskData
  isSubmitting: boolean
  error: string | null
  onUpdateField: <K extends keyof IdeationTaskData>(
    field: K,
    value: IdeationTaskData[K],
  ) => void
  onAddLabel: (label: string) => void
  onRemoveLabel: (label: string) => void
  onCreateAndStart: () => void
  onBackToChat: () => void
}

function TaskSummaryCard({
  taskData,
  isSubmitting,
  error,
  onUpdateField,
  onAddLabel,
  onRemoveLabel,
  onCreateAndStart,
  onBackToChat,
}: TaskSummaryCardProps) {
  const [newLabel, setNewLabel] = useState('')

  const handleLabelKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      onAddLabel(newLabel)
      setNewLabel('')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <CheckCircle2 className="w-5 h-5 text-phosphor-400" />
        <h3 className="text-lg font-semibold text-white">
          Task Ready for Creation
        </h3>
      </div>

      <div className="rounded-lg border border-phosphor-500/20 bg-slate-800/50 p-5 space-y-5">
        <div className="space-y-2">
          <Label htmlFor="ideation-title">Title</Label>
          <Input
            id="ideation-title"
            value={taskData.title}
            onChange={(e) => onUpdateField('title', e.target.value)}
            disabled={isSubmitting}
            placeholder="Task title"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="ideation-description">Description</Label>
          <Textarea
            id="ideation-description"
            value={taskData.description}
            onChange={(e) => onUpdateField('description', e.target.value)}
            disabled={isSubmitting}
            rows={6}
            placeholder="Task description"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label>Priority</Label>
            <Select
              value={String(taskData.priority)}
              onValueChange={(v) => onUpdateField('priority', parseInt(v, 10))}
              disabled={isSubmitting}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRIORITY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Type</Label>
            <Select
              value={taskData.task_type}
              onValueChange={(v) =>
                onUpdateField('task_type', v as TaskType)
              }
              disabled={isSubmitting}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Complexity</Label>
            <Select
              value={taskData.complexity}
              onValueChange={(v) =>
                onUpdateField('complexity', v as Complexity)
              }
              disabled={isSubmitting}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMPLEXITY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Labels</Label>
          <div className="flex flex-wrap gap-2 min-h-[32px]">
            {taskData.labels.map((label) => (
              <Badge
                key={label}
                variant="outline"
                className="gap-1"
                onClick={isSubmitting ? undefined : () => onRemoveLabel(label)}
              >
                {label}
                {!isSubmitting && <X className="w-3 h-3" />}
              </Badge>
            ))}
          </div>
          <Input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={handleLabelKeyDown}
            disabled={isSubmitting}
            placeholder="Type a label and press Enter"
            className="mt-1"
          />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <PriorityBadge priority={taskData.priority} />
            <Badge variant="default">{taskData.task_type}</Badge>
            <ComplexityBadge complexity={taskData.complexity} />
          </div>
        </div>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="p-3 bg-red-950/50 border border-red-800/50 rounded-md"
          >
            <p className="text-sm text-red-400">{error}</p>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex gap-3">
        <Button
          variant="ghost"
          onClick={onBackToChat}
          disabled={isSubmitting}
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Chat
        </Button>
        <div className="flex-1" />
        <Button
          variant="primary"
          onClick={onCreateAndStart}
          disabled={isSubmitting || !taskData.title.trim()}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating...
            </>
          ) : (
            <>
              <Rocket className="w-4 h-4" />
              Create & Start
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
