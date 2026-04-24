'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  Loader2,
  Lock,
  Monitor,
  MousePointer2,
  Power,
  RefreshCw,
  ShieldCheck,
  Unlock,
} from 'lucide-react'
import {
  type KeyboardEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
  type WheelEvent,
} from 'react'
import { type LiveSessionControl, runtimeApi } from '@/lib/api/runtime'

interface LiveSessionWorkspaceProps {
  sessionId: string
}

const VIEWPORTS = [
  { label: '720', width: 1280, height: 720 },
  { label: '900', width: 1440, height: 900 },
  { label: '1080', width: 1920, height: 1080 },
] as const

export function LiveSessionWorkspace({ sessionId }: LiveSessionWorkspaceProps) {
  const queryClient = useQueryClient()
  const viewportRef = useRef<HTMLButtonElement>(null)
  const lastWheelAt = useRef(0)
  const [targetUrl, setTargetUrl] = useState('')
  const [operatorToken, setOperatorToken] = useState<string | null>(null)
  const [tokenReady, setTokenReady] = useState(false)

  useEffect(() => {
    const storageKey = `summitflow-live-session-token:${sessionId}`
    const hash = window.location.hash.replace(/^#/, '')
    const params = new URLSearchParams(hash)
    const fragmentToken = params.get('token')
    const storedToken = window.sessionStorage.getItem(storageKey)
    const token = fragmentToken || storedToken
    if (token) {
      window.sessionStorage.setItem(storageKey, token)
      setOperatorToken(token)
    }
    if (fragmentToken) {
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}`,
      )
    }
    setTokenReady(true)
  }, [sessionId])

  const sessionQuery = useQuery({
    queryKey: ['runtime', 'live-session', sessionId],
    queryFn: () => runtimeApi.getLiveSession(sessionId),
    refetchInterval: 5000,
  })
  const frameQuery = useQuery({
    queryKey: ['runtime', 'live-session-frame', sessionId, !!operatorToken],
    queryFn: () => runtimeApi.getLiveSessionFrame(sessionId, operatorToken),
    enabled:
      tokenReady &&
      sessionQuery.data?.state === 'active' &&
      (!sessionQuery.data.token_required || !!operatorToken),
    refetchInterval: 900,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const controlMutation = useMutation({
    mutationFn: (control: LiveSessionControl) =>
      runtimeApi.controlLiveSession(sessionId, control, operatorToken),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime', 'live-session', sessionId],
      })
    },
  })
  const sensitiveMutation = useMutation({
    mutationFn: (sensitive: boolean) =>
      runtimeApi.setLiveSessionSensitive(sessionId, sensitive, operatorToken),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime', 'live-session', sessionId],
      })
    },
  })
  const teardownMutation = useMutation({
    mutationFn: () => runtimeApi.teardownLiveSession(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime', 'live-session', sessionId],
      })
      queryClient.invalidateQueries({ queryKey: ['runtime', 'live-sessions'] })
    },
  })
  const controlGrantMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      runtimeApi.setLiveSessionControlGrant(sessionId, enabled, operatorToken),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime', 'live-session', sessionId],
      })
    },
  })

  const session = sessionQuery.data
  const frame = frameQuery.data
  const tokenMissing = !!session?.token_required && !operatorToken
  const canSendInput = !!operatorToken && !!session?.control_enabled

  function send(control: LiveSessionControl): void {
    if (session?.state !== 'active') return
    if (!canSendInput) return
    controlMutation.mutate(control)
  }

  function pointFromEvent(event: MouseEvent<HTMLElement>) {
    if (!frame) return null
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: Math.round(
        ((event.clientX - rect.left) / rect.width) * frame.viewport_width,
      ),
      y: Math.round(
        ((event.clientY - rect.top) / rect.height) * frame.viewport_height,
      ),
    }
  }

  function handleClick(event: MouseEvent<HTMLElement>): void {
    viewportRef.current?.focus()
    const point = pointFromEvent(event)
    if (!point) return
    send({ action: 'click', x: point.x, y: point.y })
  }

  function handleWheel(event: WheelEvent<HTMLElement>): void {
    const now = Date.now()
    if (now - lastWheelAt.current < 80) return
    lastWheelAt.current = now
    const point = pointFromEvent(event)
    if (!point) return
    send({
      action: 'wheel',
      x: point.x,
      y: point.y,
      delta_x: Math.round(event.deltaX),
      delta_y: Math.round(event.deltaY),
    })
  }

  function handleKey(event: KeyboardEvent<HTMLButtonElement>): void {
    if (event.metaKey || event.ctrlKey) return
    event.preventDefault()
    if (event.key.length === 1) {
      send({ action: 'text', text: event.key })
      return
    }
    send({ action: 'key', key: event.key })
  }

  function navigate(): void {
    const nextUrl = targetUrl.trim()
    if (!canSendInput) return
    if (!nextUrl) return
    controlMutation.mutate({
      action: 'navigate',
      target_url: nextUrl,
    })
  }

  if (sessionQuery.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    )
  }

  if (sessionQuery.error || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-sm text-rose-300">
        {sessionQuery.error instanceof Error
          ? sessionQuery.error.message
          : 'Live session unavailable'}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-950/95 px-4 py-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-md border border-sky-500/20 bg-sky-500/10">
          <Monitor className="h-4 w-4 text-sky-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">
            {session.title || session.current_url || session.target_url}
          </div>
          <div className="mt-0.5 truncate text-2xs text-slate-500">
            {session.current_url || session.target_url}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => frameQuery.refetch()}
            disabled={tokenMissing}
            title="Refresh frame"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-slate-300 transition-colors hover:border-sky-500/40 hover:text-sky-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => sensitiveMutation.mutate(!session.sensitive)}
            disabled={!operatorToken || sensitiveMutation.isPending}
            title="Sensitive mode"
            className={clsx(
              'flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-medium transition-colors',
              session.sensitive
                ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                : 'border-slate-700 bg-slate-900 text-slate-300',
              !operatorToken && 'cursor-not-allowed opacity-50',
            )}
          >
            {session.sensitive ? (
              <Lock className="h-3.5 w-3.5" />
            ) : (
              <Unlock className="h-3.5 w-3.5" />
            )}
            {session.sensitive ? 'Sensitive' : 'Standard'}
          </button>
          <button
            type="button"
            onClick={() =>
              controlGrantMutation.mutate(!session.control_enabled)
            }
            disabled={!operatorToken || controlGrantMutation.isPending}
            title="Input control"
            className={clsx(
              'flex h-9 items-center gap-2 rounded-md border px-3 text-xs font-medium transition-colors',
              session.control_enabled
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                : 'border-slate-700 bg-slate-900 text-slate-300',
              !operatorToken && 'cursor-not-allowed opacity-50',
            )}
          >
            <MousePointer2 className="h-3.5 w-3.5" />
            {session.control_enabled ? 'Input On' : 'Input Locked'}
          </button>
          <button
            type="button"
            onClick={() => teardownMutation.mutate()}
            disabled={teardownMutation.isPending || session.state !== 'active'}
            title="Close session"
            className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-slate-400 transition-colors hover:border-rose-500/40 hover:text-rose-200 disabled:opacity-50"
          >
            <Power className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div className="grid gap-3 px-4 py-3 lg:grid-cols-[1fr_320px]">
        <section className="min-w-0">
          <button
            type="button"
            ref={viewportRef}
            aria-label="Live browser viewport"
            onClick={handleClick}
            onKeyDown={handleKey}
            onWheel={handleWheel}
            className="flex min-h-[50vh] w-full items-center justify-center overflow-hidden rounded-lg border border-slate-800 bg-black p-0 outline-none ring-0 focus:border-sky-500/60"
          >
            {frame?.image_data_url ? (
              // biome-ignore lint/performance/noImgElement: Live JPEG data URL from local backend broker.
              <img
                src={frame.image_data_url}
                alt="Live browser frame"
                draggable={false}
                className="block max-h-[calc(100vh-8rem)] w-full object-contain"
              />
            ) : tokenMissing ? (
              <div className="px-6 text-center text-sm text-amber-200">
                Operator token required. Start a new session from Runtime.
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading frame
              </div>
            )}
          </button>
        </section>

        <aside className="space-y-3">
          <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              <ShieldCheck className="h-3.5 w-3.5 text-amber-300" />
              Session
            </div>
            <div className="mt-3 grid gap-2 text-xs text-slate-400">
              <div className="flex justify-between gap-3">
                <span>Status</span>
                <span className="text-slate-200">{session.state}</span>
              </div>
              <div className="flex justify-between gap-3">
                <span>Viewport</span>
                <span className="text-slate-200">
                  {session.viewport_width}x{session.viewport_height}
                </span>
              </div>
              <div className="flex justify-between gap-3">
                <span>Capture</span>
                <span className="text-slate-200">
                  {tokenMissing
                    ? 'operator token required'
                    : frameQuery.isFetching
                      ? 'updating'
                      : 'ready'}
                </span>
              </div>
              <div className="flex justify-between gap-3">
                <span>Control</span>
                <span className="text-slate-200">
                  {session.control_enabled ? 'operator' : 'locked'}
                </span>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
            <label
              htmlFor="live-session-url"
              className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400"
            >
              URL
            </label>
            <div className="mt-2 flex gap-2">
              <input
                id="live-session-url"
                value={targetUrl}
                onChange={(event) => setTargetUrl(event.target.value)}
                placeholder={session.current_url || session.target_url}
                className="h-9 min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950/70 px-3 text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-sky-500/60"
              />
              <button
                type="button"
                onClick={navigate}
                disabled={!canSendInput}
                className="h-9 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 text-xs font-medium text-sky-100 transition-colors hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Go
              </button>
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              Viewport
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {VIEWPORTS.map((viewport) => (
                <button
                  key={viewport.label}
                  type="button"
                  onClick={() =>
                    send({
                      action: 'resize',
                      viewport_width: viewport.width,
                      viewport_height: viewport.height,
                    })
                  }
                  disabled={!canSendInput}
                  className={clsx(
                    'h-9 rounded-md border text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                    session.viewport_width === viewport.width &&
                      session.viewport_height === viewport.height
                      ? 'border-sky-500/40 bg-sky-500/10 text-sky-100'
                      : 'border-slate-700 bg-slate-950/50 text-slate-300 hover:border-slate-500',
                  )}
                >
                  {viewport.label}
                </button>
              ))}
            </div>
          </div>

          {controlMutation.error && (
            <div className="rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-200">
              {controlMutation.error instanceof Error
                ? controlMutation.error.message
                : 'Control failed'}
            </div>
          )}
          {frameQuery.error && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-3 text-xs text-amber-200">
              {frameQuery.error instanceof Error
                ? frameQuery.error.message
                : 'Frame unavailable'}
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
