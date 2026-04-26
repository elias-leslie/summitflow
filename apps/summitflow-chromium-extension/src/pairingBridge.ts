import type {
  ExtensionBridgeRequest,
  ExtensionBridgeResponse,
  ExtensionCommandResponse,
} from './protocol'

window.addEventListener('message', (event) => {
  if (!isAllowedSummitFlowOrigin(window.location.origin)) return
  if (event.source !== window || !isBridgeRequest(event.data)) return

  const request = event.data
  chrome.runtime.sendMessage(request.message, (response?: ExtensionCommandResponse) => {
    const error = chrome.runtime.lastError?.message
    const payload: ExtensionBridgeResponse = {
      source: 'summitflow.extension',
      requestId: request.requestId,
      ok: !error && response?.ok === true,
      error: error ?? response?.error,
    }
    window.postMessage(payload, window.location.origin)
  })
})

function isBridgeRequest(value: unknown): value is ExtensionBridgeRequest {
  if (!isRecord(value)) return false
  if (value.source !== 'summitflow.design') return false
  if (typeof value.requestId !== 'string' || !value.requestId) return false
  const message = value.message
  return (
    isRecord(message) &&
    (message.type === 'summitflow.claim_pairing' ||
      message.type === 'summitflow.revoke_session' ||
      message.type === 'summitflow.inject_overlay')
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isAllowedSummitFlowOrigin(origin: string): boolean {
  return (
    origin === 'http://127.0.0.1:3001' ||
    origin === 'http://localhost:3001' ||
    origin === 'http://192.168.8.244:3001' ||
    origin === 'https://terminal.summitflow.dev'
  )
}
