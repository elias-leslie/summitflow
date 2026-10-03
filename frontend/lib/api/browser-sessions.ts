import { fetchWithErrorHandling, postJson } from './utils'

export interface BrowserSession {
  name: string
  actor: string
  state: string
  paused: boolean
  runtime_state: string | null
  last_used_ms: number | null
}

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
        !Number.isFinite(item.last_used_ms)))
  )
    throw new Error('Invalid browser session response')
  return {
    name: item.name,
    actor: item.actor,
    state: item.state,
    paused: item.paused,
    runtime_state: item.runtime_state,
    last_used_ms: item.last_used_ms,
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

export type BrowserStreamEvent =
  | { type: 'frame'; data: string; seq: number; width: number; height: number }
  | {
      type: 'bound'
      target: string
      document: string
      url: string
      title: string
    }
  | { type: 'url'; url: string }
  | { type: 'input_forwarded' }
  | { type: 'released' }

export function displayBrowserLocation(value: string): string {
  try {
    const url = new URL(value)
    if (!['http:', 'https:', 'about:'].includes(url.protocol)) return ''
    url.username = ''
    url.password = ''
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return ''
  }
}

export function parseBrowserStreamEvent(raw: string): BrowserStreamEvent {
  const value = record(JSON.parse(raw) as unknown)
  if (value.type === 'input_forwarded') return { type: 'input_forwarded' }
  if (value.type === 'released') return { type: 'released' }
  if (value.type === 'frame') {
    const metadata = record(value.metadata)
    if (
      typeof value.data !== 'string' ||
      value.data.length > 8 * 1024 * 1024 ||
      !/^[A-Za-z0-9+/=]+$/.test(value.data) ||
      typeof value.seq !== 'number' ||
      !Number.isSafeInteger(value.seq) ||
      value.seq < 0 ||
      typeof metadata.deviceWidth !== 'number' ||
      metadata.deviceWidth <= 0 ||
      metadata.deviceWidth > 16384 ||
      typeof metadata.deviceHeight !== 'number' ||
      metadata.deviceHeight <= 0 ||
      metadata.deviceHeight > 16384
    ) {
      throw new Error('Invalid browser frame')
    }
    return {
      type: 'frame',
      data: value.data,
      seq: value.seq,
      width: metadata.deviceWidth,
      height: metadata.deviceHeight,
    }
  }
  if (value.type === 'url' && typeof value.url === 'string')
    return { type: 'url', url: displayBrowserLocation(value.url) }
  if (value.type === 'bound') {
    const binding = record(value.binding)
    const page = record(value.page)
    if (
      typeof binding.target_id !== 'string' ||
      !binding.target_id ||
      typeof binding.document_id !== 'string' ||
      !binding.document_id ||
      typeof page.url !== 'string' ||
      typeof page.title !== 'string'
    )
      throw new Error('Invalid browser target binding')
    return {
      type: 'bound',
      target: binding.target_id,
      document: binding.document_id,
      url: displayBrowserLocation(page.url),
      title: page.title,
    }
  }
  throw new Error('Unsupported browser stream event')
}

export function browserStreamUrl(
  session: Pick<BrowserSession, 'name' | 'actor'>,
): string {
  const url = new URL(
    `/ws/browser-sessions/${encodeURIComponent(session.name)}`,
    window.location.href,
  )
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('actor', session.actor)
  return url.toString()
}
