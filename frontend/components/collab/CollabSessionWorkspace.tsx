'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Cable,
  CircleDot,
  Loader2,
  Lock,
  MousePointer2,
  Power,
  RefreshCw,
  ShieldCheck,
  Unlock,
  Users,
  Wifi,
  WifiOff,
  XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  type CollabAnnotation,
  type CollabAnnotationKind,
  type CollabConnectorPairing,
  type CollabSession,
  collabApi,
} from '@/lib/api/collab'
import { getWsUrl } from '@/lib/api-config'
import {
  type CollabAnchorSelection,
  CollabAnnotationLayer,
} from './CollabAnnotationLayer'
import { CollabEvidencePacket } from './CollabEvidencePacket'

interface CollabSessionWorkspaceProps {
  sessionId: string
  initialSession?: CollabSession
}

const ANNOTATION_KINDS: CollabAnnotationKind[] = ['pin', 'box', 'highlight']
const FALLBACK_ANCHOR: CollabAnchorSelection = {
  x: 160,
  y: 120,
  width: 320,
  height: 180,
  viewport_width: 1440,
  viewport_height: 900,
  scroll_x: 0,
  scroll_y: 0,
}

function targetModeLabel(mode: string): string {
  if (mode === 'windows_co_browser') return 'Windows Co-Browser'
  if (mode === 'st_browser') return 'st browser'
  if (mode === 'manual') return 'Manual Review'
  return 'Live Browser'
}

function annotationAnchor(
  annotation?: CollabAnnotation,
): CollabAnchorSelection {
  if (!annotation) return FALLBACK_ANCHOR
  return {
    x: Number(annotation.anchor.x ?? FALLBACK_ANCHOR.x),
    y: Number(annotation.anchor.y ?? FALLBACK_ANCHOR.y),
    width:
      annotation.anchor.width === undefined
        ? undefined
        : Number(annotation.anchor.width),
    height:
      annotation.anchor.height === undefined
        ? undefined
        : Number(annotation.anchor.height),
    viewport_width: Number(
      annotation.anchor.viewport_width ?? FALLBACK_ANCHOR.viewport_width,
    ),
    viewport_height: Number(
      annotation.anchor.viewport_height ?? FALLBACK_ANCHOR.viewport_height,
    ),
    scroll_x: Number(annotation.anchor.scroll_x ?? 0),
    scroll_y: Number(annotation.anchor.scroll_y ?? 0),
  }
}

function bboxFromAnchor(anchor: CollabAnchorSelection) {
  return {
    x: Math.round(anchor.x),
    y: Math.round(anchor.y),
    width: Math.round(anchor.width ?? 8),
    height: Math.round(anchor.height ?? 8),
  }
}

