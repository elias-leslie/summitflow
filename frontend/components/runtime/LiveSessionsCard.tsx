'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  ExternalLink,
  Loader2,
  MonitorUp,
  Play,
  Power,
  ShieldCheck,
} from 'lucide-react'
import { useState } from 'react'
import { type LiveSessionStatus, runtimeApi } from '@/lib/api/runtime'
import { POLL_NOTIFICATIONS } from '@/lib/polling'

const AMAZON_PHOTOS_URL = 'https://www.amazon.com/photos/all'

function sessionSummary(sessions: LiveSessionStatus[] | undefined): string {
  if (!sessions?.length) return 'No active co-driving sessions'
  const active = sessions.filter((session) => session.state === 'active').length
  return `${active}/${sessions.length} active`
}

function targetLabel(session: LiveSessionStatus): string {
  if (!session.browser_target_host || !session.browser_target_port) {
    return 'Browser target unavailable'
  }
  const mode = session.browser_target_debug_local ? 'debug-local' : 'isolated'
  return `${mode} ${session.browser_target_host}:${session.browser_target_port}`
}

function openSession(sessionId: string, operatorToken?: string): void {
  if (operatorToken) {
    window.sessionStorage.setItem(
      `summitflow-live-session-token:${sessionId}`,
      operatorToken,
    )
  }
  const tokenFragment = operatorToken
    ? `#token=${encodeURIComponent(operatorToken)}`
    : ''
  window.open(
    `/runtime-live/${sessionId}${tokenFragment}`,
    `summitflow-live-${sessionId}`,
    'popup,width=1500,height=980,noopener,noreferrer',
  )
}

export function LiveSessionsCard() {
  const queryClient = useQueryClient()
  const [targetUrl, setTargetUrl] = useState(AMAZON_PHOTOS_URL)
  const { data, error, isLoading } = useQuery({
    queryKey: ['runtime', 'live-sessions'],
    queryFn: runtimeApi.listLiveSessions,
    refetchInterval: POLL_NOTIFICATIONS,
  })

  const createMutation = useMutation({
    mutationFn: () => runtimeApi.createLiveSession(targetUrl),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['runtime', 'live-sessions'] })
      openSession(session.id, session.operator_token)
    },
  })

  const teardownMutation = useMutation({
    mutationFn: (sessionId: string) =>
      runtimeApi.teardownLiveSession(sessionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runtime', 'live-sessions'] })
    },
  })

  if (isLoading) {
    return <div className="h-16 animate-pulse rounded-lg bg-slate-800/40" />
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-950/20 px-4 py-3">
        <span className="text-sm font-medium text-slate-100">Live Browser</span>
        <span className="ml-3 text-sm text-red-300">
          {error instanceof Error ? error.message : 'Unavailable'}
        </span>
      </div>
    )
  }

  const sessions = data ?? []

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/50">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-md border border-sky-500/20 bg-sky-500/10">
          <MonitorUp className="h-4 w-4 text-sky-300" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-100">
              Live Browser
            </span>
            <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-2xs font-semibold uppercase tracking-[0.14em] text-amber-200">
              Sensitive
            </span>
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            {sessionSummary(sessions)}
          </div>
        </div>
        <div className="flex min-w-[260px] flex-1 items-center gap-2 md:flex-none">
          <input
            aria-label="Target URL"
            value={targetUrl}
            onChange={(event) => setTargetUrl(event.target.value)}
            className="h-9 min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950/70 px-3 text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-sky-500/60"
          />
          <button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            title="Start session"
            className="inline-flex h-9 items-center gap-2 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 text-xs font-medium text-sky-100 transition-colors hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Start
          </button>
        </div>
      </div>

      {createMutation.error && (
        <div className="border-t border-slate-800/60 px-4 py-2 text-xs text-rose-300">
          {createMutation.error instanceof Error
            ? createMutation.error.message
            : 'Session creation failed'}
        </div>
      )}

      {sessions.length > 0 && (
        <div className="grid gap-2 border-t border-slate-800/60 px-4 py-3 md:grid-cols-2 xl:grid-cols-3">
          {sessions.map((session) => (
            <div
              key={session.id}
              className="rounded-lg border border-slate-700/60 bg-slate-950/40 p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-slate-100">
                    {session.title || session.current_url || session.target_url}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-2xs text-slate-500">
                    <span
                      className={clsx(
                        'inline-flex items-center rounded-full border px-2 py-0.5 uppercase tracking-[0.12em]',
                        session.state === 'active'
                          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                          : 'border-slate-600 bg-slate-800/50 text-slate-400',
                      )}
                    >
                      {session.state}
                    </span>
                    {session.sensitive && (
                      <span className="inline-flex items-center gap-1 text-amber-200">
                        <ShieldCheck className="h-3 w-3" />
                        Protected
                      </span>
                    )}
                    {session.control_enabled && (
                      <span className="inline-flex items-center rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 uppercase tracking-[0.12em] text-emerald-200">
                        Control
                      </span>
                    )}
                    <span
                      className={clsx(
                        'inline-flex items-center rounded-full border px-2 py-0.5 uppercase tracking-[0.12em]',
                        session.browser_target_debug_local
                          ? 'border-rose-500/25 bg-rose-500/10 text-rose-200'
                          : 'border-sky-500/25 bg-sky-500/10 text-sky-200',
                      )}
                    >
                      {session.browser_target_debug_local
                        ? 'Debug Local'
                        : 'Isolated'}
                    </span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => openSession(session.id)}
                    title="Open"
                    className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-slate-300 transition-colors hover:border-sky-500/40 hover:text-sky-200"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => teardownMutation.mutate(session.id)}
                    disabled={teardownMutation.isPending}
                    title="Close"
                    className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-slate-400 transition-colors hover:border-rose-500/40 hover:text-rose-200 disabled:opacity-50"
                  >
                    <Power className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <div className="mt-2 truncate text-2xs text-slate-600">
                {session.current_url || session.target_url}
              </div>
              <div className="mt-1 truncate text-2xs text-slate-500">
                {targetLabel(session)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
