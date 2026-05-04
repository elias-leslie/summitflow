import { buildAgentHubChatApiConfig } from '@/lib/agent-hub-chat-config'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import { buildQueryString, fetchWithErrorHandling, postJson } from './utils'

export interface AgentHubAgent {
  slug: string
  name: string
  description?: string | null
  primary_model_id?: string | null
  is_active?: boolean
  is_coding_agent?: boolean
}

export interface AgentHubSessionListItem {
  id: string
  project_id: string
  status: string
  agent_slug: string | null
  session_type?: string | null
  parent_session_id?: string | null
  external_id?: string | null
  summary_oneliner?: string | null
  workstream_status?: string | null
  current_branch?: string | null
  observed_write_paths?: string[] | null
  child_session_count?: number | null
  active_child_session_count?: number | null
  live_activity?: {
    summary?: string | null
    phase?: string | null
    status?: string | null
    health?: string | null
    files_touched?: string[]
    last_validation_command?: string | null
    last_command_exit_code?: number | null
  } | null
  created_at?: string | null
  updated_at?: string | null
}

export interface WorkContext extends Record<string, unknown> {
  mode?: string
  project_id?: string
  project_name?: string
  task_id?: string
  task_title?: string
  task_summary?: string
  feedback_id?: string
  design_id?: string
  artifact_summary?: string
  surface?: string
  pane_id?: string
}

export interface WorkChatBinding {
  id: string
  session_id: string
  surface: string
  pane_id: string | null
  project_id: string | null
  task_id: string | null
  feedback_id: string | null
  design_id: string | null
  telegram_chat_id: string | null
  telegram_thread_id: string | null
  telegram_message_id: string | null
  source_client: string | null
  work_context: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ActionRequest {
  id: string
  session_id: string
  status: string
  request_type: string
  prompt: string | null
  response_content: string | null
  telegram_chat_id: string | null
  telegram_thread_id: string | null
  telegram_message_id: string | null
  correlation_id: string | null
  join_code: string | null
  source_client: string | null
  metadata: Record<string, unknown>
  created_at: string
  resolved_at: string | null
  expires_at: string | null
}

function agentHubUrl(path: string): string {
  return `${getAgentHubProxyBase()}${path}`
}

export function buildWorkChatApiConfig(options: {
  projectId?: string | null
  externalId?: string | null
  sourceMetadata?: Record<string, string | undefined>
  workContext?: WorkContext
}) {
  return {
    ...buildAgentHubChatApiConfig({
      proxyBase: getAgentHubProxyBase(),
      projectId: options.projectId ?? 'summitflow',
    }),
    externalId: options.externalId ?? undefined,
    sourceMetadata: options.sourceMetadata,
    workContext: options.workContext,
  }
}

export async function fetchAgentHubAgents(): Promise<AgentHubAgent[]> {
  const response = await fetchWithErrorHandling<{ agents: AgentHubAgent[] }>(
    agentHubUrl('/agents?active_only=true&limit=100'),
    { errorMessage: 'Failed to fetch agents' },
  )
  return response.agents ?? []
}

export async function fetchAgentHubSessions(params: {
  project_id?: string | null
  status?: string | null
  agent_slug?: string | null
  parent_session_id?: string | null
  external_id?: string | null
  page_size?: number
}): Promise<AgentHubSessionListItem[]> {
  const query = buildQueryString({
    project_id: params.project_id,
    status: params.status,
    agent_slug: params.agent_slug,
    parent_session_id: params.parent_session_id,
    external_id: params.external_id,
    page_size: params.page_size ?? 50,
  })
  const response = await fetchWithErrorHandling<{
    sessions: AgentHubSessionListItem[]
  }>(agentHubUrl(`/sessions${query}`), {
    errorMessage: 'Failed to fetch sessions',
  })
  return response.sessions ?? []
}

export async function upsertWorkChatBinding(
  binding: Partial<WorkChatBinding> & { session_id: string },
): Promise<WorkChatBinding> {
  return postJson<WorkChatBinding>(
    agentHubUrl('/work-chats/bindings'),
    binding,
    'Failed to bind work chat session',
  )
}

export async function fetchActionRequests(params?: {
  session_id?: string | null
  status?: string | null
}): Promise<ActionRequest[]> {
  const query = buildQueryString({
    session_id: params?.session_id,
    status: params?.status,
  })
  const response = await fetchWithErrorHandling<{
    action_requests: ActionRequest[]
  }>(agentHubUrl(`/work-chats/action-requests${query}`), {
    errorMessage: 'Failed to fetch action requests',
  })
  return response.action_requests ?? []
}

export async function cancelAgentHubSessionStream(
  sessionId: string,
): Promise<void> {
  await postJson(
    agentHubUrl('/complete/cancel'),
    { session_id: sessionId },
    'Failed to pause session stream',
  )
}

export async function closeAgentHubSession(sessionId: string): Promise<void> {
  await postJson(
    agentHubUrl(`/sessions/${sessionId}/close`),
    {},
    'Failed to close session',
  )
}
