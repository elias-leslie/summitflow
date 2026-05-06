'use client'

import { clsx } from 'clsx'
import {
  Clipboard,
  Eraser,
  Loader2,
  type LucideIcon,
  MessageSquarePlus,
  MousePointer2,
  Send,
  ShieldCheck,
  SquareDashedMousePointer,
  Trash2,
} from 'lucide-react'
import type { FormEvent, RefObject } from 'react'
import type { LiveSessionStatus } from '@/lib/api/runtime'
import {
  browserTargetLabel,
  type InteractionMode,
  shortTime,
  VIEWPORTS,
} from './live-session-workspace-model'

const INTERACTION_OPTIONS: {
  mode: InteractionMode
  icon: LucideIcon
  label: string
}[] = [
  { mode: 'control', icon: MousePointer2, label: 'Drive' },
  { mode: 'pin', icon: MessageSquarePlus, label: 'Pin' },
  { mode: 'box', icon: SquareDashedMousePointer, label: 'Box' },
]

interface LiveSessionSidebarProps {
  session: LiveSessionStatus
  interactionMode: InteractionMode
  annotationsCount: number
  tokenMissing: boolean
  frameFetching: boolean
  targetUrl: string
  canSendInput: boolean
  secureTextRef: RefObject<HTMLInputElement | null>
  secureTextSending: boolean
  secureTextStatus: string | null
  secureTextError: string | null
  controlError: unknown
  frameError: unknown
  onInteractionModeChange: (mode: InteractionMode) => void
  onClearAnnotations: () => void
  onTargetUrlChange: (value: string) => void
  onNavigate: () => void
  onSubmitSecureText: (event: FormEvent<HTMLFormElement>) => void
  onPasteClipboardSecureText: () => Promise<void>
  onClearSecureText: () => void
  onResizeViewport: (width: number, height: number) => void
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

export function LiveSessionSidebar({
  session,
  interactionMode,
  annotationsCount,
  tokenMissing,
  frameFetching,
  targetUrl,
  canSendInput,
  secureTextRef,
  secureTextSending,
  secureTextStatus,
  secureTextError,
  controlError,
  frameError,
  onInteractionModeChange,
  onClearAnnotations,
  onTargetUrlChange,
  onNavigate,
  onSubmitSecureText,
  onPasteClipboardSecureText,
  onClearSecureText,
  onResizeViewport,
}: LiveSessionSidebarProps) {
  return (
    <aside className="space-y-3">
      <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
          <MessageSquarePlus className="h-3.5 w-3.5 text-cyan-300" />
          Annotate
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {INTERACTION_OPTIONS.map(({ mode, icon: Icon, label }) => (
            <button
              key={mode}
              type="button"
              onClick={() => onInteractionModeChange(mode)}
              className={clsx(
                'flex h-9 items-center justify-center gap-1 rounded-md border text-xs font-medium transition-colors',
                interactionMode === mode
                  ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100'
                  : 'border-slate-700 bg-slate-950/50 text-slate-300 hover:border-slate-500',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 text-2xs text-slate-500">
          <span>{annotationsCount} local marks</span>
          <button
            type="button"
            onClick={onClearAnnotations}
            disabled={annotationsCount === 0}
            className="flex h-8 items-center gap-1 rounded-md border border-slate-700 bg-slate-950/50 px-2 text-xs text-slate-300 transition-colors hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear
          </button>
        </div>
      </div>

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
                : frameFetching
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
          <div className="flex justify-between gap-3">
            <span>Lease</span>
            <span className="text-slate-200">
              {shortTime(session.control_expires_at)}
            </span>
          </div>
          <div className="flex justify-between gap-3">
            <span>Target</span>
            <span className="max-w-[180px] truncate text-slate-200">
              {browserTargetLabel(session)}
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
            onChange={(event) => onTargetUrlChange(event.target.value)}
            placeholder={session.current_url || session.target_url}
            className="h-9 min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950/70 px-3 text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-sky-500/60"
          />
          <button
            type="button"
            onClick={onNavigate}
            disabled={!canSendInput}
            className="h-9 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 text-xs font-medium text-sky-100 transition-colors hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Go
          </button>
        </div>
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-3">
        <div className="flex items-center justify-between gap-2">
          <label
            htmlFor="live-session-secure-text"
            className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400"
          >
            Secure Paste
          </label>
          <button
            type="button"
            onClick={() => void onPasteClipboardSecureText()}
            disabled={!canSendInput || secureTextSending}
            title="Send clipboard"
            className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-slate-950/60 text-slate-300 transition-colors hover:border-sky-500/40 hover:text-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Clipboard className="h-3.5 w-3.5" />
          </button>
        </div>
        <form onSubmit={onSubmitSecureText} className="mt-2 space-y-2">
          <input
            ref={secureTextRef}
            id="live-session-secure-text"
            type="password"
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={!canSendInput || secureTextSending}
            className="h-9 w-full rounded-md border border-slate-700 bg-slate-950/70 px-3 text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-sky-500/60 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <div className="grid grid-cols-2 gap-2">
            <button
              id="live-session-secure-send"
              type="submit"
              disabled={!canSendInput || secureTextSending}
              className="flex h-9 items-center justify-center gap-2 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 text-xs font-medium text-sky-100 transition-colors hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {secureTextSending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Send
            </button>
            <button
              type="button"
              onClick={onClearSecureText}
              disabled={secureTextSending}
              className="flex h-9 items-center justify-center gap-2 rounded-md border border-slate-700 bg-slate-950/50 px-3 text-xs font-medium text-slate-300 transition-colors hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Eraser className="h-3.5 w-3.5" />
              Clear
            </button>
          </div>
        </form>
        {secureTextStatus && (
          <div className="mt-2 text-xs text-emerald-200">
            {secureTextStatus}
          </div>
        )}
        {secureTextError && (
          <div className="mt-2 text-xs text-rose-200">{secureTextError}</div>
        )}
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
              onClick={() => onResizeViewport(viewport.width, viewport.height)}
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

      {controlError ? (
        <div className="rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-200">
          {errorMessage(controlError, 'Control failed')}
        </div>
      ) : null}
      {frameError ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-3 text-xs text-amber-200">
          {errorMessage(frameError, 'Frame unavailable')}
        </div>
      ) : null}
    </aside>
  )
}
