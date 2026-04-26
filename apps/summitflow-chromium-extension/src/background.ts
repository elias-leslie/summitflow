import type {
  AnnotationDraft,
  CollabAnnotation,
  CompactPageState,
  ConnectorSessionConfig,
  ContentToBackgroundMessage,
  ExtensionCommandMessage,
  ExtensionCommandResponse,
  PairingClaimConfig,
} from './protocol'

const SESSION_STORAGE_KEY = 'summitflow.connectorSession'
const HEARTBEAT_MIN_INTERVAL_MS = 500
const LOCAL_CONNECTOR_PORTS = Array.from({ length: 11 }, (_, index) => 47618 + index)

let lastHeartbeatAt = 0
let queuedState: CompactPageState | null = null
let heartbeatTimer: ReturnType<typeof setTimeout> | null = null
let annotations: CollabAnnotation[] = []

chrome.action.onClicked.addListener((tab) => {
  const tabId = tab.id
  if (typeof tabId !== 'number') return
  void injectOverlay(tabId).then(() => sendSessionConfig(tabId))
})

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  void handleRuntimeMessage(message, sender)
    .then((response) => sendResponse(response))
    .catch((error: unknown) => {
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : 'unknown error',
      } satisfies ExtensionCommandResponse)
    })
  return true
})

async function handleRuntimeMessage(
  message: unknown,
  sender: chrome.MessageSender,
): Promise<ExtensionCommandResponse> {
  if (isExtensionCommand(message)) {
    return handleExtensionCommand(message, sender)
  }
  if (isContentMessage(message)) {
    return handleContentMessage(message, sender)
  }
  return { ok: false, error: 'unsupported message' }
}

async function handleExtensionCommand(
  message: ExtensionCommandMessage,
  sender: chrome.MessageSender,
): Promise<ExtensionCommandResponse> {
  if (message.type === 'summitflow.claim_pairing') {
    const session = await claimPairing(message.config)
    await setSession(session)
    annotations = []
    await openTargetUrl(message.config.targetUrl)
    return { ok: true }
  }
  if (message.type === 'summitflow.configure_session') {
    await setSession(message.config)
    annotations = []
    const tabId = sender.tab?.id
    if (typeof tabId === 'number') {
      await injectOverlay(tabId)
      await sendSessionConfig(tabId)
    }
    return { ok: true }
  }
  if (message.type === 'summitflow.revoke_session') {
    const session = await getSession()
    await clearSession()
    if (session) {
      await revokeConnector(session)
    }
    return { ok: true }
  }
  if (message.type === 'summitflow.inject_overlay') {
    const tabId = sender.tab?.id
    if (typeof tabId !== 'number') return { ok: false, error: 'active tab required' }
    await injectOverlay(tabId)
    await sendSessionConfig(tabId)
    return { ok: true }
  }
  return { ok: false, error: 'unsupported command' }
}

async function handleContentMessage(
  message: ContentToBackgroundMessage,
  sender: chrome.MessageSender,
): Promise<ExtensionCommandResponse> {
  if (message.type === 'summitflow.page_state') {
    queueHeartbeat(message.state)
    return { ok: true }
  }
  if (message.type === 'summitflow.annotation_draft') {
    const session = await getSession()
    if (!session) {
      return {
        ok: false,
        error:
          'Co-Browser is not paired. Return to SummitFlow Design Review and click Pair.',
      }
    }
    const created = await createAnnotation(session, message.draft)
    annotations = [created, ...annotations].slice(0, 100)
    if (sender.tab?.id) {
      await sendToTab(sender.tab.id, {
        type: 'summitflow.render_annotations',
        annotations,
      })
    }
    return { ok: true }
  }
  if (message.type === 'summitflow.pointer') {
    return { ok: true }
  }
  return { ok: false, error: 'unsupported content message' }
}

function queueHeartbeat(state: CompactPageState): void {
  queuedState = { ...queuedState, ...state }
  if (heartbeatTimer) return
  const wait = Math.max(0, HEARTBEAT_MIN_INTERVAL_MS - (Date.now() - lastHeartbeatAt))
  heartbeatTimer = setTimeout(() => {
    heartbeatTimer = null
    void flushHeartbeat()
  }, wait)
}

async function flushHeartbeat(): Promise<void> {
  const state = queuedState
  queuedState = null
  if (!state) return
  const session = await getSession()
  if (!session) return
  lastHeartbeatAt = Date.now()
  await heartbeat(session, state)
  if (queuedState) {
    queueHeartbeat({})
  }
}

async function heartbeat(session: ConnectorSessionConfig, state: CompactPageState): Promise<void> {
  await fetch(apiUrl(session.apiBaseUrl, `/collab/connector-pairings/${session.pairingId}/heartbeat`), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      connector_token: session.connectorToken,
      url: state.url,
      title: state.title,
      scroll_x: state.scroll_x,
      scroll_y: state.scroll_y,
      viewport_width: state.viewport_width,
      viewport_height: state.viewport_height,
      dom_state_hash: session.sensitiveMode ? undefined : state.dom_state_hash,
    }),
  })
}

