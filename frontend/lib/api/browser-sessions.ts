import { fetchWithErrorHandling, postJson } from './utils'

export interface BrowserSession {
  name: string
  actor: string
  state: string
  paused: boolean
  runtime_state: string | null
  last_used_ms: number | null
  location: BrowserRuntimeLocation
  /** Why the agent paused for the owner, e.g. "login needed: github.com". */
  pause_reason: string | null
}

/** Where the session's browser runs; null while no browser is running. */
export type BrowserRuntimeLocation = 'proxmox' | 'local' | null

export type BrowserSessionAction = 'pause' | 'resume' | 'close'

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Invalid browser session response')
  }
  return value as Record<string, unknown>
}

export function parseBrowserSession(value: unknown): BrowserSession {
  const item = record(value)
  if (
    typeof item.name !== 'string' ||
    !item.name ||
    typeof item.actor !== 'string' ||
    !item.actor ||
    typeof item.state !== 'string' ||
    !item.state ||
    typeof item.paused !== 'boolean' ||
    (item.runtime_state !== null && typeof item.runtime_state !== 'string') ||
    (item.last_used_ms !== null &&
      (typeof item.last_used_ms !== 'number' ||
        !Number.isFinite(item.last_used_ms))) ||
    (item.location !== undefined &&
      item.location !== null &&
      item.location !== 'proxmox' &&
      item.location !== 'local') ||
    (item.pause_reason !== undefined &&
      item.pause_reason !== null &&
      typeof item.pause_reason !== 'string')
  )
    throw new Error('Invalid browser session response')
  return {
    name: item.name,
    actor: item.actor,
    state: item.state,
    paused: item.paused,
    runtime_state: item.runtime_state,
    last_used_ms: item.last_used_ms,
    location: item.location ?? null,
    pause_reason: item.pause_reason || null,
  }
}

export const browserSessionsApi = {
  async list(): Promise<BrowserSession[]> {
    const value = record(
      await fetchWithErrorHandling<unknown>('/api/browser-sessions', {
        cache: 'no-store',
      }),
    )
    if (value.schema_version !== 1 || !Array.isArray(value.sessions))
      throw new Error('Browser session inventory is incompatible')
    return value.sessions.map(parseBrowserSession)
  },
  async change(
    session: Pick<BrowserSession, 'name' | 'actor'>,
    action: BrowserSessionAction,
  ): Promise<BrowserSession> {
    const value = record(
      await postJson<unknown>(
        `/api/browser-sessions/${encodeURIComponent(session.name)}/${action}`,
        { actor: session.actor },
        'Browser session operation failed',
      ),
    )
    if (value.schema_version !== 1)
      throw new Error('Browser session response is incompatible')
    const changed = parseBrowserSession(value.session)
    if (changed.name !== session.name || changed.actor !== session.actor)
      throw new Error('Selected session owner changed')
    return changed
  },
}
