'use client'

import {
  ActivityIndicator,
  MessageInput,
  MessageList,
  type StreamStatus,
  useChatStream,
} from '@agent-hub/chat-ui'
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Columns2,
  Globe2,
  Grid2X2,
  Layers3,
  Maximize2,
  MessageCircleWarning,
  MessageSquarePlus,
  PanelRightClose,
  PanelsTopLeft,
  Pause,
  Play,
  Plus,
  Radio,
  Rows2,
  Send,
  SquareSplitHorizontal,
  StopCircle,
  Workflow,
  X,
} from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import { fetchProjects, fetchTasks, type Project, type Task } from '@/lib/api'
import {
  type ActionRequest,
  type AgentHubAgent,
  type AgentHubSessionListItem,
  buildWorkChatApiConfig,
  cancelAgentHubSessionStream,
  closeAgentHubSession,
  fetchActionRequests,
  fetchAgentHubAgents,
  fetchAgentHubSessions,
  upsertWorkChatBinding,
  type WorkContext,
} from '@/lib/api/agent-hub-work-chats'
import { type FeedbackItem, fetchFeedbackItems } from '@/lib/api/feedback'
import { fetchMockups, type Mockup } from '@/lib/api/mockups'
import { cn } from '@/lib/utils'

type WorkChatLayout =
  | 'horizontal'
  | 'vertical'
  | 'main-side'
  | 'two-by-two'
  | 'wide-grid'

interface WorkChatPane {
  id: string
  chatKey: number
  sessionId: string | null
  agentSlug: string
  projectId: string | null
  taskId: string | null
  taskTitle: string | null
  taskSummary: string | null
  feedbackId: string | null
  designId: string | null
  artifactSummary: string | null
}

interface WorkStartCommand {
  key: number
  prompt: string
}

interface ArtifactOption {
  value: string
  label: string
  kind: 'feedback' | 'design'
  id: string
  linkedTaskId?: string | null
}

const STORAGE_KEY = 'summitflow_work_chats_v2'
const MAX_PANES = 6
const SOURCE_CLIENT = 'summitflow/work-chats'
const GENERAL_PROJECT_ID = 'summitflow'

function makePane(agentSlug = 'chat'): WorkChatPane {
  return {
    id: `pane-${Math.random().toString(36).slice(2, 10)}`,
    chatKey: 0,
    sessionId: null,
    agentSlug,
    projectId: null,
    taskId: null,
    taskTitle: null,
    taskSummary: null,
    feedbackId: null,
    designId: null,
    artifactSummary: null,
  }
}

function readSavedState(defaultAgent: string): {
  layout: WorkChatLayout
  activePaneId: string
  panes: WorkChatPane[]
} {
  if (typeof window === 'undefined') {
    const pane = makePane(defaultAgent)
    return { layout: 'main-side', activePaneId: pane.id, panes: [pane] }
  }

  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) {
    const pane = makePane(defaultAgent)
    return { layout: 'main-side', activePaneId: pane.id, panes: [pane] }
  }

  try {
    const parsed = JSON.parse(raw)
    const panes = Array.isArray(parsed.panes)
      ? parsed.panes
          .slice(0, MAX_PANES)
          .filter((pane: Partial<WorkChatPane>) => pane?.id)
          .map((pane: Partial<WorkChatPane>) => ({
            ...makePane(defaultAgent),
            ...pane,
            chatKey: pane.chatKey ?? 0,
          }))
      : []
    if (panes.length === 0) throw new Error('empty panes')
    return {
      layout: parsed.layout ?? 'main-side',
      activePaneId: parsed.activePaneId ?? panes[0].id,
      panes,
    }
  } catch {
    const pane = makePane(defaultAgent)
    return { layout: 'main-side', activePaneId: pane.id, panes: [pane] }
  }
}

function layoutClass(layout: WorkChatLayout, count: number): string {
  if (count === 1) return 'grid-cols-1'
  if (layout === 'horizontal') return 'grid-cols-1'
  if (layout === 'vertical') return 'md:grid-cols-2'
  if (layout === 'two-by-two') return 'md:grid-cols-2'
  if (layout === 'wide-grid') return 'md:grid-cols-2 xl:grid-cols-3'
  return 'md:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]'
}

