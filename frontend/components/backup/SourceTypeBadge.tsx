'use client'

import { clsx } from 'clsx'
import type { BackupSource } from '@/lib/api/backups'

const SOURCE_TYPE_STYLES: Record<string, string> = {
  project: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
  config: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
  workspace: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
  infrastructure: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  project: 'project',
  config: 'config',
  workspace: 'workspace',
  infrastructure: 'system',
}

export function SourceTypeBadge({
  type,
}: {
  type: BackupSource['source_type']
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border leading-none',
        SOURCE_TYPE_STYLES[type] ??
          'bg-slate-600 text-slate-300 border-slate-500',
      )}
    >
      {SOURCE_TYPE_LABELS[type] ?? type}
    </span>
  )
}