async function claimPairing(config: PairingClaimConfig): Promise<ConnectorSessionConfig> {
  const response = await fetch(apiUrl(config.apiBaseUrl, `/collab/connector-pairings/${config.pairingId}/claim`), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      pairing_token: config.pairingToken,
      connector_host: 'dedicated-browser-extension',
      profile_label: config.profileLabel ?? 'SummitFlow Review',
      connector_version: chrome.runtime.getManifest().version,
    }),
  })
  if (!response.ok) {
    throw new Error(`pairing claim failed: ${response.status}`)
  }
  const body = (await response.json()) as { connector_token?: unknown }
  if (typeof body.connector_token !== 'string') {
    throw new Error('pairing claim missing connector token')
  }
  return {
    apiBaseUrl: config.apiBaseUrl,
    sessionId: config.sessionId,
    pairingId: config.pairingId,
    connectorToken: body.connector_token,
    sensitiveMode: config.sensitiveMode,
  }
}

async function openTargetUrl(targetUrl?: string | null): Promise<void> {
  const url = normalizeTargetUrl(targetUrl)
  if (!url) return
  await chrome.tabs.create({ url })
}

function normalizeTargetUrl(targetUrl?: string | null): string | null {
  if (!targetUrl) return null
  try {
    const parsed = new URL(targetUrl)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
    return parsed.toString()
  } catch {
    return null
  }
}

async function createAnnotation(
  session: ConnectorSessionConfig,
  draft: AnnotationDraft,
): Promise<CollabAnnotation> {
  const response = await fetch(apiUrl(session.apiBaseUrl, `/collab/sessions/${session.sessionId}/annotations`), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      kind: draft.kind,
      page_url_snapshot: draft.pageUrlSnapshot,
      selector: draft.selector,
      anchor: draft.anchor,
      comment: draft.comment,
    }),
  })
  if (!response.ok) {
    throw new Error(`annotation failed: ${response.status}`)
  }
  return (await response.json()) as CollabAnnotation
}

async function revokeConnector(session: ConnectorSessionConfig): Promise<void> {
  await fetch(apiUrl(session.apiBaseUrl, `/collab/connector-pairings/${session.pairingId}/revoke`), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
  })
}

async function sendSessionConfig(tabId: number): Promise<void> {
  const session = await getSession()
  if (!session) return
  await sendToTab(tabId, {
    type: 'summitflow.configure',
    config: {
      apiBaseUrl: session.apiBaseUrl,
      sessionId: session.sessionId,
      pairingId: session.pairingId,
      sensitiveMode: session.sensitiveMode,
    },
  })
}

async function injectOverlay(tabId: number): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    chrome.scripting.executeScript(
      {
        target: { tabId },
        files: ['dist/content.js'],
      },
      () => {
        const error = chrome.runtime.lastError?.message
        if (error) reject(new Error(error))
        else resolve()
      },
    )
  })
}

async function sendToTab(tabId: number, message: unknown): Promise<void> {
  await new Promise<void>((resolve) => {
    chrome.tabs.sendMessage(tabId, message, () => resolve())
  })
}

async function getSession(): Promise<ConnectorSessionConfig | null> {
  const result = await chrome.storage.session.get(SESSION_STORAGE_KEY)
  const value = result[SESSION_STORAGE_KEY]
  if (isSessionConfig(value)) return value
  return discoverLocalConnectorSession()
}

async function setSession(config: ConnectorSessionConfig): Promise<void> {
  await chrome.storage.session.set({ [SESSION_STORAGE_KEY]: config })
}

async function clearSession(): Promise<void> {
  await chrome.storage.session.remove(SESSION_STORAGE_KEY)
}

async function discoverLocalConnectorSession(): Promise<ConnectorSessionConfig | null> {
  for (const port of LOCAL_CONNECTOR_PORTS) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/extension-session`, {
        cache: 'no-store',
        headers: { accept: 'application/json' },
      })
      if (!response.ok) continue
      const value = await response.json()
      if (!isSessionConfig(value)) continue
      await setSession(value)
      return value
    } catch {
      continue
    }
  }
  return null
}

function apiUrl(apiBaseUrl: string, path: string): string {
  const base = apiBaseUrl.replace(/\/+$/, '')
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

function isExtensionCommand(message: unknown): message is ExtensionCommandMessage {
  if (!isRecord(message) || typeof message.type !== 'string') return false
  return (
    message.type === 'summitflow.claim_pairing' ||
    message.type === 'summitflow.configure_session' ||
    message.type === 'summitflow.revoke_session' ||
    message.type === 'summitflow.inject_overlay'
  )
}

function isContentMessage(message: unknown): message is ContentToBackgroundMessage {
  if (!isRecord(message) || typeof message.type !== 'string') return false
  return (
    message.type === 'summitflow.page_state' ||
    message.type === 'summitflow.annotation_draft' ||
    message.type === 'summitflow.pointer'
  )
}

function isSessionConfig(value: unknown): value is ConnectorSessionConfig {
  return (
    isRecord(value) &&
    typeof value.apiBaseUrl === 'string' &&
    typeof value.sessionId === 'string' &&
    typeof value.pairingId === 'string' &&
    typeof value.connectorToken === 'string' &&
    typeof value.sensitiveMode === 'boolean'
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
