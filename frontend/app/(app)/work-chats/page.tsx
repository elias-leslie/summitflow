'use client'

import {
  ActivityIndicator,
  type AdhocWorkSpec,
  type ChatMessage,
  groupMessages,
  MessageBubble,
  MessageInput,
  type StreamStatus,
  useChatStream,
} from '@agent-hub/chat-ui'
import {
  AlertTriangle,
  ArrowLeftToLine,
  ArrowRightToLine,
  CheckCircle2,
  ClipboardList,
  Columns2,
  GripVertical,
  Layers3,
  Maximize2,
  MessageSquarePlus,
  PanelsTopLeft,
  Pause,
  Play,
  Plus,
  Radio,
  ShieldCheck,
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
import { MockupEditorModal } from '@/components/design/MockupEditorModal'
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
  submitVerifierOutcome,
  upsertWorkChatBinding,
  type WorkContext,
} from '@/lib/api/agent-hub-work-chats'
import { type FeedbackItem, fetchFeedbackItems } from '@/lib/api/feedback'
import {
  analyzePage,
  fetchMockupContext,
  fetchMockups,
  type Mockup,
  type MockupContext,
} from '@/lib/api/mockups'
import { summarizeMockupForWorkContext } from '@/lib/mockup-html'
import { cn } from '@/lib/utils'

type WorkChatLayout =
  | 'horizontal'
  | 'vertical'
  | 'main-side'
  | 'two-by-two'
  | 'wide-grid'
type RoutingMode = 'auto' | 'direct'

interface WorkChatPane {
  id: string
  chatKey: number
  sessionId: string | null
  agentSlug: string
  routingMode: RoutingMode
  projectId: string | null
  taskId: string | null
  taskTitle: string | null
  taskSummary: string | null
  feedbackId: string | null
  designId: string | null
  artifactSummary: string | null
  verifierEnabled: boolean
  verifierChatKey: number
  verifierSessionId: string | null
  verifierSplitPercent: number
  verifierLoopCount: number
  verifierLastBuilderSessionId: string | null
}

interface WorkStartCommand {
  key: number
  prompt: string
}

interface WorkChatController {
  sendMessage: (content: string) => void
  cancelStream: () => void
  sessionId: string | null
  status: StreamStatus
}

interface ArtifactOption {
  value: string
  label: string
  kind: 'feedback' | 'design'
  id: string
  linkedTaskId?: string | null
  mockup?: Mockup
}

interface MockupEditorTarget {
  projectId: string
  mockupId: string
  paneId: string
}

const STORAGE_KEY = 'summitflow_work_chats_v2'
const MAX_PANES = 6
const SOURCE_CLIENT = 'summitflow/work-chats'
const GENERAL_PROJECT_ID = 'summitflow'
const AUTO_AGENT_SLUG = 'persona'
const VERIFIER_AGENT_SLUG = 'verifier'
const WORK_CHAT_PERSONA_ROLES = [
  'system',
  'persona-personality',
  'persona-user-context',
]
const DEFAULT_VERIFIER_SPLIT = 50
const BUILDER_SNAP_PERCENT = 88
const VERIFIER_SNAP_PERCENT = 12
const VERIFIER_MIN_PERCENT = 12
const VERIFIER_MAX_PERCENT = 88
const VERIFIER_COLLAPSE_THRESHOLD = 18
const VERIFIER_MAX_LOOPS = 3

