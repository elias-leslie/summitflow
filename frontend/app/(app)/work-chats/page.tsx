'use client'

import { ChatPanel as BaseChatPanel } from '@agent-hub/chat-ui'
import {
  Columns2,
  Grid2X2,
  Maximize2,
  MessageSquarePlus,
  PanelRightClose,
  PanelsTopLeft,
  Pause,
  Play,
  Rows2,
  SquareSplitHorizontal,
  StopCircle,
  X,
} from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import {
  type ComponentProps,
  type ComponentType,
  Suspense,
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

type WorkChatPanelProps = ComponentProps<typeof BaseChatPanel> & {
  autoSendPrompt?: string | null
  autoSendKey?: string | number | null
}

const ChatPanel = BaseChatPanel as ComponentType<WorkChatPanelProps>

const STORAGE_KEY = 'summitflow_work_chats_v1'
const MAX_PANES = 6
const SOURCE_CLIENT = 'summitflow/work-chats'
const GENERAL_PROJECT_ID = 'summitflow'

function makePane(agentSlug = 'chat'): WorkChatPane {
  return {
    id: `pane-${Math.random().toString(36).slice(2, 10)}`,
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
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex h-8 w-8 items-center justify-center rounded-md border transition-colors',
        active
          ? 'border-phosphor-500/40 bg-phosphor-500/10 text-phosphor-300'
          : 'border-slate-700 bg-slate-900/70 text-slate-500 hover:border-slate-600 hover:text-slate-200',
      )}
      title={value}
      aria-label={value}
    >
      <Icon className="h-4 w-4" />
    </button>
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
      className={cn(
        'h-8 min-w-28 rounded-md border border-slate-700 bg-slate-950/70 px-2 text-xs text-slate-200 outline-none transition-colors',
        'hover:border-slate-600 focus:border-phosphor-500/50 disabled:cursor-not-allowed disabled:opacity-40',
        className,
      )}
    >
      {children}
    </select>
  )
}

