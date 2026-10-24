'use client'

import { clsx } from 'clsx'
import type { ReactNode } from 'react'
import {
  type BlockStatus,
  TONE_BORDER,
  TONE_LABEL,
  TONE_TEXT,
} from '@/lib/backup-status'

interface StatusBlockProps {
  title: string
  /** One line naming what this mechanism protects and where it writes. */
  subtitle: string
  status: BlockStatus
  isLoading?: boolean
  error?: Error | null
  /** Shown between the facts and the details: actions or a short list. */
  children?: ReactNode
  /** Disclosure content for technical detail; collapsed by default. */
  details?: ReactNode
  detailsLabel?: string
  testId?: string
}

/** One of the three status blocks at the top of the Backups page. */
export function StatusBlock({
  title,
  subtitle,
  status,
  isLoading = false,
  error,
  children,
  details,
  detailsLabel = 'Details',
  testId,
}: StatusBlockProps) {
  const tone = isLoading ? 'unknown' : status.tone
  return (
    <section
      aria-label={title}
      data-testid={testId}
      data-tone={tone}
      className={clsx(
        'flex min-w-0 flex-col rounded-lg border border-l-[3px] border-slate-700/60 bg-slate-900/40',
        TONE_BORDER[tone],
      )}
    >
      <div className="space-y-3 px-4 py-3">
        <header>
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="display text-sm font-semibold text-slate-100">
              {title}
            </h2>
            <span className={clsx('text-2xs font-medium', TONE_TEXT[tone])}>
              {isLoading ? 'Loading' : TONE_LABEL[tone]}
            </span>
          </div>
          <p className="mt-0.5 text-2xs text-slate-500">{subtitle}</p>
        </header>
        <p
          role={isLoading ? 'status' : undefined}
          className={clsx('text-sm font-medium', TONE_TEXT[tone])}
        >
          {isLoading ? 'Loading…' : status.headline}
        </p>
        {error && (
          <p role="alert" className="text-xs text-rose-300">
            {status.facts.length > 0
              ? `Refresh failed; showing the last loaded status. ${error.message}`
              : error.message}
          </p>
        )}
        {status.facts.length > 0 && (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
            {status.facts.map((fact) => (
              <div key={fact.label} className="min-w-0">
                <dt className="text-slate-500">{fact.label}</dt>
                <dd
                  className={clsx(
                    'break-words',
                    fact.tone && fact.tone !== 'ok'
                      ? TONE_TEXT[fact.tone]
                      : 'text-slate-200',
                  )}
                >
                  {fact.value}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {children}
      </div>
      {details && (
        <details className="mt-auto border-t border-slate-800/60">
          <summary className="cursor-pointer px-4 py-2 text-2xs text-slate-400 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
            {detailsLabel}
          </summary>
          <div className="space-y-3 px-4 pb-4 pt-1 text-xs">{details}</div>
        </details>
      )}
    </section>
  )
}

export function DetailValue({
  label,
  value,
  mono = false,
}: {
  label: string
  value: ReactNode
  mono?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="text-slate-500">{label}</dt>
      <dd
        className={clsx(
          'break-words text-slate-200',
          mono && 'break-all font-mono',
        )}
      >
        {value}
      </dd>
    </div>
  )
}