function workContextForPane(
  pane: WorkChatPane,
  project: Project | null,
): WorkContext {
  const mode = pane.taskId
    ? 'project_task'
    : pane.projectId
      ? 'project'
      : pane.feedbackId || pane.designId
        ? 'artifact'
        : 'general'

  return {
    mode,
    project_id: pane.projectId ?? undefined,
    project_name: project?.name,
    task_id: pane.taskId ?? undefined,
    task_title: pane.taskTitle ?? undefined,
    task_summary: pane.taskSummary ?? undefined,
    feedback_id: pane.feedbackId ?? undefined,
    design_id: pane.designId ?? undefined,
    artifact_summary: pane.artifactSummary ?? undefined,
    surface: 'work_chats',
    pane_id: pane.id,
  }
}

function startPromptForPane(
  pane: WorkChatPane,
  project: Project | null,
): string {
  const lines = [
    'Start work in this SummitFlow Work Chats pane.',
    'Use work_context as authoritative. Keep this parent chat as supervisor context. Spawn child work lanes for implementation when useful.',
  ]
  if (pane.taskId) {
    lines.push(
      `Work task ${pane.taskId}${pane.taskTitle ? `: ${pane.taskTitle}` : ''}.`,
    )
  } else if (pane.projectId) {
    lines.push(
      `Work in project ${project?.name ?? pane.projectId}. Create or link a task before implementation when needed.`,
    )
  } else if (pane.feedbackId || pane.designId) {
    lines.push('Create or link the relevant task, then start work.')
  } else {
    lines.push(
      'General mode. Create project and task records first when needed.',
    )
  }
  return lines.join('\n')
}

function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const update = () => setIsMobile(window.innerWidth < 768)
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  return isMobile
}

function IconButton({
  title,
  onClick,
  disabled = false,
  active = false,
  children,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={cn(
        'flex h-7 w-7 shrink-0 items-center justify-center rounded border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-phosphor-500/40',
        active
          ? 'border-phosphor-500/40 bg-phosphor-500/10 text-phosphor-300'
          : 'border-slate-800 bg-slate-950/60 text-slate-500 hover:border-slate-600 hover:text-slate-200',
        disabled && 'cursor-not-allowed opacity-40',
      )}
    >
      {children}
    </button>
  )
}

function LayoutButton({
  value,
  active,
  onClick,
}: {
  value: WorkChatLayout
  active: boolean
  onClick: () => void
}) {
  const Icon =
    value === 'horizontal'
      ? Rows2
      : value === 'vertical'
        ? Columns2
        : value === 'two-by-two'
          ? Grid2X2
          : value === 'wide-grid'
            ? SquareSplitHorizontal
            : PanelRightClose

  return (
    <IconButton title={value} active={active} onClick={onClick}>
      <Icon className="h-3.5 w-3.5" />
    </IconButton>
  )
}

function SelectControl({
  value,
  onChange,
  label,
  children,
  disabled = false,
  className,
}: {
  value: string
  onChange: (value: string) => void
  label: string
  children: React.ReactNode
  disabled?: boolean
  className?: string
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(
        'h-7 min-w-0 shrink-0 rounded border border-slate-800 bg-slate-950/70 px-2 text-xs text-slate-200 outline-none transition-colors',
        'hover:border-slate-600 focus:border-phosphor-500/50 disabled:cursor-not-allowed disabled:opacity-40',
        className,
      )}
    >
      {children}
    </select>
  )
}

function PaneBadge({
  title,
  children,
  active = false,
}: {
  title: string
  children: React.ReactNode
  active?: boolean
}) {
  return (
    <span
      title={title}
      className={cn(
        'flex h-6 min-w-6 shrink-0 items-center justify-center rounded border px-1 text-[10px]',
        active
          ? 'border-phosphor-500/30 bg-phosphor-500/10 text-phosphor-300'
          : 'border-slate-800 bg-slate-950/60 text-slate-500',
      )}
    >
      {children}
    </span>
  )
}

function PaneStatus({
  status,
  error,
}: {
  status: StreamStatus
  error: string | null
}) {
  if (error || status === 'error') {
    return (
      <PaneBadge title={error ?? 'Chat error'} active>
        <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
      </PaneBadge>
    )
  }
  if (status === 'streaming' || status === 'connecting') {
    return (
      <PaneBadge title={status} active>
        <ActivityIndicator state={status} className="scale-75" />
      </PaneBadge>
    )
  }
  return (
    <PaneBadge title="Ready">
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
    </PaneBadge>
  )
}

