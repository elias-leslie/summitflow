import { buildApiUrl } from '../api-config'
import { buildQueryString, fetchWithErrorHandling, postJson } from './utils'

export type ManagedCaptureAction =
  | 'disable'
  | 'enable'
  | 'drain'
  | 'check-update'
  | 'stage-update'
  | 'qualify-update'
  | 'promote-update'
  | 'rollback-update'

export interface ManagedCodexUpdate {
  state:
    | 'unavailable'
    | 'unchecked'
    | 'available'
    | 'staged'
    | 'qualified'
    | 'active'
    | 'rolled_back'
    | 'failed'
  latest_version: string | null
  candidate_version: string | null
  active_version: string | null
  previous_version: string | null
  error_code: string | null
}

const managedActions: ManagedCaptureAction[] = [
  'disable',
  'enable',
  'drain',
  'check-update',
  'stage-update',
  'qualify-update',
  'promote-update',
  'rollback-update',
]
const updateStates: ManagedCodexUpdate['state'][] = [
  'unavailable',
  'unchecked',
  'available',
  'staged',
  'qualified',
  'active',
  'rolled_back',
  'failed',
]

export interface ManagedCodexThread {
  thread_id: string
  project_id: string
  source_id: string | null
  acknowledged: number
  provider_version: string | null
  schema_fingerprint: string | null
  generation: number
}

