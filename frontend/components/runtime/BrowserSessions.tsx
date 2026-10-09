'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  forwardRef,
  type KeyboardEvent,
  type MouseEvent,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'
import { Button } from '@/components/ui/button'
import {
  type BrowserSession,
  type BrowserSessionAction,
  browserSessionsApi,
  browserStreamUrl,
  parseBrowserStreamEvent,
} from '@/lib/api/browser-sessions'

const queryKey = ['runtime', 'browser-sessions']

function modifiers(event: {
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
  shiftKey: boolean
}): number {
  return (
    (event.altKey ? 1 : 0) |
    (event.ctrlKey ? 2 : 0) |
    (event.metaKey ? 4 : 0) |
    (event.shiftKey ? 8 : 0)
  )
}

const keyCodes: Record<string, number> = {
  Enter: 13,
  Tab: 9,
  Backspace: 8,
  Escape: 27,
  ArrowLeft: 37,
  ArrowUp: 38,
  ArrowRight: 39,
  ArrowDown: 40,
  Delete: 46,
  Home: 36,
  End: 35,
  PageUp: 33,
  PageDown: 34,
}

interface LiveBrowserHandle {
  release(): Promise<void>
}

const LiveBrowser = forwardRef<LiveBrowserHandle, { session: BrowserSession }>(
  function LiveBrowser({ session }, ref) {
    const canvas = useRef<HTMLCanvasElement>(null)
    const socket = useRef<WebSocket | null>(null)
    const releaseTransport = useRef<(() => Promise<void>) | null>(null)
    useImperativeHandle(
      ref,
      () => ({
        release: () =>
          releaseTransport.current?.() ??
          Promise.reject(
            new Error(
              'Live view is unavailable. Refresh the selected session.',
            ),
          ),
      }),
      [],
    )
    const [state, setState] = useState<
      'connecting' | 'live' | 'disconnecting' | 'ended'
    >('connecting')
    const [page, setPage] = useState({ url: '', title: '', target: '' })
    useEffect(() => {
      const ws = new WebSocket(browserStreamUrl(session))
      socket.current = ws
      let active = true
      let confirmed = false
      let pending: Promise<void> | null = null
      let resolveRelease: (() => void) | undefined
      let rejectRelease: ((error: Error) => void) | undefined
      let timer: ReturnType<typeof setTimeout> | undefined
      const releaseError = () =>
        new Error(
          'Live view release was not confirmed. Refresh the selected session before retrying.',
        )
      releaseTransport.current = () => {
        if (confirmed) return Promise.resolve()
        if (pending) return pending
        setState('disconnecting')
        pending = new Promise<void>((resolve, reject) => {
          resolveRelease = resolve
          rejectRelease = reject
          timer = setTimeout(() => reject(releaseError()), 15000)
        })
        if (ws.readyState === WebSocket.OPEN)
          ws.send(JSON.stringify({ type: 'release' }))
        else if (ws.readyState !== WebSocket.CONNECTING)
          rejectRelease?.(releaseError())
        return pending
      }
      ws.onopen = () => {
        if (pending) ws.send(JSON.stringify({ type: 'release' }))
      }
      ws.onmessage = (message: MessageEvent<unknown>) => {
        if (!active || typeof message.data !== 'string') return
        try {
          const event = parseBrowserStreamEvent(message.data)
          if (event.type === 'released') {
            confirmed = true
            clearTimeout(timer)
            resolveRelease?.()
            ws.close()
          } else if (event.type === 'bound') {
            setPage({
              url: event.url,
              title: event.title,
              target: event.target,
            })
          } else if (event.type === 'url') {
            setPage((current) => ({ ...current, url: event.url, title: '' }))
          } else if (event.type === 'frame') {
            const image = new Image()
            image.onload = () => {
              if (!active || ws.readyState !== WebSocket.OPEN) return
              const element = canvas.current
              if (!element) return
              element.width = event.width
              element.height = event.height
              element
                .getContext('2d')
                ?.drawImage(image, 0, 0, event.width, event.height)
              if (!pending) setState('live')
              ws.send(JSON.stringify({ type: 'ack', seq: event.seq }))
            }
            image.onerror = () => ws.close()
            image.src = `data:image/jpeg;base64,${event.data}`
          }
        } catch {
          ws.close()
        }
      }
      ws.onclose = () => {
        clearTimeout(timer)
        if (!confirmed) rejectRelease?.(releaseError())
        if (active) {
          setState('ended')
          canvas.current
            ?.getContext('2d')
            ?.clearRect(0, 0, canvas.current.width, canvas.current.height)
        }
      }
      ws.onerror = () => {
        if (active) setState('ended')
        ws.close()
      }
      return () => {
        active = false
        clearTimeout(timer)
        releaseTransport.current = null
        if (!confirmed) rejectRelease?.(releaseError())
        socket.current = null
        ws.close()
        canvas.current
          ?.getContext('2d')
          ?.clearRect(0, 0, canvas.current.width, canvas.current.height)
      }
    }, [session.name, session.actor])

    function send(event: Record<string, string | number>) {
      if (state === 'live' && socket.current?.readyState === WebSocket.OPEN)
        socket.current.send(JSON.stringify(event))
    }
    function mouse(event: MouseEvent<HTMLCanvasElement>, eventType: string) {
      event.preventDefault()
      if (eventType === 'mousePressed') event.currentTarget.focus()
      const bounds = event.currentTarget.getBoundingClientRect()
      send({
        type: 'input_mouse',
        eventType,
        x: Math.round(
          ((event.clientX - bounds.left) * event.currentTarget.width) /
            bounds.width,
        ),
        y: Math.round(
          ((event.clientY - bounds.top) * event.currentTarget.height) /
            bounds.height,
        ),
        button:
          eventType === 'mouseMoved' && !event.buttons
            ? 'none'
            : (['left', 'middle', 'right'][event.button] ?? 'none'),
        clickCount: eventType === 'mousePressed' ? event.detail || 1 : 0,
        modifiers: modifiers(event),
      })
    }
    function keyboard(
      event: KeyboardEvent<HTMLCanvasElement>,
      eventType: string,
    ) {
      if (event.nativeEvent.isComposing) return
      if (event.key === 'Escape' && event.shiftKey) {
        event.preventDefault()
        event.currentTarget.blur()
        return
      }
      event.preventDefault()
      send({
        type: 'input_keyboard',
        eventType,
        key: event.key,
        code: event.code,
        windowsVirtualKeyCode:
          keyCodes[event.key] ??
          (event.key.length === 1 ? event.key.toUpperCase().charCodeAt(0) : 0),
        modifiers: modifiers(event),
        ...(eventType === 'keyDown' &&
        !event.ctrlKey &&
        !event.metaKey &&
        (event.key.length === 1 || event.key === 'Enter')
          ? { text: event.key === 'Enter' ? '\r' : event.key }
          : {}),
      })
    }
    return (
      <div className="space-y-3 rounded-lg border border-slate-700 bg-slate-950 p-3">
        <div className="break-all text-sm text-slate-300">
          <p>{page.title || 'Selected browser target'}</p>
          <p className="text-xs text-slate-500">
            {page.url || 'Waiting for target binding'}
          </p>
        </div>
        <p role="status" className="text-sm text-slate-400">
          {state === 'connecting'
            ? 'Connecting to the paused session…'
            : state === 'disconnecting'
              ? 'Releasing the selected session…'
              : state === 'live'
                ? 'Live view holds this session paused. Click the page to type or scroll. Shift+Escape leaves page focus.'
                : 'Live view ended. Disconnect, refresh the session, then open it again.'}
        </p>
        <canvas
          ref={canvas}
          tabIndex={state === 'live' ? 0 : -1}
          aria-label={`Live page for ${session.name}`}
          className={`block h-auto max-h-[70vh] w-auto max-w-full border border-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${state === 'ended' ? 'hidden' : ''}`}
          onMouseMove={(event) => mouse(event, 'mouseMoved')}
          onMouseDown={(event) => mouse(event, 'mousePressed')}
          onMouseUp={(event) => mouse(event, 'mouseReleased')}
          onContextMenu={(event) => event.preventDefault()}
          onKeyDown={(event) => keyboard(event, 'keyDown')}
          onKeyUp={(event) => keyboard(event, 'keyUp')}
          onCompositionEnd={(event) => {
            for (const text of event.data)
              send({ type: 'input_keyboard', eventType: 'char', text })
          }}
          onPaste={(event) => {
            event.preventDefault()
            for (const text of event.clipboardData.getData('text/plain'))
              send({ type: 'input_keyboard', eventType: 'char', text })
          }}
          onWheel={(event) => {
            event.currentTarget.focus()
            const bounds = event.currentTarget.getBoundingClientRect()
            send({
              type: 'input_mouse',
              eventType: 'mouseWheel',
              button: 'none',
              x:
                ((event.clientX - bounds.left) * event.currentTarget.width) /
                bounds.width,
              y:
                ((event.clientY - bounds.top) * event.currentTarget.height) /
                bounds.height,
              deltaX: event.deltaX,
              deltaY: event.deltaY,
              modifiers: modifiers(event),
            })
          }}
        />
      </div>
    )
  },
)

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
  const [view, setView] = useState(false)
  const liveBrowser = useRef<LiveBrowserHandle | null>(null)
  const [releasing, setReleasing] = useState(false)
  const [releaseError, setReleaseError] = useState<string | null>(null)
  const selected = inventory.data?.find(
    (session) =>
      session.name === selection?.name && session.actor === selection.actor,
  )
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
  async function act(action?: BrowserSessionAction) {
    if (!selected || change.isPending || releasing) return
    setReleaseError(null)
    setReleasing(true)
    try {
      if (view) {
        if (!liveBrowser.current)
          throw new Error(
            'Live view is unavailable. Refresh the selected session.',
          )
        await liveBrowser.current.release()
      }
      setView(false)
      if (action) change.mutate({ session: selected, action })
    } catch (error) {
      setReleaseError(
        error instanceof Error
          ? error.message
          : 'Live view release was not confirmed.',
      )
      setView(false)
    } finally {
      setReleasing(false)
    }
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
      {inventory.data?.length === 0 && (
        <p className="rounded-lg border border-slate-700 p-4 text-sm text-slate-400">
          No managed browser sessions. Create a named session through ST to see
          it here.
        </p>
      )}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {inventory.data?.map((session) => (
          <button
            key={`${session.name}:${session.actor}`}
            type="button"
            aria-pressed={selected === session}
            disabled={releasing || change.isPending}
            onClick={() => {
              setView(false)
              change.reset()
              setReleaseError(null)
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
            {session.last_used_ms !== null && (
              <span className="mt-1 block text-xs text-slate-500">
                Last used {new Date(session.last_used_ms).toLocaleString()}
              </span>
            )}
          </button>
        ))}
      </div>
      {selection && (
        <div className="space-y-3 rounded-lg border border-slate-700 bg-slate-900 p-4">
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
                {selected.paused
                  ? 'Paused for human input.'
                  : 'Automation can use this session.'}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={change.isPending || releasing || selected.paused}
                  onClick={() => {
                    void act('pause')
                  }}
                >
                  Pause for human
                </Button>
                <Button
                  size="sm"
                  disabled={change.isPending || releasing || !selected.paused}
                  onClick={() => {
                    void act('resume')
                  }}
                >
                  Resume automation
                </Button>
                <Button
                  size="sm"
                  disabled={
                    change.isPending || releasing || !selected.paused || view
                  }
                  onClick={() => setView(true)}
                >
                  Open live view
                </Button>
                {view && (
                  <Button
                    size="sm"
                    disabled={releasing || change.isPending}
                    onClick={() => {
                      void act()
                    }}
                  >
                    Disconnect live view
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={change.isPending || releasing}
                  onClick={() => {
                    void act('close')
                  }}
                >
                  Close session
                </Button>
              </div>
              <p className="text-xs text-slate-500">
                Enter sign-in details directly in the live page. This view
                forwards human input without saving frames or keystrokes. Resume
                automation disconnects the view first.
              </p>
              {view && selected.paused && !inventory.error && (
                <LiveBrowser
                  ref={liveBrowser}
                  key={`${selected.name}:${selected.actor}`}
                  session={selected}
                />
              )}
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
          {releaseError && (
            <p role="alert" className="text-sm text-rose-300">
              {releaseError}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
