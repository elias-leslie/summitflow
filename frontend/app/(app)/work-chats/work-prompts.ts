import type { AdhocWorkSpec, ChatMessage } from '@agent-hub/chat-ui'
import type { Project } from '@/lib/api'
import type {
  AgentHubSessionListItem,
  WorkContext,
} from '@/lib/api/agent-hub-work-chats'
import { VERIFIER_MAX_LOOPS } from './constants'
import type { WorkChatPane } from './types'

export function adhocWorkSpecForPane(
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

export function workContextForPane(
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

export function startPromptForPane(
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

export function verifierPromptForPane(
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