function buildArtifactOptions({
  pane,
  feedbackItems,
  mockups,
}: {
  pane: WorkChatPane
  feedbackItems: FeedbackItem[]
  mockups: Mockup[]
}): ArtifactOption[] {
  const feedbackOptions = feedbackItems.map((item) => ({
    value: `feedback:${item.id}`,
    label: item.title,
    kind: 'feedback' as const,
    id: item.id,
    linkedTaskId: item.linked_task_id,
  }))
  const designOptions = mockups.map((mockup) => ({
    value: `design:${mockup.mockup_id}`,
    label: mockup.name,
    kind: 'design' as const,
    id: mockup.mockup_id,
    linkedTaskId: mockup.task_id,
  }))

  const options = [...feedbackOptions, ...designOptions]
  if (
    pane.feedbackId &&
    !options.some((option) => option.value === `feedback:${pane.feedbackId}`)
  ) {
    options.unshift({
      value: `feedback:${pane.feedbackId}`,
      label: pane.artifactSummary ?? pane.feedbackId,
      kind: 'feedback',
      id: pane.feedbackId,
      linkedTaskId: pane.taskId,
    })
  }
  if (
    pane.designId &&
    !options.some((option) => option.value === `design:${pane.designId}`)
  ) {
    options.unshift({
      value: `design:${pane.designId}`,
      label: pane.artifactSummary ?? pane.designId,
      kind: 'design',
      id: pane.designId,
      linkedTaskId: pane.taskId,
    })
  }
  return options
}

