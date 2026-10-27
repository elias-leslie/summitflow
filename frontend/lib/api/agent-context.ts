/**
 * Agent context API - read-only view of what Agent Hub delivers to a coding
 * agent at session start in one project (via the SummitFlow Agent Hub proxy).
 * Agent Hub owns and edits this context; SummitFlow only displays it.
 */

import { getAgentHubProxyBase } from '../agent-hub-proxy'
import { fetchWithErrorHandling } from './utils'

export type AgentContextKind =
  | 'prompt'
  | 'memory'
  | 'project_index'
  | 'continuity'
  | 'tool_capabilities'
  | 'computed'

export type AgentContextGroup = 'project' | 'global'

export interface AgentContextItem {
  order: number
  kind: AgentContextKind
  group: AgentContextGroup
  source_id: string
  title: string
  authority: string
  tier: string
  required: boolean
  disclosure: string
  reason: string
  char_count: number
  estimated_tokens: number
  edit_path: string | null
  facts: string[]
}

export interface AgentContextTotals {
  items: number
  project_items: number
  global_items: number
  project_tokens: number
  global_tokens: number
  item_tokens: number
  delivered_tokens: number
  delivered_chars: number
}

export interface ProjectAgentContext {
  project_id: string
  consumer_profile: string
  consumer_surface: string
  status: 'ok' | 'failed'
  generated_at: string
  items: AgentContextItem[]
  withheld: { count: number; estimated_tokens: number }
  totals: AgentContextTotals
  manage_path: string
  failure: { error_type: string; message: string } | null
}

const INVALID = 'Invalid agent context response'

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isItem(value: unknown): value is AgentContextItem {
  return (
    isRecord(value) &&
    typeof value.source_id === 'string' &&
    typeof value.title === 'string' &&
    (value.group === 'project' || value.group === 'global') &&
    typeof value.kind === 'string' &&
    typeof value.estimated_tokens === 'number' &&
    typeof value.char_count === 'number' &&
    (value.edit_path === null || typeof value.edit_path === 'string') &&
    Array.isArray(value.facts)
  )
}

export async function fetchProjectAgentContext(
  projectId: string,
): Promise<ProjectAgentContext> {
  const data = await fetchWithErrorHandling<unknown>(
    `${getAgentHubProxyBase()}/projects/${encodeURIComponent(projectId)}/agent-context`,
    { errorMessage: 'Could not load agent context from Agent Hub' },
  )
  if (
    !isRecord(data) ||
    data.project_id !== projectId ||
    (data.status !== 'ok' && data.status !== 'failed') ||
    !Array.isArray(data.items) ||
    !data.items.every(isItem) ||
    !isRecord(data.totals) ||
    !isRecord(data.withheld)
  ) {
    throw new Error(INVALID)
  }
  return data as unknown as ProjectAgentContext
}

/** Join an Agent Hub UI base URL with an app-relative path such as /prompts/x. */
export function buildAgentHubUiUrl(
  baseUrl: string | null,
  path: string | null,
): string | null {
  if (!baseUrl || !path?.startsWith('/')) return null
  return `${baseUrl.replace(/\/+$/, '')}${path}`
}
