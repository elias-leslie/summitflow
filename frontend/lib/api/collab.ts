import { buildQueryString, fetchWithErrorHandling, postJson } from './utils'

export type CollabTargetMode =
  | 'live_browser'
  | 'windows_co_browser'
  | 'st_browser'
  | 'manual'

export type CollabSessionState = 'active' | 'closed'
export type CollabConnectorPairingState =
  | 'pending'
  | 'claimed'
  | 'revoked'
  | 'expired'
export type CollabAnnotationKind =
  | 'pin'
  | 'box'
  | 'highlight'
  | 'pointer'
  | 'comment'

export interface CollabSession {
  session_id: string
  project_id: string | null
  title: string
  target_url: string | null
  target_mode: CollabTargetMode
  agent_hub_session_id: string | null
  state: CollabSessionState
  sensitive: boolean
  control_owner: string | null
  control_expires_at: string | null
  browser_target_source: string | null
  media_strategy: string
  evidence_policy: string
  created_by_kind: string
  created_by_display: string | null
  created_at: string | null
  updated_at: string | null
  closed_at: string | null
}

export interface CollabParticipant {
  participant_id: string
  session_id: string
  participant_key: string
  actor_kind: 'user' | 'agent' | 'system'
  display_name: string | null
  role: 'viewer' | 'controller' | 'observer'
  status: 'active' | 'idle' | 'left'
  last_seen_at: string | null
  joined_at: string | null
}

export interface CollabAnnotation {
  annotation_id: string
  session_id: string
  kind: CollabAnnotationKind
  page_key: string | null
  page_url_snapshot: string | null
  selector: string | null
  anchor: Record<string, unknown>
  comment: string
  created_by_kind: string
  created_by_display: string | null
  created_at: string | null
}

export interface CollabEvidencePacket {
  evidence_id: string
  session_id: string
  annotation_id: string | null
  title: string | null
  url: string | null
  page_url_snapshot: string | null
  viewport: Record<string, unknown>
  selector: string | null
  bbox: Record<string, unknown> | null
  context_summary: string
  artifact_id: string | null
  token_estimate: number
  created_by_kind: string
  created_by_display: string | null
  created_at: string | null
}

export interface CollabAuditEvent {
  audit_id: string
  session_id: string
  actor_kind: string
  action: string
  detail: Record<string, unknown>
  created_at: string | null
}

export interface CollabConnectorPairing {
  pairing_id: string
  session_id: string
  state: CollabConnectorPairingState
  connector_host: string | null
  profile_label: string | null
  connector_version: string | null
  connector_state: Record<string, unknown>
  expires_at: string | null
  claimed_at: string | null
  connector_last_seen_at: string | null
  revoked_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface CollabConnectorPairingCreateResponse
  extends CollabConnectorPairing {
  pairing_token: string
}

export interface CollabSessionDetail extends CollabSession {
  participants: CollabParticipant[]
  annotations: CollabAnnotation[]
  evidence_packets: CollabEvidencePacket[]
  audit_events: CollabAuditEvent[]
}

export interface CreateCollabSessionInput {
  project_id?: string | null
  title: string
  target_url?: string | null
  target_mode: CollabTargetMode
  agent_hub_session_id?: string | null
  sensitive: boolean
}

export interface CreateCollabAnnotationInput {
  kind: CollabAnnotationKind
  page_key?: string | null
  page_url_snapshot?: string | null
  selector?: string | null
  anchor: Record<string, unknown>
  comment: string
  created_by_kind?: 'user' | 'agent' | 'system'
}

export interface JoinCollabParticipantInput {
  actor_kind?: 'user' | 'agent' | 'system'
  display_name?: string | null
  role?: 'viewer' | 'controller' | 'observer'
}

export interface CreateCollabEvidencePacketInput {
  annotation_id?: string | null
  title?: string | null
  url?: string | null
  page_url_snapshot?: string | null
  viewport?: Record<string, unknown>
  selector?: string | null
  bbox?: Record<string, unknown> | null
  context_summary: string
  artifact_id?: string | null
}

export interface CreateConnectorPairingInput {
  expires_in_seconds?: number
  connector_host?: string | null
  profile_label?: string | null
}

export const collabApi = {
  listSessions: (projectId?: string | null) =>
    fetchWithErrorHandling<CollabSession[]>(
      `/api/collab/sessions${buildQueryString({ project_id: projectId })}`,
      { errorMessage: 'Failed to fetch design review sessions' },
    ),

  listProjectSessions: (projectId: string) =>
    fetchWithErrorHandling<CollabSession[]>(
      `/api/projects/${projectId}/collab/sessions`,
      { errorMessage: 'Failed to fetch project design review sessions' },
    ),

  createSession: (input: CreateCollabSessionInput) =>
    postJson<CollabSession>(
      '/api/collab/sessions',
      input,
      'Failed to create design review session',
    ),

  createProjectSession: (projectId: string, input: CreateCollabSessionInput) =>
    postJson<CollabSession>(
      `/api/projects/${projectId}/collab/sessions`,
      input,
      'Failed to create project design review session',
    ),

  getSession: (sessionId: string) =>
    fetchWithErrorHandling<CollabSessionDetail>(
      `/api/collab/sessions/${sessionId}`,
      { errorMessage: 'Failed to fetch design review session' },
    ),

  joinParticipant: (sessionId: string, input: JoinCollabParticipantInput) =>
    postJson<CollabParticipant>(
      `/api/collab/sessions/${sessionId}/participants`,
      input,
      'Failed to join design review session',
    ),

  createAnnotation: (sessionId: string, input: CreateCollabAnnotationInput) =>
    postJson<CollabAnnotation>(
      `/api/collab/sessions/${sessionId}/annotations`,
      input,
      'Failed to create annotation',
    ),

  createEvidencePacket: (
    sessionId: string,
    input: CreateCollabEvidencePacketInput,
  ) =>
    postJson<CollabEvidencePacket>(
      `/api/collab/sessions/${sessionId}/evidence-packets`,
      input,
      'Failed to create evidence packet',
    ),

  listConnectorPairings: (sessionId: string) =>
    fetchWithErrorHandling<CollabConnectorPairing[]>(
      `/api/collab/sessions/${sessionId}/connector-pairings`,
      { errorMessage: 'Failed to fetch connector pairings' },
    ),

  createConnectorPairing: (
    sessionId: string,
    input: CreateConnectorPairingInput,
  ) =>
    postJson<CollabConnectorPairingCreateResponse>(
      `/api/collab/sessions/${sessionId}/connector-pairings`,
      input,
      'Failed to create connector pairing',
    ),

  revokeConnectorPairing: (pairingId: string) =>
    postJson<CollabConnectorPairing>(
      `/api/collab/connector-pairings/${pairingId}/revoke`,
      {},
      'Failed to revoke connector pairing',
    ),

  setControlGrant: (
    sessionId: string,
    owner: string | null,
    ttlSeconds = 600,
  ) =>
    postJson<CollabSession>(
      `/api/collab/sessions/${sessionId}/control-grant`,
      { owner, ttl_seconds: ttlSeconds },
      'Failed to update control grant',
    ),

  teardownSession: (sessionId: string) =>
    postJson<CollabSession>(
      `/api/collab/sessions/${sessionId}/teardown`,
      {},
      'Failed to close design review session',
    ),
}