export interface ManagedCodexStatus {
  available: boolean
  project_id: string | null
  configured_projects: string[]
  installed_version: string | null
  installed_protocol_status: 'compatible' | 'unsupported' | 'unavailable'
  capture_enabled: boolean
  capture_disabled: boolean
  health: string
  delivery_health: string
  capture_gaps: number
  pending: number
  pending_bytes: number
  quarantined: number
  quarantined_bytes: number
  used_bytes: number
  quota_bytes: number
  raw_retention_seconds: number
  physical_bytes: number
  process_active: boolean
  threads: ManagedCodexThread[]
  actions: ManagedCaptureAction[]
  promotion_state: string
  agent_hub_url: string
  update?: ManagedCodexUpdate
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

const countKeys = [
  'capture_gaps',
  'pending',
  'pending_bytes',
  'quarantined',
  'quarantined_bytes',
  'used_bytes',
  'quota_bytes',
  'raw_retention_seconds',
  'physical_bytes',
] as const

export function parseManagedCodexStatus(value: unknown): ManagedCodexStatus {
  if (
    !record(value) ||
    ![
      'available',
      'capture_enabled',
      'capture_disabled',
      'process_active',
    ].every((key) => typeof value[key] === 'boolean') ||
    !nullableString(value.project_id) ||
    (value.configured_projects !== undefined &&
      (!Array.isArray(value.configured_projects) ||
        !value.configured_projects.every(
          (project) => typeof project === 'string' && project.length > 0,
        ))) ||
    !nullableString(value.installed_version) ||
    !['compatible', 'unsupported', 'unavailable'].includes(
      String(value.installed_protocol_status),
    ) ||
    !['health', 'delivery_health', 'promotion_state', 'agent_hub_url'].every(
      (key) => typeof value[key] === 'string',
    ) ||
    !countKeys.every((key) => count(value[key])) ||
    !Array.isArray(value.actions) ||
    !value.actions.every((action) => managedActions.includes(action)) ||
    !Array.isArray(value.threads)
  ) {
    throw new Error('Managed Codex status is incompatible')
  }
  let update: ManagedCodexUpdate | undefined
  if (value.update !== undefined) {
    if (
      !record(value.update) ||
      !updateStates.includes(
        value.update.state as ManagedCodexUpdate['state'],
      ) ||
      ![
        'latest_version',
        'candidate_version',
        'active_version',
        'previous_version',
        'error_code',
      ].every((key) =>
        nullableString((value.update as Record<string, unknown>)[key]),
      )
    )
      throw new Error('Managed Codex update status is incompatible')
    update = {
      state: value.update.state as ManagedCodexUpdate['state'],
      latest_version: value.update.latest_version as string | null,
      candidate_version: value.update.candidate_version as string | null,
      active_version: value.update.active_version as string | null,
      previous_version: value.update.previous_version as string | null,
      error_code: value.update.error_code as string | null,
    }
  }
  if (value.actions.some((kind) => String(kind).endsWith('-update')) && !update)
    throw new Error('Managed Codex update status is unavailable')
  const threads = value.threads.map((thread): ManagedCodexThread => {
    if (
      !record(thread) ||
      typeof thread.thread_id !== 'string' ||
      typeof thread.project_id !== 'string' ||
      !nullableString(thread.source_id) ||
      !nullableString(thread.provider_version) ||
      !nullableString(thread.schema_fingerprint) ||
      !count(thread.acknowledged) ||
      !count(thread.generation)
    )
      throw new Error('Managed Codex thread is incompatible')
    return {
      thread_id: thread.thread_id,
      project_id: thread.project_id,
      source_id: thread.source_id,
      provider_version: thread.provider_version,
      schema_fingerprint: thread.schema_fingerprint,
      acknowledged: thread.acknowledged,
      generation: thread.generation,
    }
  })
  const status: ManagedCodexStatus = {
    available: value.available as boolean,
    project_id: value.project_id,
    configured_projects: Array.isArray(value.configured_projects)
      ? [...new Set(value.configured_projects as string[])]
      : [],
    installed_version: value.installed_version,
    installed_protocol_status:
      value.installed_protocol_status as ManagedCodexStatus['installed_protocol_status'],
    capture_enabled: value.capture_enabled as boolean,
    capture_disabled: value.capture_disabled as boolean,
    health: value.health as string,
    delivery_health: value.delivery_health as string,
    capture_gaps: value.capture_gaps as number,
    pending: value.pending as number,
    pending_bytes: value.pending_bytes as number,
    quarantined: value.quarantined as number,
    quarantined_bytes: value.quarantined_bytes as number,
    used_bytes: value.used_bytes as number,
    quota_bytes: value.quota_bytes as number,
    raw_retention_seconds: value.raw_retention_seconds as number,
    physical_bytes: value.physical_bytes as number,
    process_active: value.process_active as boolean,
    threads,
    actions: value.actions as ManagedCaptureAction[],
    promotion_state: value.promotion_state as string,
    agent_hub_url: value.agent_hub_url as string,
    ...(update ? { update } : {}),
  }
  return status
}

export async function fetchManagedCodexStatus(
  projectId?: string,
): Promise<ManagedCodexStatus> {
  const status = parseManagedCodexStatus(
    await fetchWithErrorHandling<unknown>(
      managedApiUrl(
        `/api/projects/managed-codex${buildQueryString({ project_id: projectId })}`,
      ),
      { cache: 'no-store', errorMessage: 'Managed Codex status unavailable' },
    ),
  )
  if (projectId && status.project_id !== projectId)
    throw new Error('Managed Codex project binding mismatch')
  return status
}

export async function controlManagedCodex(
  projectId: string,
  action: ManagedCaptureAction,
): Promise<ManagedCodexStatus> {
  const status = parseManagedCodexStatus(
    await postJson<unknown>(
      managedApiUrl(
        `/api/projects/${encodeURIComponent(projectId)}/managed-codex/${action}`,
      ),
      {},
      'Managed capture action failed',
    ),
  )
  if (status.project_id !== projectId)
    throw new Error('Managed Codex project binding mismatch')
  return status
}

// Owner controls enforce same-origin requests, including local development.
// Next's established /api rewrite preserves the authenticated browser origin.
function managedApiUrl(path: string): string {
  return typeof window === 'undefined' ? buildApiUrl(path) : path
}

export function managedEvidenceUrl(
  baseUrl: string,
  sessionId: string,
): string | null {
  try {
    const url = new URL(baseUrl)
    if (
      !['https:', 'http:'].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null
    url.pathname = `/sessions/${encodeURIComponent(sessionId)}`
    url.search = '?tab=info'
    url.hash = ''
    return url.toString()
  } catch {
    return null
  }
}
