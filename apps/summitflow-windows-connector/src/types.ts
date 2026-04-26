export interface ConnectorSessionConfig {
  apiBaseUrl: string
  sessionId: string
  pairingId: string
  connectorToken: string
  sensitiveMode: boolean
}

export interface CollabSessionResponse {
  session_id: string
  target_url: string | null
  sensitive: boolean
}

export interface ClaimPairingResponse {
  connector_token: string
  pairing: {
    pairing_id: string
    session_id: string
    state: string
  }
  session: CollabSessionResponse
}

export interface ConnectorOptions {
  apiBaseUrl: string
  pairingId: string
  pairingToken: string
  browserPath?: string
  extensionDir: string
  profileDir: string
  profileLabel: string
  targetUrl?: string
  yes: boolean
  dryRun: boolean
  port: number
}

export interface EgressSummary {
  apiOrigin: string
  targetOrigin: string | null
  localOrigin: string
  allowedOrigins: string[]
}
