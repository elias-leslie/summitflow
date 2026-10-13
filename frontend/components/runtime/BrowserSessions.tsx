'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  type BrowserRuntimeLocation,
  type BrowserSession,
  type BrowserSessionAction,
  browserSessionsApi,
} from '@/lib/api/browser-sessions'

const queryKey = ['runtime', 'browser-sessions']

// Null while no browser runs; the runtime state already says so.
function browserLocationLabel(location: BrowserRuntimeLocation): string | null {
  if (location === 'proxmox') return 'Browser on the Proxmox VM'
  if (location === 'local') return 'Browser on this workstation'
  return null
}

/** The browser-automation assist window: live page plus Done, in its own window. */
export function assistWindowUrl(name: string): string {
  return `/browser-assist/${encodeURIComponent(name)}`
}

function openAssistWindow(name: string) {
  window.open(
    assistWindowUrl(name),
    `browser-assist-${name}`,
    'popup,width=1280,height=900',
  )
}

export function BrowserSessions() {
  const client = useQueryClient()
  const inventory = useQuery({
    queryKey,
    queryFn: browserSessionsApi.list,
    refetchInterval: 5000,
    retry: false,
  })
  const [selection, setSelection] = useState<Pick<
    BrowserSession,
    'name' | 'actor'
  > | null>(null)
  const selected = inventory.data?.find(
    (session) =>
      session.name === selection?.name && session.actor === selection.actor,
  )
  // Closed sessions keep their profiles but pile up; list them on request.
  const [showClosed, setShowClosed] = useState(false)
  const isClosed = (session: BrowserSession) =>
    session.state === 'closed' || session.state === 'revoked'
  const closedCount = inventory.data?.filter(isClosed).length ?? 0
  const listed = (inventory.data ?? [])
    .filter(
      (session) => showClosed || !isClosed(session) || session === selected,
    )
    .sort((a, b) => Number(b.paused) - Number(a.paused))
  // A hand-off link (?browser=NAME&actor=ID) selects the session.
  const detail = useRef<HTMLDivElement>(null)
  const [linked, setLinked] = useState(false)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const name = params.get('browser')
    const actor = params.get('actor')
    if (name && actor) {
      setSelection({ name, actor })
      setLinked(true)
    }
  }, [])
  useEffect(() => {
    if (!linked || !selected) return
    setLinked(false)
    detail.current?.scrollIntoView?.({ block: 'start' })
  }, [linked, selected])
  const unavailable =
    !selected || selected.state === 'closed' || selected.state === 'revoked'
  const change = useMutation({
    mutationFn: ({
      session,
      action,
    }: {
      session: BrowserSession
      action: BrowserSessionAction
    }) => browserSessionsApi.change(session, action),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey })
    },
    onError: async () => {
      await client.invalidateQueries({ queryKey })
    },
  })
  function act(action: BrowserSessionAction) {
    if (!selected || change.isPending) return
    change.mutate({ session: selected, action })
  }
  return (
    <section className="space-y-4" aria-label="Managed browser sessions">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-100">
            Browser sessions
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            Select a managed session to inspect it or pause automation for human
            input.
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => {
            void inventory.refetch()
          }}
          disabled={inventory.isFetching}
        >
          Refresh
        </Button>
      </div>
      {inventory.isLoading && (
        <p role="status" className="text-sm text-slate-400">
          Loading browser sessions…
        </p>
      )}
      {inventory.error && (
        <p role="alert" className="text-sm text-rose-300">
          Browser sessions are unavailable. {inventory.error.message}
        </p>
      )}
      {inventory.data && listed.length === 0 && (
        <p className="rounded-lg border border-slate-700 p-4 text-sm text-slate-400">
          No open browser sessions. Agent browser commands create one per agent.
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {listed.map((session) => (
          <button
            key={`${session.name}:${session.actor}`}
            type="button"
            aria-pressed={selected === session}
            disabled={change.isPending}
            onClick={() => {
              change.reset()
              setSelection({ name: session.name, actor: session.actor })
            }}
            className={`min-w-0 rounded-lg border p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${selected === session ? 'border-cyan-500 bg-cyan-500/5' : 'border-slate-700 bg-slate-900'}`}
          >
            <span className="block break-all text-sm font-medium text-slate-200">
              {session.name}
            </span>
            <span className="mt-1 block break-all text-xs text-slate-400">
              Owner: {session.actor}
            </span>
            <span className="mt-2 block text-xs text-slate-400">
              {session.state} ·{' '}
              {session.paused
                ? 'Paused'
                : session.state === 'closed' || session.state === 'revoked'
                  ? 'Unavailable'
                  : 'Automation enabled'}{' '}
              · {session.runtime_state || 'Runtime unknown'}
            </span>
            {session.paused && session.pause_reason && (
              <span className="mt-1 block break-words text-xs text-amber-300">
                Waiting for you: {session.pause_reason}
              </span>
            )}
            {session.location !== null && (
              <span className="mt-1 block text-xs text-slate-400">
                {browserLocationLabel(session.location)}
              </span>
            )}
            {session.last_used_ms !== null && (
              <span className="mt-1 block text-xs text-slate-500">
                Last used {new Date(session.last_used_ms).toLocaleString()}
              </span>
            )}
          </button>
        ))}
      </div>
      {closedCount > 0 && (
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={showClosed}
          onClick={() => setShowClosed((current) => !current)}
        >
          {showClosed
            ? 'Hide closed sessions'
            : `Show closed sessions (${closedCount})`}
        </Button>
      )}
      {selection && (
        <div
          ref={detail}
          className="scroll-mt-4 space-y-3 rounded-lg border border-slate-700 bg-slate-900 p-4"
        >
          <h3 className="break-all font-medium text-slate-200">
            {selection.name}
          </h3>
          {unavailable ? (
            <p role="status" className="text-sm text-slate-400">
              {selected
                ? `This session is ${selected.state}.`
                : 'This selection is unavailable or its owner changed.'}{' '}
              Select another session to continue.
            </p>
          ) : (
            <>
              <p className="text-sm text-slate-400">
                Owner: <span className="break-all">{selected.actor}</span>.{' '}
                {selected.location !== null &&
                  `${browserLocationLabel(selected.location)}. `}
                {selected.paused
                  ? 'Paused for human input.'
                  : 'Automation can use this session.'}
              </p>
              {selected.paused && selected.pause_reason && (
                <p className="break-words text-sm text-amber-300">
                  Agent is waiting for you: {selected.pause_reason}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={selected.paused ? 'primary' : 'secondary'}
                  disabled={!selected.paused}
                  onClick={() => openAssistWindow(selected.name)}
                >
                  Open live view
                </Button>
                <Button
                  size="sm"
                  disabled={change.isPending || selected.paused}
                  onClick={() => act('pause')}
                >
                  Pause for human
                </Button>
                <Button
                  size="sm"
                  disabled={change.isPending || !selected.paused}
                  onClick={() => act('resume')}
                >
                  Resume automation
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={change.isPending}
                  onClick={() => act('close')}
                >
                  Close session
                </Button>
              </div>
              <p className="text-xs text-slate-500">
                The live view opens in its own window while the session is
                paused. Press Done there to hand the browser back to the agent.
                Frames and keystrokes are not saved.
              </p>
            </>
          )}
          {change.isPending && (
            <p role="status" className="text-sm text-slate-400">
              Updating selected session…
            </p>
          )}
          {change.error && (
            <p role="alert" className="text-sm text-rose-300">
              {change.error.message}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