function formatTimestamp(value: string | null): string {
  if (!value) return 'never'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function connectorApiBaseUrl(): string {
  if (typeof window === 'undefined') return 'http://127.0.0.1:8001/api'
  if (
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1'
  ) {
    return `${window.location.protocol}//${window.location.hostname}:8001/api`
  }
  return `${window.location.origin}/api`
}

function targetOrigin(targetUrl: string | null): string | null {
  if (!targetUrl || targetUrl === 'about:blank') return null
  try {
    return new URL(targetUrl).origin
  } catch {
    return null
  }
}

type ExtensionPairStatus = 'idle' | 'sending' | 'paired' | 'missing' | 'failed'

interface ExtensionPairState {
  status: ExtensionPairStatus
  message: string
}

interface ExtensionBridgeResponse {
  source?: string
  requestId?: string
  ok?: boolean
  error?: string
}

interface ExtensionPairingConfig {
  apiBaseUrl: string
  sessionId: string
  pairingId: string
  pairingToken: string
  sensitiveMode: boolean
  targetUrl: string | null
  profileLabel: string | null
}

function postPairingToExtension(
  config: ExtensionPairingConfig,
): Promise<ExtensionBridgeResponse> {
  if (typeof window === 'undefined') {
    return Promise.resolve({
      ok: false,
      error: 'Browser extension bridge unavailable during server render.',
    })
  }

  const requestId =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`

  return new Promise((resolve) => {
    const timeout = window.setTimeout(() => {
      cleanup()
      resolve({
        ok: false,
        error:
          'Extension not detected on this tab. After loading the extension, refresh this Design page, then click Pair again.',
      })
    }, 1_500)

    const handleMessage = (event: MessageEvent<ExtensionBridgeResponse>) => {
      const data = event.data
      if (
        event.source !== window ||
        data?.source !== 'summitflow.extension' ||
        data.requestId !== requestId
      ) {
        return
      }
      cleanup()
      resolve(data)
    }

    function cleanup() {
      window.clearTimeout(timeout)
      window.removeEventListener('message', handleMessage)
    }

    window.addEventListener('message', handleMessage)
    window.postMessage(
      {
        source: 'summitflow.design',
        requestId,
        message: {
          type: 'summitflow.claim_pairing',
          config,
        },
      },
      window.location.origin,
    )
  })
}

function connectorValue(
  pairing: CollabConnectorPairing | null,
  key: string,
): string | null {
  const value = pairing?.connector_state[key]
  return typeof value === 'string' && value.trim() ? value : null
}

function connectorRecord(
  pairing: CollabConnectorPairing | null,
  key: string,
): Record<string, unknown> | null {
  const value = pairing?.connector_state[key]
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : null
}

export function CollabSessionWorkspace({
  sessionId,
  initialSession,
}: CollabSessionWorkspaceProps): React.ReactElement {
  const queryClient = useQueryClient()
  const [comment, setComment] = useState('')
  const [kind, setKind] = useState<CollabAnnotationKind>('box')
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [eventConnected, setEventConnected] = useState(false)
  const [extensionPairState, setExtensionPairState] =
    useState<ExtensionPairState>({
      status: 'idle',
      message:
        'Install/enable the extension in the dedicated Windows profile, refresh this Design page, then click Pair.',
    })
  const [draftAnchor, setDraftAnchor] = useState<CollabAnchorSelection | null>(
    null,
  )

  const detailQuery = useQuery({
    queryKey: ['collab-session', sessionId],
    queryFn: () => collabApi.getSession(sessionId),
    initialData: initialSession
      ? {
          ...initialSession,
          participants: [],
          annotations: [],
          evidence_packets: [],
          audit_events: [],
        }
      : undefined,
    refetchInterval: 30_000,
  })

  const session = detailQuery.data
  const connectorPairingsQuery = useQuery({
    queryKey: ['collab-connector-pairings', sessionId],
    queryFn: () => collabApi.listConnectorPairings(sessionId),
    enabled: session?.target_mode === 'windows_co_browser',
    refetchInterval:
      session?.target_mode === 'windows_co_browser' ? 5_000 : false,
  })
  const joinedSessionRef = useRef<string | null>(null)
  const selectedAnchor =
    draftAnchor ?? annotationAnchor(session?.annotations[0])
  const selectedAnnotationId = session?.annotations[0]?.annotation_id ?? null
  const connectorPairings = connectorPairingsQuery.data ?? []
  const activeConnectorPairing =
    connectorPairings.find((pairing) => pairing.state === 'claimed') ??
    connectorPairings.find((pairing) => pairing.state === 'pending') ??
    connectorPairings[0] ??
    null

  const annotationMutation = useMutation({
    mutationFn: () =>
      collabApi.createAnnotation(sessionId, {
        kind,
        page_key: session?.target_url || '/design',
        page_url_snapshot: session?.target_url,
        selector: '[data-design-review-target]',
        anchor:
          kind === 'pin'
            ? {
                ...selectedAnchor,
                width: undefined,
                height: undefined,
              }
            : { ...selectedAnchor },
        comment,
      }),
    onSuccess: () => {
      setComment('')
      setDraftAnchor(null)
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['collab-sessions'] })
    },
  })

  const evidenceMutation = useMutation({
    mutationFn: () =>
      collabApi.createEvidencePacket(sessionId, {
        title: 'Selected review region',
        annotation_id: selectedAnnotationId,
        url: session?.target_url,
        page_url_snapshot: session?.target_url,
        viewport: {
          width: selectedAnchor.viewport_width,
          height: selectedAnchor.viewport_height,
        },
        selector: '[data-design-review-target]',
        bbox: bboxFromAnchor(selectedAnchor),
        context_summary:
          'Design Review selection with target mode, viewport, selector, and bbox only. No DOM dump or screenshot stream attached.',
      }),
    onSuccess: () => {
      setEvidenceError(null)
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })
    },
    onError: (error) => {
      setEvidenceError(
        error instanceof Error ? error.message : 'Evidence packet blocked',
      )
    },
  })

  const grantMutation = useMutation({
    mutationFn: (owner: string | null) =>
      collabApi.setControlGrant(sessionId, owner, 600),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['collab-sessions'] })
    },
  })

  const createConnectorPairingMutation = useMutation({
    mutationFn: () =>
      collabApi.createConnectorPairing(sessionId, {
        expires_in_seconds: 600,
        profile_label: 'SummitFlow Review',
      }),
    onSuccess: (pairing) => {
      setExtensionPairState({
        status: 'sending',
        message: 'Sending one-time pairing token to browser extension...',
      })
      queryClient.invalidateQueries({
        queryKey: ['collab-connector-pairings', sessionId],
      })
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })

      void postPairingToExtension({
        apiBaseUrl: connectorApiBaseUrl(),
        sessionId,
        pairingId: pairing.pairing_id,
        pairingToken: pairing.pairing_token,
        sensitiveMode: Boolean(session?.sensitive),
        targetUrl: session?.target_url ?? null,
        profileLabel: pairing.profile_label,
      }).then((response) => {
        if (response.ok) {
          setExtensionPairState({
            status: 'paired',
            message:
              'Extension paired. It can open the target tab; click the extension icon on that tab to show the overlay if needed.',
          })
        } else {
          setExtensionPairState({
            status: 'missing',
            message:
              response.error ??
              'Extension not detected on this tab. Refresh this Design page after loading the extension, then click Pair again.',
          })
        }
        queryClient.invalidateQueries({
          queryKey: ['collab-connector-pairings', sessionId],
        })
      })
    },
  })

  const revokeConnectorPairingMutation = useMutation({
    mutationFn: (pairingId: string) =>
      collabApi.revokeConnectorPairing(pairingId),
    onSuccess: () => {
      setExtensionPairState({
        status: 'idle',
        message:
          'Install/enable the extension in the dedicated Windows profile, refresh this Design page, then click Pair.',
      })
      queryClient.invalidateQueries({
        queryKey: ['collab-connector-pairings', sessionId],
      })
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })
    },
  })

  const participantMutation = useMutation({
    mutationFn: (input: {
      actor_kind: 'user' | 'agent'
      display_name: string
      role: 'viewer' | 'controller'
    }) => collabApi.joinParticipant(sessionId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['collab-sessions'] })
    },
  })

  const teardownMutation = useMutation({
    mutationFn: () => collabApi.teardownSession(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collab-session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['collab-sessions'] })
    },
  })

  useEffect(() => {
    if (joinedSessionRef.current === sessionId) return
    joinedSessionRef.current = sessionId
    participantMutation.mutate({
      actor_kind: 'user',
      display_name: 'Operator',
      role: 'controller',
    })
  }, [participantMutation, sessionId])

  useEffect(() => {
    const socket = new WebSocket(
      getWsUrl(`/api/collab/sessions/${sessionId}/events`),
    )
    const pingTimer = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'ping' }))
      }
    }, 15_000)

    socket.onopen = () => setEventConnected(true)
    socket.onclose = () => setEventConnected(false)
    socket.onerror = () => setEventConnected(false)
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(String(event.data)) as { type?: string }
        if (payload.type === 'collab_event') {
          queryClient.invalidateQueries({
            queryKey: ['collab-session', sessionId],
          })
          queryClient.invalidateQueries({ queryKey: ['collab-sessions'] })
          queryClient.invalidateQueries({
            queryKey: ['collab-connector-pairings', sessionId],
          })
        }
      } catch {
        setEventConnected(false)
      }
    }

    return () => {
      window.clearInterval(pingTimer)
      socket.close()
    }
  }, [queryClient, sessionId])

  if (detailQuery.isLoading || !session) {
    return (
      <div className="flex min-h-[360px] items-center justify-center text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }

  const canAnnotate =
    session.state === 'active' &&
    !!comment.trim() &&
    !annotationMutation.isPending
  const controlActive = !!session.control_owner

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
      <section className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 pb-3">
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.14em]',
              session.state === 'active'
                ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                : 'border-slate-700 bg-slate-900 text-slate-400',
            )}
          >
            <CircleDot className="h-3 w-3" />
            {session.state}
          </span>
          <span className="rounded-full border border-cyan-500/25 bg-cyan-500/10 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-cyan-200">
            {targetModeLabel(session.target_mode)}
          </span>
          <span
            className={clsx(
              'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.14em]',
              session.sensitive
                ? 'border-amber-500/25 bg-amber-500/10 text-amber-200'
                : 'border-slate-700 bg-slate-900 text-slate-400',
            )}
          >
            {session.sensitive ? (
              <Lock className="h-3 w-3" />
            ) : (
              <Unlock className="h-3 w-3" />
            )}
            {session.sensitive ? 'Sensitive' : 'Standard'}
          </span>
          <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-slate-400">
            {session.media_strategy}
          </span>
          <span
            className={clsx(
              'rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.14em]',
              eventConnected
                ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                : 'border-slate-700 bg-slate-900 text-slate-400',
            )}
          >
            {eventConnected ? 'Event Push' : 'Poll Fallback'}
          </span>
        </div>

        <div>
          <h2 className="text-lg font-semibold tracking-tight text-slate-100">
            {session.title}
          </h2>
          <div className="mt-1 truncate font-mono text-xs text-slate-500">
            {session.target_url || 'about:blank'}
          </div>
        </div>

        <CollabAnnotationLayer
          annotations={session.annotations}
          disabled={session.state !== 'active'}
          draftAnchor={draftAnchor ?? undefined}
          markKind={kind}
          onAnchorChange={setDraftAnchor}
        />
      </section>

      <aside className="space-y-3">
        {session.target_mode === 'windows_co_browser' && (
          <WindowsConnectorPanel
            session={session}
            pairings={connectorPairings}
            activePairing={activeConnectorPairing}
            extensionPairState={extensionPairState}
            createPending={createConnectorPairingMutation.isPending}
            createError={createConnectorPairingMutation.error}
            revokePending={revokeConnectorPairingMutation.isPending}
            onCreatePairing={() => createConnectorPairingMutation.mutate()}
            onRevokePairing={(pairingId) =>
              revokeConnectorPairingMutation.mutate(pairingId)
            }
          />
        )}

        <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              <Users className="h-3.5 w-3.5 text-fuchsia-300" />
              Participants
            </div>
            <button
              type="button"
              onClick={() =>
                participantMutation.mutate({
                  actor_kind: 'agent',
                  display_name: 'Codex',
                  role: 'viewer',
                })
              }
              disabled={
                session.state !== 'active' || participantMutation.isPending
              }
              className="h-7 rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 px-2 text-[11px] font-medium text-fuchsia-100 transition-colors hover:bg-fuchsia-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Agent
            </button>
          </div>
          <div className="mt-3 space-y-2">
            {session.participants.length === 0 ? (
              <div className="text-xs text-slate-500">
                No active participants
              </div>
            ) : (
              session.participants.map((participant) => (
                <div
                  key={participant.participant_id}
                  className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-950/60 px-2 py-1.5 text-xs"
                >
                  <span className="truncate text-slate-200">
                    {participant.display_name || participant.actor_kind}
                  </span>
                  <span className="shrink-0 uppercase tracking-[0.12em] text-slate-500">
                    {participant.role}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
            <MousePointer2 className="h-3.5 w-3.5 text-cyan-300" />
            Control
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 text-sm">
            <span className="text-slate-400">Owner</span>
            <span className="text-slate-100">
              {session.control_owner || 'locked'}
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => grantMutation.mutate('agent')}
              disabled={session.state !== 'active' || grantMutation.isPending}
              className="h-9 rounded-md border border-cyan-500/30 bg-cyan-500/10 text-xs font-medium text-cyan-100 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Grant Agent
            </button>
            <button
              type="button"
              onClick={() => grantMutation.mutate(null)}
              disabled={!controlActive || grantMutation.isPending}
              className="h-9 rounded-md border border-slate-700 bg-slate-950/60 text-xs font-medium text-slate-300 transition-colors hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Release
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
            Markup
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {ANNOTATION_KINDS.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setKind(item)}
                className={clsx(
                  'h-8 rounded-md border text-xs font-medium capitalize transition-colors',
                  kind === item
                    ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100'
                    : 'border-slate-700 bg-slate-950/50 text-slate-300 hover:border-slate-500',
                )}
              >
                {item}
              </button>
            ))}
          </div>
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={600}
            rows={3}
            className="mt-3 w-full resize-none rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-cyan-500/60"
            placeholder="Comment"
          />
          <button
            type="button"
            onClick={() => annotationMutation.mutate()}
            disabled={!canAnnotate}
            className="mt-2 h-9 w-full rounded-md border border-cyan-500/30 bg-cyan-500/10 text-xs font-medium text-cyan-100 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add Mark
          </button>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
            Evidence
          </div>
          <button
            type="button"
            onClick={() => evidenceMutation.mutate()}
            disabled={session.state !== 'active' || evidenceMutation.isPending}
            className="mt-3 h-9 w-full rounded-md border border-emerald-500/30 bg-emerald-500/10 text-xs font-medium text-emerald-100 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Compact Packet
          </button>
          {evidenceError && (
            <div className="mt-2 text-xs text-amber-200">{evidenceError}</div>
          )}
          <div className="mt-3 space-y-2">
            {session.evidence_packets.map((packet) => (
              <CollabEvidencePacket key={packet.evidence_id} packet={packet} />
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={() => teardownMutation.mutate()}
          disabled={session.state !== 'active' || teardownMutation.isPending}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-md border border-rose-500/30 bg-rose-500/10 text-sm font-medium text-rose-100 transition-colors hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Power className="h-4 w-4" />
          Close Session
        </button>
      </aside>
    </div>
  )
}

interface WindowsConnectorPanelProps {
  session: CollabSession
  pairings: CollabConnectorPairing[]
  activePairing: CollabConnectorPairing | null
  extensionPairState: ExtensionPairState
  createPending: boolean
  createError: unknown
  revokePending: boolean
  onCreatePairing: () => void
  onRevokePairing: (pairingId: string) => void
}

function WindowsConnectorPanel({
  session,
  pairings,
  activePairing,
  extensionPairState,
  createPending,
  createError,
  revokePending,
  onCreatePairing,
  onRevokePairing,
}: WindowsConnectorPanelProps): React.ReactElement {
  const apiBaseUrl = connectorApiBaseUrl()
  const target = targetOrigin(session.target_url)
  const currentUrl = connectorValue(activePairing, 'url')
  const title = connectorValue(activePairing, 'title')
  const viewport = connectorRecord(activePairing, 'viewport')
  const scroll = connectorRecord(activePairing, 'scroll')
  const connected = activePairing?.state === 'claimed'
  const canRevoke =
    !!activePairing &&
    (activePairing.state === 'pending' || activePairing.state === 'claimed')
  const pairDisabledReason =
    session.state !== 'active'
      ? 'Pair disabled: this Windows Co-Browser session is closed. Click New Windows above to start an active session.'
      : createPending
        ? 'Creating pairing...'
        : null

  return (
    <div className="rounded-lg border border-teal-500/25 bg-teal-950/20 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-teal-100">
          <Cable className="h-3.5 w-3.5 text-teal-300" />
          Windows Co-Browser Extension
        </div>
        <span
          className={clsx(
            'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.14em]',
            connected
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
              : 'border-slate-700 bg-slate-950/60 text-slate-400',
          )}
        >
          {connected ? (
            <Wifi className="h-3 w-3" />
          ) : (
            <WifiOff className="h-3 w-3" />
          )}
          {activePairing?.state ?? 'none'}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <ConnectorFact
          label="Profile"
          value={activePairing?.profile_label ?? 'SummitFlow Review'}
        />
        <ConnectorFact
          label="Host"
          value={activePairing?.connector_host ?? 'unpaired'}
        />
        <ConnectorFact
          label="Sensitive"
          value={session.sensitive ? 'blocked' : 'standard'}
        />
        <ConnectorFact
          label="Control"
          value={session.control_owner ?? 'locked'}
        />
        <ConnectorFact
          label="Last seen"
          value={formatTimestamp(activePairing?.connector_last_seen_at ?? null)}
        />
        <ConnectorFact label="Pairings" value={String(pairings.length)} />
      </div>

      <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/60 p-2 text-xs">
        <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">
          Capture
        </div>
        <div className="mt-2 space-y-1 text-slate-300">
          <div className="truncate">
            {title || currentUrl || 'waiting for page state'}
          </div>
          {viewport && (
            <div className="text-slate-500">
              {String(viewport.width ?? '?')}x{String(viewport.height ?? '?')}
              {scroll
                ? ` scroll ${String(scroll.x ?? 0)},${String(scroll.y ?? 0)}`
                : ''}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/60 p-2 text-xs">
        <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">
          Egress
        </div>
        <div className="mt-2 space-y-1 font-mono text-[11px] text-slate-400">
          <div>{new URL(apiBaseUrl).origin}</div>
          {target && <div>{target}</div>}
        </div>
      </div>

      <div
        className={clsx(
          'mt-3 rounded-md border p-2 text-xs',
          extensionPairState.status === 'paired'
            ? 'border-emerald-500/25 bg-emerald-950/20 text-emerald-100'
            : extensionPairState.status === 'missing' ||
                extensionPairState.status === 'failed'
              ? 'border-amber-500/25 bg-amber-950/20 text-amber-100'
              : 'border-slate-800 bg-slate-950/60 text-slate-300',
        )}
      >
        <div className="font-semibold uppercase tracking-[0.14em] text-slate-500">
          Extension Pairing
        </div>
        <div className="mt-2 leading-5">{extensionPairState.message}</div>
        <a
          href="/api/collab/chromium-extension.zip"
          className="mt-2 inline-flex h-7 items-center rounded-md border border-teal-500/30 bg-teal-500/10 px-2 text-[11px] font-medium text-teal-100 transition-colors hover:bg-teal-500/20"
        >
          Download Extension ZIP
        </a>
        {activePairing?.state === 'pending' && (
          <div className="mt-2 rounded border border-amber-500/20 bg-slate-950/60 px-2 py-1 text-[11px] text-amber-100">
            Pending token expires in minutes. If the extension was just loaded,
            refresh this Design page, then click Pair again.
          </div>
        )}
      </div>

      {Boolean(createError) && (
        <div className="mt-2 text-xs text-rose-200">
          {createError instanceof Error
            ? createError.message
            : 'Pairing failed'}
        </div>
      )}
      {pairDisabledReason && (
        <div className="mt-2 rounded-md border border-amber-500/25 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200">
          {pairDisabledReason}
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={onCreatePairing}
          disabled={session.state !== 'active' || createPending}
          title={pairDisabledReason ?? 'Pair installed browser extension'}
          className="flex h-9 items-center justify-center gap-2 rounded-md border border-teal-500/30 bg-teal-500/10 text-xs font-medium text-teal-100 transition-colors hover:bg-teal-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {createPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          Pair
        </button>
        <button
          type="button"
          onClick={() =>
            activePairing && onRevokePairing(activePairing.pairing_id)
          }
          disabled={!canRevoke || revokePending}
          className="flex h-9 items-center justify-center gap-2 rounded-md border border-rose-500/30 bg-rose-500/10 text-xs font-medium text-rose-100 transition-colors hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <XCircle className="h-3.5 w-3.5" />
          Revoke
        </button>
      </div>
    </div>
  )
}

function ConnectorFact({
  label,
  value,
}: {
  label: string
  value: string
}): React.ReactElement {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 px-2 py-1.5">
      <div className="uppercase tracking-[0.12em] text-slate-600">{label}</div>
      <div className="mt-1 truncate text-slate-200">{value}</div>
    </div>
  )
}
