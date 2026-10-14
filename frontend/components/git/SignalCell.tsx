import clsx from 'clsx'
import type { Cell, Tone } from './developmentSignals'

export const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-emerald-300',
  info: 'text-cyan-300',
  warn: 'text-amber-300',
  bad: 'text-rose-300',
  idle: 'text-slate-500',
}
export const TONE_DOT: Record<Tone, string> = {
  ok: 'bg-emerald-400',
  info: 'bg-cyan-400',
  warn: 'bg-amber-400',
  bad: 'bg-rose-400 shadow-[0_0_6px_rgba(251,113,133,0.7)]',
  idle: 'bg-slate-700',
}
export const TONE_STRIP: Record<Tone, string> = {
  ok: 'bg-emerald-500/30',
  info: 'bg-cyan-500/40',
  warn: 'bg-amber-400/70',
  bad: 'bg-rose-500',
  idle: 'bg-transparent',
}

export function SignalCell({ label, cell }: { label: string; cell: Cell }) {
  return (
    <span
      className="flex min-w-0 items-center gap-1.5 text-xs"
      title={`${label}\n${cell.title}`}
    >
      <span
        aria-hidden="true"
        className={clsx(
          'h-1.5 w-1.5 shrink-0 rounded-full',
          TONE_DOT[cell.tone],
        )}
      />
      <span className="text-2xs text-slate-500 lg:hidden">{label}</span>
      <span
        className={clsx(
          'truncate font-mono tabular-nums',
          TONE_TEXT[cell.tone],
        )}
      >
        {cell.label}
      </span>
      {cell.detail && (
        <span className="hidden truncate text-2xs text-slate-500 xl:inline">
          {cell.detail}
        </span>
      )}
    </span>
  )
}