function PaneChrome({
  pane,
  status,
  error,
  agents,
  sessions,
  projects,
  childSessions,
  actionRequests,
  onPatch,
  onNewChat,
  onSplit,
  onClose,
  onStart,
  onPause,
  onStop,
}: {
  pane: WorkChatPane
  status: StreamStatus
  error: string | null
  agents: AgentHubAgent[]
  sessions: AgentHubSessionListItem[]
  projects: Project[]
  childSessions: AgentHubSessionListItem[]
  actionRequests: ActionRequest[]
  onPatch: (patch: Partial<WorkChatPane>) => void
  onNewChat: () => void
  onSplit: () => void
  onClose: () => void
  onStart: () => void
  onPause: () => void
  onStop: () => void
}) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [feedbackItems, setFeedbackItems] = useState<FeedbackItem[]>([])
  const [mockups, setMockups] = useState<Mockup[]>([])

  useEffect(() => {
    if (!pane.projectId) {
      setTasks([])
      setFeedbackItems([])
      setMockups([])
      return
    }

    let cancelled = false
    fetchTasks(pane.projectId, { limit: 100 })
      .then((result) => {
        if (!cancelled) setTasks(result.tasks)
      })
      .catch(() => {
        if (!cancelled) setTasks([])
      })
    fetchFeedbackItems({
      project_id: pane.projectId,
      status: 'active',
      limit: 50,
    })
      .then((result) => {
        if (!cancelled) setFeedbackItems(result.items)
      })
      .catch(() => {
        if (!cancelled) setFeedbackItems([])
      })
    fetchMockups(pane.projectId, { limit: 50 })
      .then((result) => {
        if (!cancelled) setMockups(result.items)
      })
      .catch(() => {
        if (!cancelled) setMockups([])
      })
    return () => {
      cancelled = true
    }
  }, [pane.projectId])

  const displayedTasks = useMemo(() => {
    if (!pane.taskId || tasks.some((task) => task.id === pane.taskId)) {
      return tasks
    }
    return [
      {
        id: pane.taskId,
        project_id: pane.projectId ?? '',
        title: pane.taskTitle ?? pane.taskId,
        description: pane.taskSummary,
        status: 'pending',
        plan_content: null,
        progress_log: null,
        error_message: null,
        branch_name: null,
        commits: [],
        total_sessions: 0,
        total_tokens_used: 0,
        created_at: null,
        updated_at: null,
        started_at: null,
        completed_at: null,
        priority: 2,
        labels: [],
        task_type: 'task',
        parent_task_id: null,
        capability_id: null,
      } as Task,
      ...tasks,
    ]
  }, [pane.projectId, pane.taskId, pane.taskSummary, pane.taskTitle, tasks])

  const artifacts = useMemo(
    () => buildArtifactOptions({ pane, feedbackItems, mockups }),
    [feedbackItems, mockups, pane],
  )
  const selectedArtifact = pane.feedbackId
    ? `feedback:${pane.feedbackId}`
    : pane.designId
      ? `design:${pane.designId}`
      : ''
  const hasTelegram = actionRequests.some((request) => request.telegram_chat_id)
  const blockers = actionRequests.filter(
    (request) => request.status !== 'resolved',
  )

  return (
    <div className="flex h-8 shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-800 bg-slate-900/85 px-1.5">
      <PaneStatus status={status} error={error} />

      <SelectControl
        value={pane.agentSlug}
        onChange={(value) => onPatch({ agentSlug: value })}
        label="Agent"
        className="w-40"
      >
        {agents.map((agent) => (
          <option key={agent.slug} value={agent.slug}>
            {agent.name}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={pane.projectId ?? ''}
        onChange={(value) =>
          onPatch({
            projectId: value || null,
            taskId: null,
            taskTitle: null,
            taskSummary: null,
            feedbackId: null,
            designId: null,
            artifactSummary: null,
          })
        }
        label="Project"
        className="w-40"
      >
        <option value="">General</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={pane.taskId ?? ''}
        onChange={(value) => {
          const task = displayedTasks.find((item) => item.id === value)
          onPatch({
            taskId: task?.id ?? null,
            taskTitle: task?.title ?? null,
            taskSummary: task?.description ?? null,
          })
        }}
        label="Task"
        disabled={!pane.projectId}
        className="w-56"
      >
        <option value="">No task</option>
        {displayedTasks.map((task) => (
          <option key={task.id} value={task.id}>
            {task.id} - {task.title}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={selectedArtifact}
        onChange={(value) => {
          const artifact = artifacts.find((item) => item.value === value)
          if (!artifact) {
            onPatch({
              feedbackId: null,
              designId: null,
              artifactSummary: null,
            })
            return
          }
          onPatch({
            feedbackId: artifact.kind === 'feedback' ? artifact.id : null,
            designId: artifact.kind === 'design' ? artifact.id : null,
            artifactSummary: artifact.label,
            taskId: artifact.linkedTaskId ?? pane.taskId,
          })
        }}
        label="Feedback or design"
        disabled={!pane.projectId}
        className="w-48"
      >
        <option value="">No artifact</option>
        {artifacts.map((artifact) => (
          <option key={artifact.value} value={artifact.value}>
            {artifact.kind} - {artifact.label}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={pane.sessionId ?? ''}
        onChange={(value) => onPatch({ sessionId: value || null })}
        label="Session"
        className="w-36"
      >
        <option value="">New session</option>
        {sessions.map((session) => (
          <option key={session.id} value={session.id}>
            {session.id.slice(0, 8)} - {session.agent_slug ?? 'agent'}
          </option>
        ))}
      </SelectControl>

      <div className="flex-1" />

      <PaneBadge title="Transport: Web via SummitFlow">
        <Globe2 className="h-3.5 w-3.5" />
      </PaneBadge>
      {pane.sessionId ? (
        <PaneBadge title={`Session ${pane.sessionId}`} active>
          <Radio className="h-3.5 w-3.5" />
        </PaneBadge>
      ) : null}
      {pane.taskId ? (
        <PaneBadge title={`Task ${pane.taskId}`} active>
          <ClipboardList className="h-3.5 w-3.5" />
        </PaneBadge>
      ) : null}
      {pane.feedbackId || pane.designId ? (
        <PaneBadge title={pane.artifactSummary ?? 'Artifact'} active>
          <Layers3 className="h-3.5 w-3.5" />
        </PaneBadge>
      ) : null}
      {childSessions.length ? (
        <PaneBadge title={`${childSessions.length} child lanes`} active>
          <Workflow className="h-3.5 w-3.5" />
          <span className="ml-1">{childSessions.length}</span>
        </PaneBadge>
      ) : null}
      {blockers.length ? (
        <PaneBadge title={`${blockers.length} action requests`} active>
          <MessageCircleWarning className="h-3.5 w-3.5" />
          <span className="ml-1">{blockers.length}</span>
        </PaneBadge>
      ) : null}
      {hasTelegram ? (
        <PaneBadge title="Telegram linked" active>
          <Send className="h-3.5 w-3.5" />
        </PaneBadge>
      ) : null}

      <IconButton title="New chat" onClick={onNewChat}>
        <MessageSquarePlus className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Split pane" onClick={onSplit}>
        <Columns2 className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton
        title="Detach"
        onClick={() => {
          const params = new URLSearchParams()
          if (pane.sessionId) params.set('session_id', pane.sessionId)
          if (pane.projectId) params.set('project_id', pane.projectId)
          if (pane.taskId) params.set('task_id', pane.taskId)
          if (pane.taskTitle) params.set('task_title', pane.taskTitle)
          window.open(`/work-chats?${params.toString()}`, '_blank')
        }}
      >
        <Maximize2 className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton
        title={pane.sessionId ? 'Resume work' : 'Start work'}
        onClick={onStart}
      >
        <Play className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Pause" onClick={onPause} disabled={!pane.sessionId}>
        <Pause className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Stop" onClick={onStop} disabled={!pane.sessionId}>
        <StopCircle className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton title="Close pane" onClick={onClose}>
        <X className="h-3.5 w-3.5" />
      </IconButton>
    </div>
  )
}

function WorkChatBody({
  pane,
  apiConfig,
  workingDir,
  startCommand,
  onRuntimeChange,
  onSessionCreated,
}: {
  pane: WorkChatPane
  apiConfig: ReturnType<typeof buildWorkChatApiConfig>
  workingDir?: string
  startCommand?: WorkStartCommand
  onRuntimeChange: (state: {
    status: StreamStatus
    error: string | null
  }) => void
  onSessionCreated: (sessionId: string) => void
}) {
  const {
    messages,
    status,
    error,
    currentSessionId,
    sendMessage,
    cancelStream,
    editMessage,
    regenerateMessage,
  } = useChatStream({
    agentSlug: pane.agentSlug,
    sessionId: pane.sessionId ?? undefined,
    workingDir,
    toolsEnabled: true,
    apiConfig,
  })
  const lastNotifiedSessionId = useRef<string | null>(null)
  const lastAutoSendKey = useRef<number | null>(null)

  useEffect(() => {
    onRuntimeChange({ status, error })
  }, [error, onRuntimeChange, status])

  useEffect(() => {
    if (
      !currentSessionId ||
      currentSessionId === lastNotifiedSessionId.current
    ) {
      return
    }
    lastNotifiedSessionId.current = currentSessionId
    onSessionCreated(currentSessionId)
  }, [currentSessionId, onSessionCreated])

  useEffect(() => {
    if (!startCommand || lastAutoSendKey.current === startCommand.key) return
    if (status !== 'idle' && status !== 'error') return
    lastAutoSendKey.current = startCommand.key
    sendMessage(startCommand.prompt)
  }, [sendMessage, startCommand, status])

  const isStreaming =
    status === 'streaming' ||
    status === 'reconnecting' ||
    status === 'cancelling' ||
    status === 'connecting'

  return (
    <div className="flex h-full min-h-0 flex-col chat-outrun">
      {error ? (
        <div className="shrink-0 border-b border-rose-500/20 bg-rose-500/10 px-3 py-1 text-xs text-rose-300">
          {error}
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <MessageList
          messages={messages}
          isStreaming={isStreaming}
          onEditMessage={editMessage}
          onRegenerateMessage={regenerateMessage}
        />
      </div>
      <div className="shrink-0 border-t border-slate-800 bg-slate-950/85">
        <MessageInput
          onSend={(message, targetModels) => sendMessage(message, targetModels)}
          onCancel={cancelStream}
          status={status}
          compact
          preferencesEndpoint={`${getAgentHubProxyBase()}/preferences`}
          modelsEndpoint={`${getAgentHubProxyBase()}/models`}
        />
      </div>
    </div>
  )
}

function WorkChatPaneView({
  pane,
  active,
  index,
  paneCount,
  layout,
  agents,
  sessions,
  projects,
  childSessions,
  actionRequests,
  startCommand,
  onActivate,
  onPatch,
  onNewChat,
  onSplit,
  onClose,
  onStart,
  onPause,
  onStop,
}: {
  pane: WorkChatPane
  active: boolean
  index: number
  paneCount: number
  layout: WorkChatLayout
  agents: AgentHubAgent[]
  sessions: AgentHubSessionListItem[]
  projects: Project[]
  childSessions: AgentHubSessionListItem[]
  actionRequests: ActionRequest[]
  startCommand?: WorkStartCommand
  onActivate: () => void
  onPatch: (patch: Partial<WorkChatPane>) => void
  onNewChat: () => void
  onSplit: () => void
  onClose: () => void
  onStart: () => void
  onPause: () => void
  onStop: () => void
}) {
  const [runtime, setRuntime] = useState<{
    status: StreamStatus
    error: string | null
  }>({ status: 'idle', error: null })
  const project = pane.projectId
    ? (projects.find((item) => item.id === pane.projectId) ?? null)
    : null
  const context = useMemo(
    () => workContextForPane(pane, project),
    [pane, project],
  )
  const mainSideRowSpan =
    layout === 'main-side' && index === 0 && paneCount > 2
      ? Math.min(paneCount - 1, MAX_PANES - 1)
      : null
  const apiConfig = useMemo(
    () =>
      buildWorkChatApiConfig({
        projectId: pane.projectId ?? GENERAL_PROJECT_ID,
        externalId:
          pane.taskId ??
          pane.feedbackId ??
          (pane.designId ? `design:${pane.designId}` : null),
        sourceMetadata: {
          transport: 'web',
          surface: 'work_chats',
          pane_id: pane.id,
          source_client: SOURCE_CLIENT,
        },
        workContext: context,
      }),
    [
      context,
      pane.designId,
      pane.feedbackId,
      pane.id,
      pane.projectId,
      pane.taskId,
    ],
  )

  const handleSessionCreated = useCallback(
    (sessionId: string) => {
      onPatch({ sessionId })
      void upsertWorkChatBinding({
        session_id: sessionId,
        surface: 'work_chats',
        pane_id: pane.id,
        project_id: pane.projectId,
        task_id: pane.taskId,
        feedback_id: pane.feedbackId,
        design_id: pane.designId,
        source_client: SOURCE_CLIENT,
        work_context: context,
      })
    },
    [
      context,
      onPatch,
      pane.designId,
      pane.feedbackId,
      pane.id,
      pane.projectId,
      pane.taskId,
    ],
  )

  return (
    <section
      onClick={onActivate}
      style={
        mainSideRowSpan
          ? { gridRow: `span ${mainSideRowSpan} / span ${mainSideRowSpan}` }
          : undefined
      }
      className={cn(
        'flex min-h-0 min-w-0 resize flex-col overflow-hidden rounded border bg-slate-950/80',
        active
          ? 'border-phosphor-500/50 shadow-[0_0_0_1px_rgba(0,245,255,0.08)]'
          : 'border-slate-800',
      )}
    >
      <PaneChrome
        pane={pane}
        status={runtime.status}
        error={runtime.error}
        agents={agents}
        sessions={sessions}
        projects={projects}
        childSessions={childSessions}
        actionRequests={actionRequests}
        onPatch={onPatch}
        onNewChat={onNewChat}
        onSplit={onSplit}
        onClose={onClose}
        onStart={onStart}
        onPause={onPause}
        onStop={onStop}
      />
      <div className="min-h-0 flex-1">
        <WorkChatBody
          key={`${pane.id}:${pane.chatKey}:${pane.sessionId ?? 'new'}:${pane.agentSlug}`}
          pane={pane}
          apiConfig={apiConfig}
          workingDir={project?.root_path ?? undefined}
          startCommand={startCommand}
          onRuntimeChange={setRuntime}
          onSessionCreated={handleSessionCreated}
        />
      </div>
    </section>
  )
}

function paneFromSearchParams(
  searchParams: URLSearchParams,
  defaultAgent: string,
): WorkChatPane {
  return {
    ...makePane(searchParams.get('agent_slug') || defaultAgent),
    sessionId: searchParams.get('session_id'),
    projectId: searchParams.get('project_id'),
    taskId: searchParams.get('task_id'),
    taskTitle: searchParams.get('task_title'),
    taskSummary: searchParams.get('task_summary'),
    feedbackId: searchParams.get('feedback_id'),
    designId: searchParams.get('design_id'),
    artifactSummary: searchParams.get('artifact_summary'),
  }
}

function WorkChatsContent() {
  const searchParams = useSearchParams()
  const isMobile = useIsMobile()
  const queryString = searchParams.toString()
  const initializedRef = useRef(false)
  const [layout, setLayout] = useState<WorkChatLayout>('main-side')
  const [panes, setPanes] = useState<WorkChatPane[]>([])
  const [activePaneId, setActivePaneId] = useState('')
  const [agents, setAgents] = useState<AgentHubAgent[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [sessions, setSessions] = useState<AgentHubSessionListItem[]>([])
  const [childSessions, setChildSessions] = useState<AgentHubSessionListItem[]>(
    [],
  )
  const [actionRequests, setActionRequests] = useState<ActionRequest[]>([])
  const [startCommands, setStartCommands] = useState<
    Record<string, WorkStartCommand>
  >({})
  const [paneActionError, setPaneActionError] = useState<string | null>(null)
  const [appliedQueryString, setAppliedQueryString] = useState('')

  const defaultAgent = agents[0]?.slug ?? 'chat'

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    const saved = readSavedState(defaultAgent)
    setLayout(saved.layout)
    setPanes(saved.panes)
    setActivePaneId(saved.activePaneId)
  }, [defaultAgent])

  useEffect(() => {
    fetchAgentHubAgents()
      .then((items) =>
        setAgents(items.length ? items : [{ slug: 'chat', name: 'Chat' }]),
      )
      .catch(() => setAgents([{ slug: 'chat', name: 'Chat' }]))
    fetchProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
  }, [])

  useEffect(() => {
    if (!panes.length) return
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ layout, panes, activePaneId }),
    )
  }, [activePaneId, layout, panes])

  useEffect(() => {
    if (!queryString || appliedQueryString === queryString || !panes.length) {
      return
    }

    const params = new URLSearchParams(queryString)
    const hasWorkContext =
      params.has('session_id') ||
      params.has('project_id') ||
      params.has('task_id') ||
      params.has('feedback_id') ||
      params.has('design_id')
    if (!hasWorkContext) return

    const queryPane = paneFromSearchParams(params, defaultAgent)
    setPanes((current) => {
      const emptyIndex = current.findIndex(
        (pane) =>
          !pane.sessionId &&
          !pane.projectId &&
          !pane.taskId &&
          !pane.feedbackId &&
          !pane.designId,
      )
      if (emptyIndex >= 0) {
        const next = [...current]
        next[emptyIndex] = queryPane
        return next
      }
      if (current.length >= MAX_PANES) {
        const replaceIndex = Math.max(
          current.findIndex((pane) => pane.id === activePaneId),
          0,
        )
        const next = [...current]
        next[replaceIndex] = queryPane
        return next
      }
      return [...current, queryPane]
    })
    setActivePaneId(queryPane.id)
    setAppliedQueryString(queryString)

    if (params.get('start') === '1') {
      setStartCommands((current) => ({
        ...current,
        [queryPane.id]: {
          key: Date.now(),
          prompt: startPromptForPane(queryPane, null),
        },
      }))
    }
  }, [
    activePaneId,
    appliedQueryString,
    defaultAgent,
    panes.length,
    queryString,
  ])

  const activePane = panes.find((pane) => pane.id === activePaneId) ?? panes[0]

  useEffect(() => {
    fetchAgentHubSessions({ status: 'active', page_size: 100 })
      .then(setSessions)
      .catch(() => setSessions([]))
  }, [panes.length])

  useEffect(() => {
    if (!activePane?.sessionId) {
      setChildSessions([])
      setActionRequests([])
      return
    }

    fetchAgentHubSessions({
      parent_session_id: activePane.sessionId,
      page_size: 50,
    })
      .then(setChildSessions)
      .catch(() => setChildSessions([]))
    fetchActionRequests({ session_id: activePane.sessionId })
      .then(setActionRequests)
      .catch(() => setActionRequests([]))
  }, [activePane?.sessionId])

  const visiblePanes = useMemo(
    () => (isMobile && activePane ? [activePane] : panes),
    [activePane, isMobile, panes],
  )

  const patchPane = (paneId: string, patch: Partial<WorkChatPane>) => {
    setPanes((current) =>
      current.map((pane) =>
        pane.id === paneId ? { ...pane, ...patch } : pane,
      ),
    )
  }

  const splitPane = (pane: WorkChatPane) => {
    if (panes.length >= MAX_PANES) return
    const next = { ...pane, id: makePane(pane.agentSlug).id, sessionId: null }
    setPanes((current) => [...current, next])
    setActivePaneId(next.id)
  }

  const closePane = (pane: WorkChatPane) => {
    if (panes.length === 1) {
      patchPane(pane.id, { sessionId: null, chatKey: pane.chatKey + 1 })
      return
    }
    const remaining = panes.filter((item) => item.id !== pane.id)
    setPanes(remaining)
    if (activePaneId === pane.id) setActivePaneId(remaining[0]?.id ?? '')
  }

  const queueStart = (pane: WorkChatPane, project: Project | null) => {
    setPaneActionError(null)
    setStartCommands((current) => ({
      ...current,
      [pane.id]: {
        key: Date.now(),
        prompt: startPromptForPane(pane, project),
      },
    }))
  }

  const pausePane = async (pane: WorkChatPane) => {
    if (!pane.sessionId) return
    setPaneActionError(null)
    try {
      await cancelAgentHubSessionStream(pane.sessionId)
    } catch (error) {
      setPaneActionError(
        error instanceof Error ? error.message : 'Pause failed',
      )
    }
  }

  const stopPane = async (pane: WorkChatPane) => {
    if (!pane.sessionId) return
    setPaneActionError(null)
    try {
      await cancelAgentHubSessionStream(pane.sessionId).catch(() => null)
      await closeAgentHubSession(pane.sessionId)
    } catch (error) {
      setPaneActionError(error instanceof Error ? error.message : 'Stop failed')
    }
  }

  if (!panes.length) {
    return (
      <div className="flex h-[calc(100dvh-66px)] items-center justify-center text-sm text-slate-500 lg:h-[calc(100dvh-70px)]">
        Loading...
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100dvh-66px)] min-h-0 flex-col overflow-hidden bg-slate-950 lg:h-[calc(100dvh-70px)]">
      <div className="flex h-9 shrink-0 items-center gap-1 overflow-x-auto border-b border-slate-800 bg-slate-900/90 px-1.5">
        <PaneBadge title="SummitFlow Work Chats" active>
          <PanelsTopLeft className="h-3.5 w-3.5" />
        </PaneBadge>
        <SelectControl
          value={activePaneId}
          onChange={setActivePaneId}
          label="Active pane"
          className="w-44 md:hidden"
        >
          {panes.map((pane, index) => (
            <option key={pane.id} value={pane.id}>
              Pane {index + 1} - {pane.agentSlug}
            </option>
          ))}
        </SelectControl>
        <div className="flex items-center gap-1">
          {(
            [
              'main-side',
              'horizontal',
              'vertical',
              'two-by-two',
              'wide-grid',
            ] as WorkChatLayout[]
          ).map((item) => (
            <LayoutButton
              key={item}
              value={item}
              active={layout === item}
              onClick={() => setLayout(item)}
            />
          ))}
        </div>
        <IconButton
          title="Add pane"
          disabled={panes.length >= MAX_PANES}
          onClick={() => {
            if (panes.length >= MAX_PANES) return
            const next = makePane(defaultAgent)
            setPanes((current) => [...current, next])
            setActivePaneId(next.id)
          }}
        >
          <Plus className="h-3.5 w-3.5" />
        </IconButton>
        <div className="flex-1" />
        {paneActionError ? (
          <span className="text-xs text-rose-400">{paneActionError}</span>
        ) : null}
      </div>

      <main
        className={cn(
          'grid min-h-0 flex-1 auto-rows-fr overflow-hidden gap-1 p-1',
          layoutClass(layout, visiblePanes.length),
        )}
      >
        {visiblePanes.map((pane, index) => {
          const project = pane.projectId
            ? (projects.find((item) => item.id === pane.projectId) ?? null)
            : null
          const isActive = activePaneId === pane.id
          return (
            <WorkChatPaneView
              key={pane.id}
              pane={pane}
              active={isActive}
              index={index}
              paneCount={visiblePanes.length}
              layout={layout}
              agents={agents}
              sessions={sessions}
              projects={projects}
              childSessions={isActive ? childSessions : []}
              actionRequests={isActive ? actionRequests : []}
              startCommand={startCommands[pane.id]}
              onActivate={() => setActivePaneId(pane.id)}
              onPatch={(patch) => patchPane(pane.id, patch)}
              onNewChat={() =>
                patchPane(pane.id, {
                  sessionId: null,
                  chatKey: pane.chatKey + 1,
                })
              }
              onSplit={() => splitPane(pane)}
              onClose={() => closePane(pane)}
              onStart={() => queueStart(pane, project)}
              onPause={() => void pausePane(pane)}
              onStop={() => void stopPane(pane)}
            />
          )
        })}
      </main>
    </div>
  )
}

export default function WorkChatsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[calc(100dvh-66px)] items-center justify-center text-sm text-slate-500 lg:h-[calc(100dvh-70px)]">
          Loading...
        </div>
      }
    >
      <WorkChatsContent />
    </Suspense>
  )
}
