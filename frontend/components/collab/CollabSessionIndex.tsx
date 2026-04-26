'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Loader2, MonitorUp, Plus, ScreenShare } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  type CollabSession,
  type CollabTargetMode,
  collabApi,
} from '@/lib/api/collab'
import { POLL_STANDARD } from '@/lib/polling'
import { CollabSessionWorkspace } from './CollabSessionWorkspace'

interface CollabSessionIndexProps {
  projectId?: string
  title?: string
}

const TARGET_MODES: Array<{
  value: CollabTargetMode
  label: string
  description: string
}> = [
  {
    value: 'live_browser',
    label: 'Live Browser',
    description: 'Shared session backed by isolated browser target.',
  },
  {
    value: 'windows_co_browser',
    label: 'Windows Co-Browser',
    description: 'Dedicated Windows profile/connector path.',
  },
  {
    value: 'st_browser',
    label: 'st browser',
    description: 'Bounded automation evidence from existing CLI.',
  },
]

function modeLabel(mode: CollabTargetMode): string {
  return TARGET_MODES.find((item) => item.value === mode)?.label ?? mode
}

function defaultTargetUrl(): string {
  return ''
}

export function CollabSessionIndex({
  projectId,
  title = 'Design Review',
}: CollabSessionIndexProps): React.ReactElement {
  const queryClient = useQueryClient()
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null,
  )
  const [targetUrl, setTargetUrl] = useState(defaultTargetUrl)
  const [sessionTitle, setSessionTitle] = useState('Windows Co-Browser Review')
  const [targetMode, setTargetMode] =
    useState<CollabTargetMode>('windows_co_browser')
  const [sensitive, setSensitive] = useState(true)

  const sessionsQuery = useQuery({
    queryKey: ['collab-sessions', projectId ?? 'global'],
    queryFn: () =>
      projectId
        ? collabApi.listProjectSessions(projectId)
        : collabApi.listSessions(),
    refetchInterval: POLL_STANDARD,
  })

  const sessions = sessionsQuery.data ?? []
  const activeSessions = sessions.filter(
    (session) => session.state === 'active',
  )
  const selectedSession =
    sessions.find((session) => session.session_id === selectedSessionId) ??
    activeSessions[0] ??
    sessions[0] ??
    null

  useEffect(() => {
    if (!selectedSessionId && selectedSession) {
      setSelectedSessionId(selectedSession.session_id)
    }
  }, [selectedSession, selectedSessionId])

  const createMutation = useMutation({
    mutationFn: (overrideMode?: CollabTargetMode) => {
      const input = {
        project_id: projectId,
        title: sessionTitle,
        target_url: targetUrl.trim() || null,
        target_mode: overrideMode ?? targetMode,
        sensitive,
      }
      return projectId
        ? collabApi.createProjectSession(projectId, input)
        : collabApi.createSession(input)
    },
    onSuccess: (session) => {
      setSelectedSessionId(session.session_id)
      queryClient.invalidateQueries({ queryKey: ['collab-sessions'] })
    },
  })

  return (
    <div className="space-y-4" data-testid="design-review-sessions">
      <div className="flex flex-col gap-3 border-b border-slate-800 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <ScreenShare className="h-4 w-4 text-fuchsia-300" />
            <h1 className="text-xl font-semibold tracking-tight text-slate-100">
              {title}
            </h1>
            <span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-slate-400">
              {activeSessions.length} active
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-500">
            Live Browser, Windows Co-Browser, st browser evidence
          </div>
        </div>

        <div className="grid gap-2 lg:grid-cols-[180px_240px_190px_auto_auto_auto]">
          <input
            value={sessionTitle}
            onChange={(event) => setSessionTitle(event.target.value)}
            className="h-9 rounded-md border border-slate-700 bg-slate-950/70 px-3 text-xs text-slate-200 outline-none transition-colors focus:border-fuchsia-500/60"
            aria-label="Session title"
          />
          <input
            value={targetUrl}
            onChange={(event) => setTargetUrl(event.target.value)}
            placeholder="Target URL optional"
            className="h-9 rounded-md border border-slate-700 bg-slate-950/70 px-3 font-mono text-xs text-slate-200 outline-none transition-colors focus:border-fuchsia-500/60"
            aria-label="Target URL"
          />
          <select
            value={targetMode}
            onChange={(event) =>
              setTargetMode(event.target.value as CollabTargetMode)
            }
            className="h-9 rounded-md border border-slate-700 bg-slate-950/70 px-3 text-xs text-slate-200 outline-none transition-colors focus:border-fuchsia-500/60"
            aria-label="Target mode"
          >
            {TARGET_MODES.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setSensitive((current) => !current)}
            className={clsx(
              'h-9 rounded-md border px-3 text-xs font-medium transition-colors',
              sensitive
                ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                : 'border-slate-700 bg-slate-950/60 text-slate-300',
            )}
          >
            {sensitive ? 'Sensitive' : 'Standard'}
          </button>
          <button
            type="button"
            onClick={() => createMutation.mutate(undefined)}
            disabled={createMutation.isPending}
            className="flex h-9 items-center justify-center gap-2 rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 text-xs font-medium text-fuchsia-100 transition-colors hover:bg-fuchsia-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            Start
          </button>
          <button
            type="button"
            onClick={() => createMutation.mutate('windows_co_browser')}
            disabled={createMutation.isPending}
            className="flex h-9 items-center justify-center gap-2 rounded-md border border-teal-500/30 bg-teal-500/10 px-3 text-xs font-medium text-teal-100 transition-colors hover:bg-teal-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <ScreenShare className="h-3.5 w-3.5" />
            New Windows
          </button>
        </div>
      </div>

      {createMutation.error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-950/20 px-3 py-2 text-xs text-rose-200">
          {createMutation.error instanceof Error
            ? createMutation.error.message
            : 'Session creation failed'}
        </div>
      )}

      {sessionsQuery.isLoading ? (
        <div className="flex h-40 items-center justify-center text-slate-500">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : sessions.length === 0 ? (
        <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-8 text-center text-sm text-slate-500">
          No Design Review sessions
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[280px_1fr]">
          <div className="space-y-2">
            {sessions.map((session: CollabSession) => (
              <button
                key={session.session_id}
                type="button"
                onClick={() => setSelectedSessionId(session.session_id)}
                className={clsx(
                  'w-full rounded-lg border p-3 text-left transition-colors',
                  selectedSession?.session_id === session.session_id
                    ? 'border-fuchsia-500/40 bg-fuchsia-500/10'
                    : 'border-slate-800 bg-slate-950/40 hover:border-slate-700',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-slate-100">
                    {session.title}
                  </span>
                  <span className="shrink-0 rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                    {session.state}
                  </span>
                </div>
                <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                  <MonitorUp className="h-3.5 w-3.5" />
                  {modeLabel(session.target_mode)}
                </div>
                {session.target_mode === 'windows_co_browser' &&
                  session.state !== 'active' && (
                    <div className="mt-2 rounded border border-amber-500/25 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-200">
                      Pair disabled: closed session
                    </div>
                  )}
                <div className="mt-1 truncate font-mono text-[11px] text-slate-600">
                  {session.target_url || 'about:blank'}
                </div>
              </button>
            ))}
          </div>

          {selectedSession && (
            <CollabSessionWorkspace
              sessionId={selectedSession.session_id}
              initialSession={selectedSession}
            />
          )}
        </div>
      )}
    </div>
  )
}
