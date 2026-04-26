import os from 'node:os'
import type { ClaimPairingResponse, ConnectorSessionConfig } from './types'
import { CONNECTOR_VERSION } from './core'

export async function claimPairing(options: {
  apiBaseUrl: string
  pairingId: string
  pairingToken: string
  profileLabel: string
}): Promise<ClaimPairingResponse> {
  const response = await fetch(apiUrl(options.apiBaseUrl, `/collab/connector-pairings/${options.pairingId}/claim`), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      pairing_token: options.pairingToken,
      connector_host: os.hostname(),
      profile_label: options.profileLabel,
      connector_version: CONNECTOR_VERSION,
    }),
  })
  if (!response.ok) {
    throw new Error(`Pairing claim failed: ${response.status}`)
  }
  return (await response.json()) as ClaimPairingResponse
}

export async function revokePairing(session: ConnectorSessionConfig): Promise<void> {
  await fetch(apiUrl(session.apiBaseUrl, `/collab/connector-pairings/${session.pairingId}/revoke`), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
  })
}

export function apiUrl(apiBaseUrl: string, path: string): string {
  const base = apiBaseUrl.replace(/\/+$/, '')
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}