function makePane(agentSlug = AUTO_AGENT_SLUG): WorkChatPane {
  return {
    id: `pane-${Math.random().toString(36).slice(2, 10)}`,
    chatKey: 0,
    sessionId: null,
    agentSlug,
    routingMode: agentSlug === AUTO_AGENT_SLUG ? 'auto' : 'direct',
    projectId: null,
    taskId: null,
    taskTitle: null,
    taskSummary: null,
    feedbackId: null,
    designId: null,
    artifactSummary: null,
    verifierEnabled: false,
    verifierChatKey: 0,
    verifierSessionId: null,
    verifierSplitPercent: DEFAULT_VERIFIER_SPLIT,
    verifierLoopCount: 0,
    verifierLastBuilderSessionId: null,
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
          .map((pane: Partial<WorkChatPane>) => {
            const savedAgent = pane.agentSlug ?? defaultAgent
            const routingMode =
              pane.routingMode ??
              (savedAgent === AUTO_AGENT_SLUG || savedAgent === 'chat'
                ? 'auto'
                : 'direct')
            const basePane = makePane(defaultAgent)
            return {
              ...basePane,
              id: pane.id ?? basePane.id,
              sessionId: pane.sessionId ?? null,
              agentSlug: routingMode === 'auto' ? AUTO_AGENT_SLUG : savedAgent,
              routingMode,
              projectId: pane.projectId ?? null,
              taskId: pane.taskId ?? null,
              taskTitle: pane.taskTitle ?? null,
              taskSummary: pane.taskSummary ?? null,
              feedbackId: pane.feedbackId ?? null,
              designId: pane.designId ?? null,
              artifactSummary: pane.artifactSummary ?? null,
              chatKey: pane.chatKey ?? 0,
              verifierEnabled: pane.verifierEnabled ?? false,
              verifierChatKey: pane.verifierChatKey ?? 0,
              verifierSessionId: pane.verifierSessionId ?? null,
              verifierSplitPercent:
                pane.verifierSplitPercent ?? DEFAULT_VERIFIER_SPLIT,
              verifierLoopCount: pane.verifierLoopCount ?? 0,
              verifierLastBuilderSessionId:
                pane.verifierLastBuilderSessionId ?? null,
            } satisfies WorkChatPane
          })
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

function adhocWorkSpecForPane(
  pane: WorkChatPane,
  project: Project | null,
): AdhocWorkSpec {
  const isProjectWork = Boolean(pane.projectId)
  const isImplementationWork = Boolean(pane.taskId || pane.feedbackId)
  const isDesignWork = Boolean(pane.designId)

  let workloadProfile: string
  if (isDesignWork) workloadProfile = 'frontend_ux'
  else if (isImplementationWork) workloadProfile = 'coding_impl'
  else if (isProjectWork) workloadProfile = 'planning'
  else workloadProfile = 'general'

  let taskType: string
  if (pane.taskId) taskType = 'project_task'
  else if (pane.feedbackId) taskType = 'feedback_work'
  else if (pane.designId) taskType = 'design_work'
  else if (isProjectWork) taskType = 'project_work'
  else taskType = 'general'

  const riskTier = isImplementationWork ? 'normal' : 'low'
  const toolMode = isProjectWork ? 'write' : 'read_only'
  const costPreference = isImplementationWork ? 'balanced' : 'low_cost'

  const capabilities: Record<string, number> = {
    reasoning: 0.7,
    tool_use: isProjectWork ? 0.8 : 0.4,
    ...(isProjectWork && { coding: isImplementationWork ? 0.85 : 0.55 }),
    ...(isDesignWork && { vision: 0.45 }),
    ...(!isProjectWork && { research: 0.45 }),
  }

  return {
    title:
      pane.taskTitle ??
      pane.artifactSummary ??
      (project ? `${project.name} work chat` : 'General work chat'),
    task_type: taskType,
    workload_profile: workloadProfile,
    risk_tier: riskTier,
    tool_mode: toolMode,
    context: {
      project_id: pane.projectId ?? undefined,
      task_id: pane.taskId ?? undefined,
      feedback_id: pane.feedbackId ?? undefined,
      design_id: pane.designId ?? undefined,
      surface: 'work_chats',
      pane_id: pane.id,
    },
    expected_output:
      'result, evidence, files/checks when changed, exact blocker if blocked',
    routing_judgment: {
      workload_profile: workloadProfile,
      risk_tier: riskTier,
      capabilities,
      constraints: {
        needs_repo_access: isProjectWork,
        verifier_enabled: pane.verifierEnabled,
        source_surface: 'work_chats',
      },
      confidence: 0.7,
      rationale: 'Derived from Work Chats context.',
    },
    routing: {
      cost_preference: costPreference,
    },
  }
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
    routing_mode: pane.routingMode,
    verifier_enabled: pane.verifierEnabled,
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
    adhoc_spec:
      pane.routingMode === 'auto'
        ? adhocWorkSpecForPane(pane, project)
        : undefined,
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
  if (pane.routingMode === 'auto') {
    lines.push(
      'Routing mode: Auto Jenny. Answer directly or delegate based on work_context and Agent Hub routing.',
      'For flexible child work, use bash `st agent run --adhoc --json <workspec>` from work_context.adhoc_spec; do not choose a provider or model.',
    )
  } else {
    lines.push(`Direct agent mode: ${pane.agentSlug}.`)
  }
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

function verifierPromptForPane(
  pane: WorkChatPane,
  project: Project | null,
  parentMessages: ChatMessage[] = [],
  childSessions: AgentHubSessionListItem[] = [],
): string {
  const parentSession = pane.sessionId ?? 'unknown'
  const recentMessages = parentMessages.slice(-8)
  const lines = [
    'Verification Cycle',
    '',
    `Parent session: ${parentSession}`,
    `Verifier loop: ${pane.verifierLoopCount + 1}/${VERIFIER_MAX_LOOPS}`,
    '',
    'Verify the latest completed builder turn in the parent Work Chat session.',
    'Use work_context, parent_session_id, session events, tool output, artifacts, diffs, and current repo state as evidence.',
    'Treat the builder final response as a claim, not proof. Decompose into atomic claims.',
    'If a concrete fix is needed, put the exact corrective builder prompt in the report section "What feedback did you give?".',
    'End with the required ## Report block.',
  ]
  if (pane.taskId) {
    lines.push(
      `Task ${pane.taskId}${pane.taskTitle ? `: ${pane.taskTitle}` : ''}.`,
    )
  } else if (pane.projectId) {
    lines.push(`Project ${project?.name ?? pane.projectId}.`)
  }
  if (pane.artifactSummary) lines.push(`Artifact: ${pane.artifactSummary}.`)
  if (childSessions.length) {
    lines.push('', 'Child agent sessions to verify as part of Jenny routing:')
    childSessions.forEach((session) => {
      const summary =
        session.summary_oneliner ??
        session.live_activity?.summary ??
        session.summary_outcome ??
        session.workstream_status ??
        ''
      lines.push(
        `- ${session.agent_slug ?? 'agent'} | ${session.status} | ${session.id}${summary ? ` | ${summary}` : ''}`,
      )
    })
  }
  if (recentMessages.length) {
    lines.push('', 'Parent turn excerpt:')
    recentMessages.forEach((message, index) => {
      const content = message.content.trim().slice(0, 4000)
      lines.push(
        `--- message ${index + 1} role=${message.role} id=${message.id} ---`,
        content || '(empty)',
      )
    })
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

function agentName(agents: AgentHubAgent[], slug: string | null | undefined) {
  if (!slug) return 'agent'
  return agents.find((agent) => agent.slug === slug)?.name ?? slug
}

function autoAgentLabel(agents: AgentHubAgent[]) {
  return `Auto: ${agentName(agents, AUTO_AGENT_SLUG)}`
}

function paneAgentLabel(pane: WorkChatPane, agents: AgentHubAgent[]) {
  if (pane.routingMode === 'auto') return autoAgentLabel(agents)
  return agentName(agents, pane.agentSlug)
}

function paneContextLabel(pane: WorkChatPane, projects: Project[]) {
  const project = pane.projectId
    ? (projects.find((item) => item.id === pane.projectId)?.name ??
      pane.projectId)
    : 'General'
  if (pane.taskId) {
    return `${project} / ${pane.taskTitle ?? pane.taskId}`
  }
  if (pane.artifactSummary) {
    return `${project} / ${pane.artifactSummary}`
  }
  return project
}

function sessionSummary(session: AgentHubSessionListItem) {
  return (
    session.summary_oneliner ??
    session.live_activity?.summary ??
    session.summary_outcome ??
    session.workstream_status ??
    ''
  )
}

function resetChatRuntimePatch(pane: WorkChatPane): Partial<WorkChatPane> {
  return {
    sessionId: null,
    chatKey: pane.chatKey + 1,
    verifierSessionId: null,
    verifierChatKey: pane.verifierChatKey + 1,
    verifierLoopCount: 0,
    verifierLastBuilderSessionId: null,
  }
}

function sessionResumePatch(
  pane: WorkChatPane,
  session: AgentHubSessionListItem,
): Partial<WorkChatPane> {
  const agentSlug = session.agent_slug ?? AUTO_AGENT_SLUG
  const externalTaskId = session.external_id?.startsWith('task-')
    ? session.external_id
    : null
  return {
    sessionId: session.id,
    agentSlug,
    routingMode: agentSlug === AUTO_AGENT_SLUG ? 'auto' : 'direct',
    projectId: session.project_id ?? pane.projectId,
    taskId: externalTaskId ?? pane.taskId,
    verifierSessionId: null,
    verifierChatKey: pane.verifierChatKey + 1,
    verifierLoopCount: 0,
    verifierLastBuilderSessionId: null,
  }
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
  const feedbackOptions: ArtifactOption[] = feedbackItems.map((item) => ({
    value: `feedback:${item.id}`,
    label: item.title,
    kind: 'feedback' as const,
    id: item.id,
    linkedTaskId: item.linked_task_id,
  }))
  const designOptions: ArtifactOption[] = mockups.map((mockup) => ({
    value: `design:${mockup.mockup_id}`,
    label: mockup.name,
    kind: 'design' as const,
    id: mockup.mockup_id,
    linkedTaskId: mockup.task_id,
    mockup,
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
  verifierStatus,
  verifierError,
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
  onOpenChildSession,
  onOpenMockup,
  onSendPaneMessage,
}: {
  pane: WorkChatPane
  status: StreamStatus
  error: string | null
  verifierStatus: StreamStatus
  verifierError: string | null
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
  onOpenChildSession: (session: AgentHubSessionListItem) => void
  onOpenMockup: (target: MockupEditorTarget) => void
  onSendPaneMessage: (prompt: string) => void
}) {
  const [contextOpen, setContextOpen] = useState(false)
  const [sessionsOpen, setSessionsOpen] = useState(false)
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
  const selectedDesignArtifact = artifacts.find(
    (artifact) =>
      artifact.value === selectedArtifact && artifact.kind === 'design',
  )
  const currentProject = pane.projectId
    ? (projects.find((project) => project.id === pane.projectId) ?? null)
    : null
  const [isAnalyzingPage, setIsAnalyzingPage] = useState(false)
  const hasTelegram = actionRequests.some((request) => request.telegram_chat_id)
  const blockers = actionRequests.filter(
    (request) => request.status !== 'resolved',
  )
  const contextLabel = paneContextLabel(pane, projects)
  const currentSession = pane.sessionId
    ? (sessions.find((session) => session.id === pane.sessionId) ?? null)
    : null
  const sessionOptions = sessions.filter((session) => {
    if (pane.projectId && session.project_id !== pane.projectId) return false
    if (
      pane.taskId &&
      session.external_id &&
      session.external_id.startsWith('task-') &&
      session.external_id !== pane.taskId
    ) {
      return false
    }
    return true
  })
  const activityBits = [
    pane.sessionId ? `session ${pane.sessionId.slice(0, 8)}` : 'new session',
    childSessions.length ? `${childSessions.length} child lanes` : null,
    blockers.length ? `${blockers.length} requests` : null,
    pane.verifierEnabled
      ? verifierError
        ? 'verifier error'
        : verifierStatus === 'streaming' || verifierStatus === 'connecting'
          ? `verifier ${verifierStatus}`
          : 'verifier'
      : null,
    hasTelegram ? 'telegram' : null,
  ].filter(Boolean)

  const sendDesignContext = async () => {
    if (!pane.projectId || !pane.designId) return
    try {
      const context = await fetchMockupContext(pane.projectId, pane.designId)
      onSendPaneMessage(
        [
          'Use this design artifact as current Work Chat context.',
          `Artifact context: ${context.compact_summary}`,
          `Artifact id: ${context.mockup_id}`,
          'Full HTML is stored in per-project Design; fetch it only if needed.',
        ].join('\n'),
      )
    } catch {
      const summary = selectedDesignArtifact?.mockup
        ? summarizeMockupForWorkContext(selectedDesignArtifact.mockup)
        : `${pane.artifactSummary ?? pane.designId} (${pane.designId})`
      onSendPaneMessage(
        [
          'Use this design artifact as current Work Chat context.',
          `Artifact: ${summary}`,
          'Discuss it, revise the mockup, create tasks, or plan page implementation as needed.',
        ].join('\n'),
      )
    }
  }

  const analyzeDesignPage = async () => {
    const pagePath = selectedDesignArtifact?.mockup?.page_path
    const baseUrl = currentProject?.public_url || currentProject?.base_url
    if (!pane.projectId || !pagePath || !baseUrl) return
    setIsAnalyzingPage(true)
    try {
      const pageUrl = new URL(pagePath, baseUrl).toString()
      const result = await analyzePage(pane.projectId, pageUrl, pagePath)
      if (result.success && result.mockup_id) {
        onPatch({
          designId: result.mockup_id,
          artifactSummary: `Page analysis ${pagePath}`,
        })
        onSendPaneMessage(
          [
            'I captured and analyzed the current page into a project Design artifact.',
            `Mockup: ${result.mockup_id}`,
            `Page: ${pagePath}`,
            result.recommendations
              ? `Compact findings: ${result.recommendations.slice(0, 1200)}`
              : '',
          ]
            .filter(Boolean)
            .join('\n'),
        )
      } else {
        onSendPaneMessage(
          `Page design analysis failed for ${pagePath}: ${result.error ?? 'unknown error'}`,
        )
      }
    } catch (error) {
      onSendPaneMessage(
        `Page design analysis failed for ${pagePath}: ${
          error instanceof Error ? error.message : 'unknown error'
        }`,
      )
    } finally {
      setIsAnalyzingPage(false)
    }
  }

  return (
    <div className="shrink-0 border-b border-slate-800 bg-slate-900/90">
      <div className="flex min-h-10 items-center gap-2 px-2">
        <PaneStatus status={status} error={error} />
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-sm font-medium text-slate-100">
              {paneAgentLabel(pane, agents)}
            </span>
            <span className="truncate text-xs text-slate-500">
              {contextLabel}
            </span>
          </div>
          <div className="truncate text-[10px] text-slate-600">
            {activityBits.join(' / ')}
          </div>
        </div>

        <IconButton
          title={contextOpen ? 'Hide context' : 'Context'}
          active={contextOpen}
          onClick={() => setContextOpen((value) => !value)}
        >
          <ClipboardList className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton
          title={sessionsOpen ? 'Hide sessions' : 'Sessions'}
          active={sessionsOpen}
          onClick={() => setSessionsOpen((value) => !value)}
        >
          <Radio className="h-3.5 w-3.5" />
        </IconButton>
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
            params.set('routing_mode', pane.routingMode)
            if (pane.routingMode === 'direct')
              params.set('agent_slug', pane.agentSlug)
            if (pane.projectId) params.set('project_id', pane.projectId)
            if (pane.taskId) params.set('task_id', pane.taskId)
            if (pane.taskTitle) params.set('task_title', pane.taskTitle)
            if (pane.verifierEnabled) params.set('verifier', '1')
            if (pane.verifierSessionId) {
              params.set('verifier_session_id', pane.verifierSessionId)
            }
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
        <IconButton
          title="Pause"
          onClick={onPause}
          disabled={!pane.sessionId && !pane.verifierSessionId}
        >
          <Pause className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton
          title="Stop"
          onClick={onStop}
          disabled={!pane.sessionId && !pane.verifierSessionId}
        >
          <StopCircle className="h-3.5 w-3.5" />
        </IconButton>
        <IconButton title="Close pane" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </IconButton>
      </div>

      {contextOpen ? (
        <div className="grid gap-2 border-t border-slate-800/70 bg-slate-950/55 p-2 md:grid-cols-[minmax(140px,1fr)_minmax(180px,1.4fr)_minmax(160px,1fr)_auto]">
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
                ...resetChatRuntimePatch(pane),
              })
            }
            label="Project"
            className="w-full"
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
                ...resetChatRuntimePatch(pane),
              })
            }}
            label="Task"
            disabled={!pane.projectId}
            className="w-full"
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
                  ...resetChatRuntimePatch(pane),
                })
                return
              }
              onPatch({
                feedbackId: artifact.kind === 'feedback' ? artifact.id : null,
                designId: artifact.kind === 'design' ? artifact.id : null,
                artifactSummary: artifact.label,
                taskId: artifact.linkedTaskId ?? pane.taskId,
                ...resetChatRuntimePatch(pane),
              })
            }}
            label="Feedback or design"
            disabled={!pane.projectId}
            className="w-full"
          >
            <option value="">No artifact</option>
            {artifacts.map((artifact) => (
              <option key={artifact.value} value={artifact.value}>
                {artifact.kind} - {artifact.label}
              </option>
            ))}
          </SelectControl>

          <label
            title="Enable verifier"
            className={cn(
              'flex h-7 shrink-0 cursor-pointer items-center gap-2 rounded border px-2 text-xs transition-colors',
              pane.verifierEnabled
                ? 'border-phosphor-500/40 bg-phosphor-500/10 text-phosphor-200'
                : 'border-slate-800 bg-slate-950/60 text-slate-500 hover:border-slate-600 hover:text-slate-200',
            )}
          >
            <input
              type="checkbox"
              checked={pane.verifierEnabled}
              onChange={(event) =>
                onPatch({
                  verifierEnabled: event.target.checked,
                  verifierLoopCount: event.target.checked
                    ? pane.verifierLoopCount
                    : 0,
                })
              }
              className="h-3 w-3 accent-cyan-400"
              aria-label="Enable verifier"
            />
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>Verify</span>
          </label>

          {pane.projectId && pane.designId ? (
            <div className="flex min-w-0 items-center gap-2 md:col-span-4">
              <Layers3 className="h-3.5 w-3.5 shrink-0 text-phosphor-300" />
              <span className="min-w-0 flex-1 truncate text-xs text-slate-300">
                {pane.artifactSummary ?? pane.designId}
              </span>
              {selectedDesignArtifact?.mockup?.version ? (
                <span className="rounded border border-slate-800 bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                  v{selectedDesignArtifact.mockup.version}
                </span>
              ) : null}
              <button
                type="button"
                onClick={() =>
                  onOpenMockup({
                    projectId: pane.projectId!,
                    mockupId: pane.designId!,
                    paneId: pane.id,
                  })
                }
                className="h-7 shrink-0 rounded border border-phosphor-500/30 bg-phosphor-500/10 px-2 text-xs text-phosphor-200 hover:bg-phosphor-500/15"
              >
                Open mock
              </button>
              <button
                type="button"
                onClick={() => void sendDesignContext()}
                className="h-7 shrink-0 rounded border border-slate-700 bg-slate-950/70 px-2 text-xs text-slate-300 hover:border-phosphor-500/50 hover:text-phosphor-200"
              >
                Send context
              </button>
              {selectedDesignArtifact?.mockup?.page_path ? (
                <button
                  type="button"
                  onClick={() => void analyzeDesignPage()}
                  disabled={isAnalyzingPage}
                  className="h-7 shrink-0 rounded border border-slate-700 bg-slate-950/70 px-2 text-xs text-slate-300 hover:border-phosphor-500/50 hover:text-phosphor-200 disabled:opacity-50"
                >
                  {isAnalyzingPage ? 'Analyzing' : 'Analyze page'}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {sessionsOpen ? (
        <div className="border-t border-slate-800/70 bg-slate-950/70 p-2">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-300">
              Resume Session
            </span>
            {currentSession ? (
              <span className="truncate text-[10px] text-slate-500">
                current {currentSession.id.slice(0, 8)} /{' '}
                {agentName(agents, currentSession.agent_slug)}
              </span>
            ) : null}
          </div>
          <div className="flex max-h-36 flex-col gap-1 overflow-y-auto">
            <button
              type="button"
              onClick={() =>
                onPatch({
                  ...resetChatRuntimePatch(pane),
                })
              }
              className="flex h-8 items-center gap-2 rounded border border-slate-800 bg-slate-950/80 px-2 text-left text-xs text-slate-300 hover:border-phosphor-500/50 hover:text-phosphor-200"
            >
              <MessageSquarePlus className="h-3.5 w-3.5 shrink-0 text-phosphor-300" />
              New session
            </button>
            {sessionOptions.map((session) => {
              const summary = sessionSummary(session)
              const activeSession = session.id === pane.sessionId
              return (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => onPatch(sessionResumePatch(pane, session))}
                  title={summary || session.id}
                  className={cn(
                    'flex h-8 min-w-0 items-center gap-2 rounded border px-2 text-left text-xs transition-colors',
                    activeSession
                      ? 'border-phosphor-500/40 bg-phosphor-500/10 text-phosphor-200'
                      : 'border-slate-800 bg-slate-950/80 text-slate-300 hover:border-phosphor-500/50 hover:text-phosphor-200',
                  )}
                >
                  <Radio className="h-3.5 w-3.5 shrink-0 text-slate-500" />
                  <span className="w-20 shrink-0 font-mono text-[10px] text-slate-500">
                    {session.id.slice(0, 8)}
                  </span>
                  <span className="w-28 shrink-0 truncate">
                    {agentName(agents, session.agent_slug)}
                  </span>
                  <span className="w-20 shrink-0 text-slate-500">
                    {session.status}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-slate-400">
                    {summary || session.external_id || session.project_id}
                  </span>
                </button>
              )
            })}
            {childSessions.map((session) => {
              const summary = sessionSummary(session)
              return (
                <button
                  key={session.id}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onOpenChildSession(session)
                  }}
                  title={summary || session.id}
                  className="flex h-8 min-w-0 items-center gap-2 rounded border border-slate-800 bg-slate-950/80 px-2 text-left text-xs text-slate-300 hover:border-phosphor-500/50 hover:text-phosphor-200"
                >
                  <Workflow className="h-3.5 w-3.5 shrink-0 text-phosphor-300" />
                  <span className="w-20 shrink-0 font-mono text-[10px] text-slate-500">
                    {session.id.slice(0, 8)}
                  </span>
                  <span className="w-28 shrink-0 truncate">
                    {agentName(agents, session.agent_slug)}
                  </span>
                  <span className="w-20 shrink-0 text-slate-500">child</span>
                  <span className="min-w-0 flex-1 truncate text-slate-400">
                    {summary || session.status}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function extractMockupIds(content: string): string[] {
  const ids = [...(content.match(/\bmk-[a-z0-9]{8,}\b/gi) ?? [])]
  const encodedIds =
    content.match(
      /(?:mockup_id|design_id|artifact_id|artifact)[:="'\s]+(mk-[a-z0-9]{8,})/gi,
    ) ?? []
  encodedIds.forEach((value) => {
    const id = value.match(/\bmk-[a-z0-9]{8,}\b/i)?.[0]
    if (id) ids.push(id)
  })
  return Array.from(new Set(ids))
}

function MockupMentionCards({
  content,
  projectId,
  paneId,
  onOpenMockup,
}: {
  content: string
  projectId: string | null
  paneId: string
  onOpenMockup: (target: MockupEditorTarget) => void
}) {
  const ids = projectId ? extractMockupIds(content) : []
  const idsKey = ids.join('|')
  const [contexts, setContexts] = useState<Record<string, MockupContext>>({})

  useEffect(() => {
    if (!projectId || !ids.length) return
    let cancelled = false
    Promise.all(
      ids.map((id) =>
        fetchMockupContext(projectId, id)
          .then((context) => [id, context] as const)
          .catch(() => null),
      ),
    ).then((items) => {
      if (cancelled) return
      setContexts(
        Object.fromEntries(
          items.filter(
            (item): item is readonly [string, MockupContext] => item !== null,
          ),
        ),
      )
    })
    return () => {
      cancelled = true
    }
  }, [idsKey, projectId])

  if (!ids.length || !projectId) return null

  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {ids.map((mockupId) => {
        const context = contexts[mockupId]
        return (
          <button
            key={mockupId}
            type="button"
            onClick={() => onOpenMockup({ projectId, mockupId, paneId })}
            title={context?.compact_summary ?? mockupId}
            className="inline-flex max-w-96 items-center gap-1.5 rounded border border-phosphor-500/25 bg-phosphor-500/8 px-2 py-1 text-xs text-phosphor-200 transition-colors hover:border-phosphor-500/50 hover:bg-phosphor-500/12"
          >
            <Layers3 className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              {context
                ? `${context.name} v${context.version}`
                : `Open mock ${mockupId}`}
            </span>
            {context?.annotation_count ? (
              <span className="rounded bg-slate-950/70 px-1 font-mono text-[10px] text-slate-400">
                {context.annotation_count} notes
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

function WorkChatMessageList({
  messages,
  isStreaming,
  pane,
  onEditMessage,
  onRegenerateMessage,
  onOpenMockup,
}: {
  messages: ChatMessage[]
  isStreaming: boolean
  pane: WorkChatPane
  onEditMessage?: (messageId: string, newContent: string) => void
  onRegenerateMessage?: (messageId: string) => void
  onOpenMockup: (target: MockupEditorTarget) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (!messages.length) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-500">
        <p>Start a conversation</p>
      </div>
    )
  }

  const groupedMessages = groupMessages(messages)

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {groupedMessages.map((item, index) => {
        if (Array.isArray(item)) {
          return (
            <div
              key={item[0].responseGroupId}
              className="flex flex-col gap-3 md:flex-row"
            >
              {item.map((message) => (
                <div key={message.id} className="min-w-0 flex-1">
                  <MessageBubble
                    message={message}
                    isStreaming={
                      isStreaming &&
                      message.role === 'assistant' &&
                      !message.content
                    }
                    onEdit={onEditMessage}
                    onRegenerate={onRegenerateMessage}
                    canEdit={!isStreaming}
                    canRegenerate={!isStreaming}
                    canContinue={!isStreaming}
                  />
                  <MockupMentionCards
                    content={message.content}
                    projectId={pane.projectId}
                    paneId={pane.id}
                    onOpenMockup={onOpenMockup}
                  />
                </div>
              ))}
            </div>
          )
        }

        const message = item
        const isLastMessage = index === groupedMessages.length - 1
        return (
          <div key={message.id}>
            <MessageBubble
              message={message}
              isStreaming={
                isStreaming && message.role === 'assistant' && isLastMessage
              }
              onEdit={onEditMessage}
              onRegenerate={onRegenerateMessage}
              canEdit={!isStreaming}
              canRegenerate={!isStreaming}
              canContinue={!isStreaming}
            />
            <MockupMentionCards
              content={message.content}
              projectId={pane.projectId}
              paneId={pane.id}
              onOpenMockup={onOpenMockup}
            />
          </div>
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}

function WorkChatBody({
  pane,
  apiConfig,
  workingDir,
  startCommand,
  onOpenMockup,
  onRuntimeChange,
  onMessagesChange,
  onTurnFinished,
  onControllerReady,
  onSessionCreated,
}: {
  pane: WorkChatPane
  apiConfig: ReturnType<typeof buildWorkChatApiConfig>
  workingDir?: string
  startCommand?: WorkStartCommand
  onOpenMockup: (target: MockupEditorTarget) => void
  onRuntimeChange: (state: {
    status: StreamStatus
    error: string | null
  }) => void
  onMessagesChange?: (messages: ChatMessage[]) => void
  onTurnFinished?: () => void
  onControllerReady?: (controller: WorkChatController) => void
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
  const previousStatus = useRef<StreamStatus>('idle')
  const turnInFlight = useRef(false)

  const sendTurn = useCallback(
    (content: string, targetModels?: string[]) => {
      turnInFlight.current = true
      sendMessage(content, targetModels)
    },
    [sendMessage],
  )

  useEffect(() => {
    onRuntimeChange({ status, error })
  }, [error, onRuntimeChange, status])

  useEffect(() => {
    onMessagesChange?.(messages)
  }, [messages, onMessagesChange])

  useEffect(() => {
    onControllerReady?.({
      sendMessage: (content: string) => sendTurn(content),
      cancelStream,
      sessionId: currentSessionId,
      status,
    })
  }, [cancelStream, currentSessionId, onControllerReady, sendTurn, status])

  useEffect(() => {
    const wasActive =
      previousStatus.current === 'streaming' ||
      previousStatus.current === 'connecting' ||
      previousStatus.current === 'reconnecting' ||
      previousStatus.current === 'cancelling'
    if (wasActive && status === 'idle' && turnInFlight.current) {
      turnInFlight.current = false
      onTurnFinished?.()
    }
    if (status === 'error') {
      turnInFlight.current = false
    }
    previousStatus.current = status
  }, [onTurnFinished, status])

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
    sendTurn(startCommand.prompt)
  }, [sendTurn, startCommand, status])

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
        <WorkChatMessageList
          messages={messages}
          isStreaming={isStreaming}
          pane={pane}
          onEditMessage={editMessage}
          onRegenerateMessage={regenerateMessage}
          onOpenMockup={onOpenMockup}
        />
      </div>
      <div className="shrink-0 border-t border-slate-800 bg-slate-950/85">
        <MessageInput
          onSend={(message, targetModels) => sendTurn(message, targetModels)}
          onCancel={cancelStream}
          status={status}
          compact
          allowModelMentions={false}
          preferencesEndpoint={`${getAgentHubProxyBase()}/preferences`}
        />
      </div>
    </div>
  )
}

function latestAssistantContent(messages: ChatMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant' && message.content.trim()) {
      return message.content
    }
  }
  return ''
}

function extractReportSection(content: string, heading: string): string {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = content.match(
    new RegExp(
      `^###\\s+${escaped}\\s*$([\\s\\S]*?)(?=^###\\s|^##\\s|(?![\\s\\S]))`,
      'im',
    ),
  )
  return match?.[1]?.trim() ?? ''
}

function parseVerifierReport(content: string): {
  status: string | null
  confidence: string | null
  atomicClaimCount: number | null
  atomicPassCount: number | null
  atomicFailCount: number | null
  feedback: string
  excerpt: string
} {
  const reportIndex = content.search(/^##\s+Report\s*$/im)
  if (reportIndex === -1) {
    return {
      status: null,
      confidence: null,
      atomicClaimCount: null,
      atomicPassCount: null,
      atomicFailCount: null,
      feedback: '',
      excerpt: '',
    }
  }
  const report = content.slice(reportIndex)
  const status = report.match(/^\s*STATUS\s*:\s*([a-z_ -]+)/im)?.[1]?.trim()
  const confidence = report
    .match(/^\s*CONFIDENCE\s*:\s*([a-z_ -]+)/im)?.[1]
    ?.trim()
    .toUpperCase()
  const feedback = extractReportSection(report, 'What feedback did you give?')
  const parseCount = (...patterns: RegExp[]) => {
    for (const pattern of patterns) {
      const match = report.match(pattern)
      if (match?.[1]) return Number.parseInt(match[1], 10)
    }
    return null
  }
  return {
    status: status ?? null,
    confidence: confidence ?? null,
    atomicClaimCount: parseCount(
      /^\s*ATOMIC[_\s-]*CLAIMS?\s*:\s*(\d+)/im,
      /^\s*CLAIMS?\s*:\s*(\d+)/im,
    ),
    atomicPassCount: parseCount(
      /^\s*ATOMIC[_\s-]*PASS(?:ED)?\s*:\s*(\d+)/im,
      /^\s*PASS(?:ED)?\s*:\s*(\d+)/im,
    ),
    atomicFailCount: parseCount(
      /^\s*ATOMIC[_\s-]*FAIL(?:ED)?\s*:\s*(\d+)/im,
      /^\s*FAIL(?:ED)?\s*:\s*(\d+)/im,
    ),
    feedback,
    excerpt: report.slice(0, 5000),
  }
}

function hasVerifierFeedback(report: {
  status: string | null
  confidence: string | null
  feedback: string
}): boolean {
  if (report.status?.toLowerCase() !== 'failed') return false
  if (report.confidence !== 'FEEDBACK') return false
  const normalized = report.feedback.trim().toLowerCase()
  return Boolean(
    normalized &&
      normalized !== 'none' &&
      normalized !== 'nothing' &&
      normalized !== 'n/a',
  )
}

function ChatLane({
  label,
  kind,
  collapsed,
  status,
  error,
  sessionId,
  children,
}: {
  label: string
  kind: 'builder' | 'verifier'
  collapsed: boolean
  status: StreamStatus
  error: string | null
  sessionId: string | null
  children: React.ReactNode
}) {
  const Icon = kind === 'verifier' ? ShieldCheck : MessageSquarePlus

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      <div className="flex h-7 shrink-0 items-center gap-1 border-b border-slate-800 bg-slate-950/80 px-2">
        <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        {!collapsed ? (
          <span className="min-w-0 truncate text-xs font-medium text-slate-300">
            {label}
          </span>
        ) : null}
        <div className="flex-1" />
        <PaneStatus status={status} error={error} />
        {!collapsed && sessionId ? (
          <PaneBadge title={sessionId}>
            <Radio className="h-3.5 w-3.5" />
          </PaneBadge>
        ) : null}
      </div>
      {collapsed ? (
        <div className="flex min-h-0 flex-1 flex-col items-center gap-2 overflow-hidden px-1 py-2 text-[10px] text-slate-500">
          <Icon className="h-4 w-4 text-slate-500" />
          <PaneStatus status={status} error={error} />
          {sessionId ? (
            <span className="max-w-full truncate">{sessionId.slice(0, 8)}</span>
          ) : null}
        </div>
      ) : null}
      <div className={cn('min-h-0 flex-1', collapsed && 'hidden')}>
        {children}
      </div>
    </div>
  )
}

function BuilderVerifierSplit({
  pane,
  builderRuntime,
  verifierRuntime,
  builderSessionId,
  verifierSessionId,
  builderLabel,
  onPatch,
  builder,
  verifier,
}: {
  pane: WorkChatPane
  builderRuntime: { status: StreamStatus; error: string | null }
  verifierRuntime: { status: StreamStatus; error: string | null }
  builderSessionId: string | null
  verifierSessionId: string | null
  builderLabel: string
  onPatch: (patch: Partial<WorkChatPane>) => void
  builder: React.ReactNode
  verifier: React.ReactNode
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [dragging, setDragging] = useState(false)
  const split = Math.min(
    VERIFIER_MAX_PERCENT,
    Math.max(
      VERIFIER_MIN_PERCENT,
      pane.verifierSplitPercent || DEFAULT_VERIFIER_SPLIT,
    ),
  )
  const builderCollapsed = split <= VERIFIER_COLLAPSE_THRESHOLD
  const verifierCollapsed = split >= 100 - VERIFIER_COLLAPSE_THRESHOLD

  const updateFromClientX = useCallback(
    (clientX: number) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect?.width) return
      const next = ((clientX - rect.left) / rect.width) * 100
      onPatch({
        verifierSplitPercent: Math.min(
          VERIFIER_MAX_PERCENT,
          Math.max(VERIFIER_MIN_PERCENT, Math.round(next)),
        ),
      })
    },
    [onPatch],
  )

  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      setDragging(true)
      updateFromClientX(event.clientX)
      const onMove = (moveEvent: PointerEvent) => {
        updateFromClientX(moveEvent.clientX)
      }
      const onUp = () => {
        setDragging(false)
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
    },
    [updateFromClientX],
  )

  return (
    <div ref={containerRef} className="flex h-full min-h-0 overflow-hidden">
      <div
        className="min-h-0 min-w-[92px] overflow-hidden"
        style={{ flexBasis: `${split}%` }}
      >
        <ChatLane
          label={builderLabel}
          kind="builder"
          collapsed={builderCollapsed}
          status={builderRuntime.status}
          error={builderRuntime.error}
          sessionId={builderSessionId}
        >
          {builder}
        </ChatLane>
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={VERIFIER_MIN_PERCENT}
        aria-valuemax={VERIFIER_MAX_PERCENT}
        aria-valuenow={split}
        tabIndex={0}
        onPointerDown={startDrag}
        className={cn(
          'group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center border-x border-slate-800 bg-slate-900/80 outline-none transition-colors',
          'hover:border-phosphor-500/50 hover:bg-slate-800 focus:border-phosphor-500/60',
          dragging && 'border-phosphor-500/70 bg-slate-800',
        )}
      >
        <GripVertical className="h-4 w-4 text-slate-500 group-hover:text-slate-200" />
        <div className="pointer-events-none absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus:pointer-events-auto group-focus:opacity-100">
          <button
            type="button"
            title="Show verifier"
            aria-label="Show verifier"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onPatch({ verifierSplitPercent: VERIFIER_SNAP_PERCENT })
            }}
            className="flex h-6 w-6 items-center justify-center rounded border border-slate-700 bg-slate-950 text-slate-300 shadow hover:border-phosphor-500/60 hover:text-phosphor-200"
          >
            <ArrowLeftToLine className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Show builder"
            aria-label="Show builder"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onPatch({ verifierSplitPercent: BUILDER_SNAP_PERCENT })
            }}
            className="flex h-6 w-6 items-center justify-center rounded border border-slate-700 bg-slate-950 text-slate-300 shadow hover:border-phosphor-500/60 hover:text-phosphor-200"
          >
            <ArrowRightToLine className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div
        className="min-h-0 min-w-[92px] overflow-hidden"
        style={{ flexBasis: `${100 - split}%` }}
      >
        <ChatLane
          label="Verifier"
          kind="verifier"
          collapsed={verifierCollapsed}
          status={verifierRuntime.status}
          error={verifierRuntime.error}
          sessionId={verifierSessionId}
        >
          {verifier}
        </ChatLane>
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
  onOpenChildSession,
  onOpenMockup,
  onSendPaneMessage,
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
  onOpenChildSession: (session: AgentHubSessionListItem) => void
  onOpenMockup: (target: MockupEditorTarget) => void
  onSendPaneMessage: (prompt: string) => void
}) {
  const [builderRuntime, setBuilderRuntime] = useState<{
    status: StreamStatus
    error: string | null
  }>({ status: 'idle', error: null })
  const [verifierRuntime, setVerifierRuntime] = useState<{
    status: StreamStatus
    error: string | null
  }>({ status: 'idle', error: null })
  const [verifierTrigger, setVerifierTrigger] = useState(0)
  const [verifierStartCommand, setVerifierStartCommand] =
    useState<WorkStartCommand>()
  const builderControllerRef = useRef<WorkChatController | null>(null)
  const builderMessagesRef = useRef<ChatMessage[]>([])
  const verifierMessagesRef = useRef<ChatMessage[]>([])
  const verifierRunKey = useRef<string | null>(null)
  const handledVerifierReportKey = useRef<string | null>(null)
  const verifierFeedbackInFlight = useRef(false)
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
        includeRoles:
          pane.agentSlug === AUTO_AGENT_SLUG
            ? WORK_CHAT_PERSONA_ROLES
            : undefined,
        promptMode: pane.agentSlug === AUTO_AGENT_SLUG ? 'chat' : undefined,
      }),
    [
      context,
      pane.designId,
      pane.feedbackId,
      pane.id,
      pane.projectId,
      pane.taskId,
      pane.agentSlug,
    ],
  )
  const verifierPane = useMemo(
    () => ({
      ...pane,
      agentSlug: VERIFIER_AGENT_SLUG,
      sessionId: pane.verifierSessionId,
      chatKey: pane.verifierChatKey,
    }),
    [pane],
  )
  const verifierContext = useMemo(
    () => ({
      ...context,
      role: 'verifier',
      parent_session_id: pane.sessionId ?? undefined,
      verifier_loop_count: pane.verifierLoopCount,
      verifier_max_loops: VERIFIER_MAX_LOOPS,
    }),
    [context, pane.sessionId, pane.verifierLoopCount],
  )
  const verifierApiConfig = useMemo(
    () =>
      buildWorkChatApiConfig({
        projectId: pane.projectId ?? GENERAL_PROJECT_ID,
        externalId:
          pane.taskId ??
          pane.feedbackId ??
          (pane.designId ? `design:${pane.designId}` : null),
        parentSessionId: pane.sessionId,
        sourceMetadata: {
          transport: 'web',
          surface: 'work_chats',
          pane_id: `${pane.id}:verifier`,
          source_client: SOURCE_CLIENT,
          lane_role: 'verifier',
        },
        workContext: verifierContext,
      }),
    [
      pane.designId,
      pane.feedbackId,
      pane.id,
      pane.projectId,
      pane.sessionId,
      pane.taskId,
      verifierContext,
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
  const handleVerifierSessionCreated = useCallback(
    (sessionId: string) => {
      onPatch({ verifierSessionId: sessionId })
      void upsertWorkChatBinding({
        session_id: sessionId,
        surface: 'work_chats',
        pane_id: `${pane.id}:verifier`,
        project_id: pane.projectId,
        task_id: pane.taskId,
        feedback_id: pane.feedbackId,
        design_id: pane.designId,
        source_client: SOURCE_CLIENT,
        work_context: verifierContext,
      })
    },
    [
      onPatch,
      pane.designId,
      pane.feedbackId,
      pane.id,
      pane.projectId,
      pane.taskId,
      verifierContext,
    ],
  )

  const triggerVerifier = useCallback(() => {
    if (!pane.verifierEnabled || !pane.sessionId) return
    setVerifierTrigger((current) => current + 1)
  }, [pane.sessionId, pane.verifierEnabled])

  const handleBuilderTurnFinished = useCallback(() => {
    if (!pane.verifierEnabled || !pane.sessionId) return
    if (!verifierFeedbackInFlight.current) {
      onPatch({
        verifierLoopCount: 0,
        verifierLastBuilderSessionId: pane.sessionId,
      })
    }
    verifierFeedbackInFlight.current = false
    triggerVerifier()
  }, [onPatch, pane.sessionId, pane.verifierEnabled, triggerVerifier])

  const handleVerifierTurnFinished = useCallback(() => {
    const content = latestAssistantContent(verifierMessagesRef.current)
    if (!content) return
    const reportKey = `${pane.verifierSessionId ?? 'new'}:${content.length}:${content.slice(-80)}`
    if (handledVerifierReportKey.current === reportKey) return
    handledVerifierReportKey.current = reportKey
    const report = parseVerifierReport(content)
    if (pane.sessionId && pane.verifierSessionId && report.status) {
      void submitVerifierOutcome({
        parent_session_id: pane.sessionId,
        verifier_session_id: pane.verifierSessionId,
        builder_session_id: pane.sessionId,
        project_id: pane.projectId ?? GENERAL_PROJECT_ID,
        task_id: pane.taskId,
        status: report.status,
        confidence: report.confidence,
        atomic_claim_count: report.atomicClaimCount,
        atomic_pass_count: report.atomicPassCount,
        atomic_fail_count: report.atomicFailCount,
        feedback_loop_count: pane.verifierLoopCount,
        report_excerpt: report.excerpt,
      }).catch(() => null)
    }
    if (!hasVerifierFeedback(report)) return
    if (pane.verifierLoopCount >= VERIFIER_MAX_LOOPS) return
    const feedback = report.feedback.trim()
    const controller = builderControllerRef.current
    if (!controller || controller.status !== 'idle') return
    verifierFeedbackInFlight.current = true
    onPatch({ verifierLoopCount: pane.verifierLoopCount + 1 })
    controller.sendMessage(feedback)
  }, [
    onPatch,
    pane.projectId,
    pane.sessionId,
    pane.taskId,
    pane.verifierLoopCount,
    pane.verifierSessionId,
  ])

  useEffect(() => {
    if (verifierTrigger <= 0) return
    if (!pane.verifierEnabled || !pane.sessionId) return
    if (
      verifierRuntime.status !== 'idle' &&
      verifierRuntime.status !== 'error'
    ) {
      return
    }
    const key = `${pane.sessionId}:${verifierTrigger}:${pane.verifierLoopCount}:${pane.verifierChatKey}`
    if (verifierRunKey.current === key) return
    verifierRunKey.current = key
    setVerifierStartCommand({
      key: Date.now(),
      prompt: verifierPromptForPane(
        pane,
        project,
        builderMessagesRef.current,
        childSessions,
      ),
    })
  }, [
    childSessions,
    pane,
    pane.sessionId,
    pane.verifierChatKey,
    pane.verifierEnabled,
    pane.verifierLoopCount,
    project,
    verifierRuntime.status,
    verifierTrigger,
  ])

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
        status={builderRuntime.status}
        error={builderRuntime.error}
        verifierStatus={verifierRuntime.status}
        verifierError={verifierRuntime.error}
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
        onOpenChildSession={onOpenChildSession}
        onOpenMockup={onOpenMockup}
        onSendPaneMessage={onSendPaneMessage}
      />
      <div className="min-h-0 flex-1">
        {pane.verifierEnabled ? (
          <BuilderVerifierSplit
            pane={pane}
            builderRuntime={builderRuntime}
            verifierRuntime={verifierRuntime}
            builderSessionId={pane.sessionId}
            verifierSessionId={pane.verifierSessionId}
            builderLabel={
              pane.agentSlug === AUTO_AGENT_SLUG
                ? agentName(agents, AUTO_AGENT_SLUG)
                : 'Builder'
            }
            onPatch={onPatch}
            builder={
              <WorkChatBody
                key={`${pane.id}:builder:${pane.chatKey}:${pane.agentSlug}`}
                pane={pane}
                apiConfig={apiConfig}
                workingDir={project?.root_path ?? undefined}
                startCommand={startCommand}
                onOpenMockup={onOpenMockup}
                onRuntimeChange={setBuilderRuntime}
                onMessagesChange={(messages) => {
                  builderMessagesRef.current = messages
                }}
                onTurnFinished={handleBuilderTurnFinished}
                onControllerReady={(controller) => {
                  builderControllerRef.current = controller
                }}
                onSessionCreated={handleSessionCreated}
              />
            }
            verifier={
              <WorkChatBody
                key={`${pane.id}:verifier:${pane.verifierChatKey}`}
                pane={verifierPane}
                apiConfig={verifierApiConfig}
                workingDir={project?.root_path ?? undefined}
                startCommand={verifierStartCommand}
                onOpenMockup={onOpenMockup}
                onRuntimeChange={setVerifierRuntime}
                onMessagesChange={(messages) => {
                  verifierMessagesRef.current = messages
                }}
                onTurnFinished={handleVerifierTurnFinished}
                onSessionCreated={handleVerifierSessionCreated}
              />
            }
          />
        ) : (
          <WorkChatBody
            key={`${pane.id}:builder:${pane.chatKey}:${pane.agentSlug}`}
            pane={pane}
            apiConfig={apiConfig}
            workingDir={project?.root_path ?? undefined}
            startCommand={startCommand}
            onOpenMockup={onOpenMockup}
            onRuntimeChange={setBuilderRuntime}
            onMessagesChange={(messages) => {
              builderMessagesRef.current = messages
            }}
            onTurnFinished={handleBuilderTurnFinished}
            onControllerReady={(controller) => {
              builderControllerRef.current = controller
            }}
            onSessionCreated={handleSessionCreated}
          />
        )}
      </div>
    </section>
  )
}

function paneFromSearchParams(
  searchParams: URLSearchParams,
  defaultAgent: string,
): WorkChatPane {
  const routingMode =
    searchParams.get('routing_mode') === 'direct' ? 'direct' : 'auto'
  const agentSlug =
    routingMode === 'direct'
      ? searchParams.get('agent_slug') || defaultAgent
      : AUTO_AGENT_SLUG
  return {
    ...makePane(agentSlug),
    routingMode,
    sessionId: searchParams.get('session_id'),
    projectId: searchParams.get('project_id'),
    taskId: searchParams.get('task_id'),
    taskTitle: searchParams.get('task_title'),
    taskSummary: searchParams.get('task_summary'),
    feedbackId: searchParams.get('feedback_id'),
    designId: searchParams.get('design_id'),
    artifactSummary: searchParams.get('artifact_summary'),
    verifierEnabled: searchParams.get('verifier') === '1',
    verifierSessionId: searchParams.get('verifier_session_id'),
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
  const [mockupEditorTarget, setMockupEditorTarget] =
    useState<MockupEditorTarget | null>(null)
  const [paneActionError, setPaneActionError] = useState<string | null>(null)
  const [appliedQueryString, setAppliedQueryString] = useState('')

  const defaultAgent = AUTO_AGENT_SLUG

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
        setAgents(
          items.length ? items : [{ slug: AUTO_AGENT_SLUG, name: 'Jenny' }],
        ),
      )
      .catch(() => setAgents([{ slug: AUTO_AGENT_SLUG, name: 'Jenny' }]))
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
    let cancelled = false
    const load = () => {
      fetchAgentHubSessions({
        project_id: activePane?.projectId ?? undefined,
        page_size: 100,
      })
        .then((items) => {
          if (!cancelled) setSessions(items)
        })
        .catch(() => {
          if (!cancelled) setSessions([])
        })
    }
    load()
    const timer = window.setInterval(load, 10000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [activePane?.projectId, panes.length])

  useEffect(() => {
    if (!activePane?.sessionId) {
      setChildSessions([])
      setActionRequests([])
      return
    }

    let cancelled = false
    const load = () => {
      fetchAgentHubSessions({
        parent_session_id: activePane.sessionId,
        page_size: 50,
      })
        .then((items) => {
          if (!cancelled) setChildSessions(items)
        })
        .catch(() => {
          if (!cancelled) setChildSessions([])
        })
      fetchActionRequests({ session_id: activePane.sessionId })
        .then((items) => {
          if (!cancelled) setActionRequests(items)
        })
        .catch(() => {
          if (!cancelled) setActionRequests([])
        })
    }
    load()
    const timer = window.setInterval(load, 5000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
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
    const next = {
      ...pane,
      id: makePane(pane.agentSlug).id,
      sessionId: null,
      verifierSessionId: null,
      verifierChatKey: pane.verifierChatKey + 1,
      verifierLoopCount: 0,
      verifierLastBuilderSessionId: null,
    }
    setPanes((current) => [...current, next])
    setActivePaneId(next.id)
  }

  const closePane = (pane: WorkChatPane) => {
    if (panes.length === 1) {
      patchPane(pane.id, {
        sessionId: null,
        chatKey: pane.chatKey + 1,
        verifierSessionId: null,
        verifierChatKey: pane.verifierChatKey + 1,
        verifierLoopCount: 0,
        verifierLastBuilderSessionId: null,
      })
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

  const queuePaneMessage = (paneId: string, prompt: string) => {
    setPaneActionError(null)
    setStartCommands((current) => ({
      ...current,
      [paneId]: {
        key: Date.now(),
        prompt,
      },
    }))
  }

  const pausePane = async (pane: WorkChatPane) => {
    if (!pane.sessionId && !pane.verifierSessionId) return
    setPaneActionError(null)
    try {
      if (pane.sessionId) await cancelAgentHubSessionStream(pane.sessionId)
      if (pane.verifierSessionId) {
        await cancelAgentHubSessionStream(pane.verifierSessionId)
      }
    } catch (error) {
      setPaneActionError(
        error instanceof Error ? error.message : 'Pause failed',
      )
    }
  }

  const stopPane = async (pane: WorkChatPane) => {
    if (!pane.sessionId && !pane.verifierSessionId) return
    setPaneActionError(null)
    try {
      if (pane.sessionId) {
        await cancelAgentHubSessionStream(pane.sessionId).catch(() => null)
        await closeAgentHubSession(pane.sessionId)
      }
      if (pane.verifierSessionId) {
        await cancelAgentHubSessionStream(pane.verifierSessionId).catch(
          () => null,
        )
        await closeAgentHubSession(pane.verifierSessionId)
      }
    } catch (error) {
      setPaneActionError(error instanceof Error ? error.message : 'Stop failed')
    }
  }

  const openChildSession = (
    sourcePane: WorkChatPane,
    session: AgentHubSessionListItem,
  ) => {
    const existing = panes.find((pane) => pane.sessionId === session.id)
    if (existing) {
      setActivePaneId(existing.id)
      return
    }
    if (panes.length >= MAX_PANES) {
      setPaneActionError('Max panes reached')
      return
    }
    const agentSlug = session.agent_slug ?? defaultAgent
    const next = {
      ...makePane(agentSlug),
      sessionId: session.id,
      projectId: session.project_id ?? sourcePane.projectId,
      taskId: sourcePane.taskId,
      taskTitle: sourcePane.taskTitle,
      taskSummary: sourcePane.taskSummary,
      feedbackId: sourcePane.feedbackId,
      designId: sourcePane.designId,
      artifactSummary: sourcePane.artifactSummary,
      routingMode: agentSlug === AUTO_AGENT_SLUG ? 'auto' : 'direct',
    } satisfies WorkChatPane
    setPanes((current) => [...current, next])
    setActivePaneId(next.id)
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
      <div className="flex h-10 shrink-0 items-center gap-2 overflow-x-auto border-b border-slate-800 bg-slate-900/90 px-2">
        <div className="flex min-w-0 items-center gap-2">
          <PanelsTopLeft className="h-3.5 w-3.5 shrink-0 text-phosphor-300" />
          <div className="hidden min-w-0 sm:block">
            <div className="truncate text-sm font-medium text-slate-100">
              Work Chats
            </div>
            <div className="truncate text-[10px] text-slate-600">
              {panes.length} pane{panes.length === 1 ? '' : 's'}
            </div>
          </div>
        </div>
        <SelectControl
          value={activePaneId}
          onChange={setActivePaneId}
          label="Active pane"
          className="w-44 md:hidden"
        >
          {panes.map((pane, index) => (
            <option key={pane.id} value={pane.id}>
              Pane {index + 1} - {paneAgentLabel(pane, agents)}
            </option>
          ))}
        </SelectControl>
        <div className="flex-1" />
        <SelectControl
          value={layout}
          onChange={(value) => setLayout(value as WorkChatLayout)}
          label="Layout"
          className="w-32"
        >
          <option value="main-side">Focus + side</option>
          <option value="horizontal">Rows</option>
          <option value="vertical">Columns</option>
          <option value="two-by-two">Grid</option>
          <option value="wide-grid">Wide grid</option>
        </SelectControl>
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
                  ...resetChatRuntimePatch(pane),
                })
              }
              onSplit={() => splitPane(pane)}
              onClose={() => closePane(pane)}
              onStart={() => queueStart(pane, project)}
              onPause={() => void pausePane(pane)}
              onStop={() => void stopPane(pane)}
              onOpenChildSession={(session) => openChildSession(pane, session)}
              onOpenMockup={setMockupEditorTarget}
              onSendPaneMessage={(prompt) => queuePaneMessage(pane.id, prompt)}
            />
          )
        })}
      </main>

      {mockupEditorTarget ? (
        <MockupEditorModal
          projectId={mockupEditorTarget.projectId}
          mockupId={mockupEditorTarget.mockupId}
          open
          onOpenChange={(open) => {
            if (!open) setMockupEditorTarget(null)
          }}
          onSaved={(saved) => {
            patchPane(mockupEditorTarget.paneId, {
              designId: saved.mockup_id,
              artifactSummary: saved.name,
              taskId: saved.task_id ?? null,
            })
            setMockupEditorTarget((current) =>
              current ? { ...current, mockupId: saved.mockup_id } : current,
            )
          }}
          onSendToJenny={({ sourceMockup, savedMockup, summary }) => {
            const targetMockup = savedMockup ?? sourceMockup
            queuePaneMessage(
              mockupEditorTarget.paneId,
              [
                'I updated or annotated this design mockup in the Work Chats editor.',
                `Project: ${targetMockup.project_id}`,
                `Mockup: ${targetMockup.mockup_id} v${targetMockup.version}`,
                `Name: ${targetMockup.name}`,
                targetMockup.page_path ? `Page: ${targetMockup.page_path}` : '',
                '',
                summary,
                '',
                'Read the stored mockup artifact from per-project Design if more detail is needed. Revise the mock, plan, task, or implementation path accordingly.',
              ]
                .filter(Boolean)
                .join('\n'),
            )
          }}
        />
      ) : null}
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
