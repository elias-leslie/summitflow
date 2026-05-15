import type { Project } from '@/lib/api'
import type { AgentHubSessionListItem } from '@/lib/api/agent-hub-work-chats'
import type { FeedbackItem } from '@/lib/api/feedback'
import type { Mockup } from '@/lib/api/mockups'
import {
  AUTO_AGENT_SLUG,
  DEFAULT_VERIFIER_SPLIT,
  MAX_PANES,
  STORAGE_KEY,
} from './constants'
import type { ArtifactOption, WorkChatLayout, WorkChatPane } from './types'

export function makePane(agentSlug = AUTO_AGENT_SLUG): WorkChatPane {
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

export function readSavedState(defaultAgent: string): {
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

export function layoutClass(layout: WorkChatLayout, count: number): string {
  if (count === 1) return 'grid-cols-1'
  if (layout === 'horizontal') return 'grid-cols-1'
  if (layout === 'vertical') return 'md:grid-cols-2'
  if (layout === 'two-by-two') return 'md:grid-cols-2'
  if (layout === 'wide-grid') return 'md:grid-cols-2 xl:grid-cols-3'
  return 'md:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]'
}

export function resetChatRuntimePatch(
  pane: WorkChatPane,
): Partial<WorkChatPane> {
  return {
    sessionId: null,
    chatKey: pane.chatKey + 1,
    verifierSessionId: null,
    verifierChatKey: pane.verifierChatKey + 1,
    verifierLoopCount: 0,
    verifierLastBuilderSessionId: null,
  }
}

export function sessionResumePatch(
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

export function buildArtifactOptions({
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

export function paneFromSearchParams(
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

export function agentName(
  agents: { slug: string; name?: string | null }[],
  slug: string | null | undefined,
) {
  if (!slug) return 'agent'
  return agents.find((agent) => agent.slug === slug)?.name ?? slug
}

export function autoAgentLabel(
  agents: { slug: string; name?: string | null }[],
) {
  return `Auto: ${agentName(agents, AUTO_AGENT_SLUG)}`
}

export function paneAgentLabel(
  pane: WorkChatPane,
  agents: { slug: string; name?: string | null }[],
) {
  if (pane.routingMode === 'auto') return autoAgentLabel(agents)
  return agentName(agents, pane.agentSlug)
}

export function paneContextLabel(pane: WorkChatPane, projects: Project[]) {
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

export function sessionSummary(session: AgentHubSessionListItem) {
  return (
    session.summary_oneliner ??
    session.live_activity?.summary ??
    session.summary_outcome ??
    session.workstream_status ??
    ''
  )
}