function IconButton({
  title,
  onClick,
  disabled = false,
  children,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-slate-950/70 text-slate-400 transition-colors hover:border-slate-600 hover:bg-slate-800/80 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function PaneToolbar({
  pane,
  agents,
  sessions,
  projects,
  onPatch,
  onNewChat,
  onSplit,
  onClose,
  onStart,
  onPause,
  onStop,
}: {
  pane: WorkChatPane
  agents: AgentHubAgent[]
  sessions: AgentHubSessionListItem[]
  projects: Project[]
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

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 bg-slate-900/80 px-2 py-2">
      <IconButton title="New Chat" onClick={onNewChat}>
        <MessageSquarePlus className="h-4 w-4" />
      </IconButton>
      <IconButton title="Split Pane" onClick={onSplit}>
        <Columns2 className="h-4 w-4" />
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
        <Maximize2 className="h-4 w-4" />
      </IconButton>
      <IconButton
        title={pane.sessionId ? 'Resume Work' : 'Start Work'}
        onClick={onStart}
      >
        <Play className="h-4 w-4" />
      </IconButton>
      <IconButton title="Pause" onClick={onPause} disabled={!pane.sessionId}>
        <Pause className="h-4 w-4" />
      </IconButton>
      <IconButton title="Stop" onClick={onStop} disabled={!pane.sessionId}>
        <StopCircle className="h-4 w-4" />
      </IconButton>

      <SelectControl
        value={pane.agentSlug}
        onChange={(value) => onPatch({ agentSlug: value })}
        label="Change Agent"
        className="min-w-40"
      >
        {agents.map((agent) => (
          <option key={agent.slug} value={agent.slug}>
            {agent.name} · {agent.slug}
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
        label="Change Project Context"
        className="min-w-36"
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
        label="Change Task Context"
        disabled={!pane.projectId}
        className="min-w-44"
      >
        <option value="">No task</option>
        {displayedTasks.map((task) => (
          <option key={task.id} value={task.id}>
            {task.id} · {task.title}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={pane.feedbackId ?? ''}
        onChange={(value) => {
          const feedback = feedbackItems.find((item) => item.id === value)
          onPatch({
            feedbackId: feedback?.id ?? null,
            artifactSummary: feedback?.title ?? pane.artifactSummary,
            taskId: feedback?.linked_task_id ?? pane.taskId,
          })
        }}
        label="Change Feedback Context"
        disabled={!pane.projectId}
        className="min-w-36"
      >
        <option value="">No feedback</option>
        {feedbackItems.map((item) => (
          <option key={item.id} value={item.id}>
            {item.title}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={pane.designId ?? ''}
        onChange={(value) => {
          const mockup = mockups.find((item) => item.mockup_id === value)
          onPatch({
            designId: mockup?.mockup_id ?? null,
            artifactSummary: mockup?.name ?? pane.artifactSummary,
            taskId: mockup?.task_id ?? pane.taskId,
          })
        }}
        label="Change Design Context"
        disabled={!pane.projectId}
        className="min-w-36"
      >
        <option value="">No design</option>
        {mockups.map((mockup) => (
          <option key={mockup.mockup_id} value={mockup.mockup_id}>
            {mockup.name}
          </option>
        ))}
      </SelectControl>

      <SelectControl
        value={pane.sessionId ?? ''}
        onChange={(value) => onPatch({ sessionId: value || null })}
        label="Attach Existing Session"
        className="min-w-40"
      >
        <option value="">New session</option>
        {sessions.map((session) => (
          <option key={session.id} value={session.id}>
            {session.id.slice(0, 8)} · {session.agent_slug ?? 'agent'}
          </option>
        ))}
      </SelectControl>

      <div className="flex-1" />
      <IconButton title="Close Pane" onClick={onClose}>
        <X className="h-4 w-4" />
      </IconButton>
    </div>
  )
}

function SourceBadges({
  pane,
  hasTelegram,
}: {
  pane: WorkChatPane
  hasTelegram: boolean
}) {
  const badges = ['Web', 'SummitFlow']
  if (hasTelegram) badges.push('Telegram')
  if (pane.sessionId) badges.push('Session')
  if (pane.taskId) badges.push('Task')
  if (pane.feedbackId) badges.push('Feedback')
  if (pane.designId) badges.push('Design')

  return (
    <div className="flex flex-wrap gap-1">
      {badges.map((badge) => (
        <span
          key={badge}
          className="rounded border border-slate-700 bg-slate-950/70 px-1.5 py-0.5 text-[10px] text-slate-400"
        >
          {badge}
        </span>
      ))}
    </div>
  )
}

function RightRail({
  sessionId,
  childSessions,
  actionRequests,
}: {
  sessionId: string | null
  childSessions: AgentHubSessionListItem[]
  actionRequests: ActionRequest[]
}) {
  return (
    <aside className="hidden w-80 shrink-0 border-l border-slate-800 bg-slate-900/70 p-3 xl:block">
      <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-slate-500">
        Child Lanes
      </div>
      <div className="mt-2 space-y-2 text-xs">
        {childSessions.length ? (
          childSessions.map((session) => (
            <div
              key={session.id}
              className="rounded-md border border-slate-800 bg-slate-950/60 p-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-slate-300">
                  {session.id.slice(0, 8)}
                </span>
                <span className="text-slate-500">{session.status}</span>
              </div>
              <div className="mt-1 line-clamp-2 text-slate-400">
                {session.summary_oneliner ??
                  session.live_activity?.summary ??
                  session.workstream_status ??
                  'working'}
              </div>
              {session.observed_write_paths?.length ? (
                <div className="mt-1 truncate text-phosphor-400">
                  {session.observed_write_paths.slice(0, 3).join(', ')}
                </div>
              ) : null}
              {session.live_activity?.last_validation_command ? (
                <div className="mt-1 truncate text-amber-300">
                  {session.live_activity.last_validation_command}
                </div>
              ) : null}
            </div>
          ))
        ) : (
          <div className="text-slate-600">
            {sessionId ? 'No child lanes' : 'No session attached'}
          </div>
        )}
      </div>

      <div className="mt-4 text-[10px] font-medium uppercase tracking-[0.16em] text-slate-500">
        Action Requests
      </div>
      <div className="mt-2 space-y-2 text-xs">
        {actionRequests.length ? (
          actionRequests.map((request) => (
            <div
              key={request.id}
              className="rounded-md border border-slate-800 bg-slate-950/60 p-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-300">
                  {request.request_type}
                </span>
                <span className="text-slate-500">{request.status}</span>
              </div>
              {request.prompt ? (
                <div className="mt-1 line-clamp-3 text-slate-400">
                  {request.prompt}
                </div>
              ) : null}
              {request.join_code ? (
                <div className="mt-1 font-mono text-phosphor-400">
                  /join {request.join_code}
                </div>
              ) : null}
            </div>
          ))
        ) : (
          <div className="text-slate-600">No blockers</div>
        )}
      </div>
    </aside>
  )
}

function WorkChatPaneView({
  pane,
  active,
  index,
  layout,
  agents,
  sessions,
  projects,
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
  layout: WorkChatLayout
  agents: AgentHubAgent[]
  sessions: AgentHubSessionListItem[]
  projects: Project[]
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
  const project = pane.projectId
    ? (projects.find((item) => item.id === pane.projectId) ?? null)
    : null
  const context = workContextForPane(pane, project)
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

  const workingDir = project?.root_path ?? undefined

  return (
    <section
      onClick={onActivate}
      className={cn(
        'flex min-h-[360px] min-w-0 resize flex-col overflow-hidden rounded-lg border bg-slate-950/70',
        active
          ? 'border-phosphor-500/50 shadow-[0_0_0_1px_rgba(0,245,255,0.08)]'
          : 'border-slate-800',
        layout === 'main-side' && index === 0 ? 'xl:row-span-2' : '',
      )}
    >
      <PaneToolbar
        pane={pane}
        agents={agents}
        sessions={sessions}
        projects={projects}
        onPatch={onPatch}
        onNewChat={onNewChat}
        onSplit={onSplit}
        onClose={onClose}
        onStart={onStart}
        onPause={onPause}
        onStop={onStop}
      />

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-2 py-1 text-xs text-slate-500">
        <SourceBadges
          pane={pane}
          hasTelegram={actionRequests.some(
            (request) => request.telegram_chat_id,
          )}
        />
        <span>agent {pane.agentSlug}</span>
        <span>project {pane.projectId ?? 'general'}</span>
        <span>task {pane.taskId ?? 'none'}</span>
        <span>
          session {pane.sessionId ? pane.sessionId.slice(0, 8) : 'new'}
        </span>
      </div>

      <div className="min-h-0 flex-1 chat-outrun">
        <ChatPanel
          key={`${pane.id}:${pane.sessionId ?? 'new'}:${pane.agentSlug}`}
          agentSlug={pane.agentSlug}
          sessionId={pane.sessionId ?? undefined}
          workingDir={workingDir}
          toolsEnabled
          apiConfig={apiConfig}
          modelsEndpoint={`${getAgentHubProxyBase()}/models`}
          title="Work Chat"
          autoSendPrompt={startCommand?.prompt ?? null}
          autoSendKey={startCommand?.key ?? null}
          onSessionCreated={(sessionId) => {
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
          }}
          onClear={() => onPatch({ sessionId: null })}
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
      patchPane(pane.id, { sessionId: null })
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
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        Loading...
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-900/80 px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <PanelsTopLeft className="h-4 w-4 text-phosphor-400" />
          Work Chats
        </div>
        <div className="flex gap-1">
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

        <SelectControl
          value={activePaneId}
          onChange={setActivePaneId}
          label="Active Pane"
          className="md:hidden"
        >
          {panes.map((pane, index) => (
            <option key={pane.id} value={pane.id}>
              Pane {index + 1} · {pane.agentSlug}
            </option>
          ))}
        </SelectControl>

        <button
          type="button"
          onClick={() => {
            if (panes.length >= MAX_PANES) return
            const next = makePane(defaultAgent)
            setPanes((current) => [...current, next])
            setActivePaneId(next.id)
          }}
          className="ml-auto rounded-md border border-slate-700 bg-slate-950/70 px-2 py-1 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100"
        >
          Add Pane
        </button>

        {paneActionError ? (
          <div className="text-xs text-rose-400">{paneActionError}</div>
        ) : null}
      </div>

      <div className="flex min-h-0 flex-1">
        <main
          className={cn(
            'grid min-h-0 flex-1 auto-rows-fr gap-2 p-2',
            layoutClass(layout, visiblePanes.length),
          )}
        >
          {visiblePanes.map((pane, index) => {
            const project = pane.projectId
              ? (projects.find((item) => item.id === pane.projectId) ?? null)
              : null
            return (
              <WorkChatPaneView
                key={pane.id}
                pane={pane}
                active={activePaneId === pane.id}
                index={index}
                layout={layout}
                agents={agents}
                sessions={sessions}
                projects={projects}
                actionRequests={actionRequests}
                startCommand={startCommands[pane.id]}
                onActivate={() => setActivePaneId(pane.id)}
                onPatch={(patch) => patchPane(pane.id, patch)}
                onNewChat={() => patchPane(pane.id, { sessionId: null })}
                onSplit={() => splitPane(pane)}
                onClose={() => closePane(pane)}
                onStart={() => queueStart(pane, project)}
                onPause={() => void pausePane(pane)}
                onStop={() => void stopPane(pane)}
              />
            )
          })}
        </main>
        <RightRail
          sessionId={activePane?.sessionId ?? null}
          childSessions={childSessions}
          actionRequests={actionRequests}
        />
      </div>
    </div>
  )
}

export default function WorkChatsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center text-sm text-slate-500">
          Loading...
        </div>
      }
    >
      <WorkChatsContent />
    </Suspense>
  )
}
