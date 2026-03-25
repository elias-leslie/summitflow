'use client'

import { clsx } from 'clsx'
import type {
  BackupHealthItem,
  BackupHealthResponse,
  StorageStatus,
  StorageSummary,
} from '@/lib/api/backups'
import { formatBytes } from '@/lib/format'

// ─── Health Bar ──────────────────────────────────────────────────

const HEALTH_TONE: Record<string, string> = {
  green: 'bg-emerald-500',
  yellow: 'bg-amber-500',
  red: 'bg-red-500',
}

function BackupHealthBar({ sources }: { sources: BackupHealthItem[] }) {
  if (sources.length === 0) return null
  return (
    <div className="flex gap-0.5 h-2.5 rounded-full overflow-hidden bg-slate-800/50 ring-1 ring-white/5">
      {sources.map((s) => (
        <div
          key={s.source_id}
          className={clsx(
            'flex-1 transition-colors duration-500',
            HEALTH_TONE[s.health_status] ?? 'bg-slate-700',
          )}
          title={`${s.source_name}: ${s.health_status}`}
        />
      ))}
    </div>
  )
}

// ─── Stat Pill ───────────────────────────────────────────────────

function StatPill({
  value,
  label,
  tone,
}: {
  value: number | string
  label: string
  tone: string
}) {
  if (value === 0) return null
  return (
    <div
      className={clsx(
        'flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-mono tabular-nums',
        tone,
      )}
    >
      <span className="font-semibold">{value}</span>
      <span className="opacity-60 hidden sm:inline">{label}</span>
    </div>
  )
}

// ─── Main ────────────────────────────────────────────────────────

interface StatusRibbonProps {
  health: BackupHealthResponse | undefined
  storageSummary: StorageSummary | undefined
  storageStatus: StorageStatus | undefined
  isLoading: boolean
}

export function StatusRibbon({
  health,
  storageSummary,
  storageStatus,
  isLoading,
}: StatusRibbonProps) {
  if (isLoading) return null

  const sources = health?.sources ?? []
  const greenCount = sources.filter((s) => s.health_status === 'green').length
  const redCount = sources.filter((s) => s.health_status === 'red').length
  const totalBackups = storageSummary?.total_count ?? 0
  const totalBytes = storageSummary?.total_bytes ?? 0

  return (
    <div className="space-y-3">
      {/* Health bar */}
      <BackupHealthBar sources={sources} />

      {/* Stat pills row */}
      <div className="flex flex-wrap items-center gap-2">
        <StatPill
          value={sources.length}
          label="sources"
          tone="bg-slate-500/8 text-slate-400 border-slate-500/20"
        />
        <StatPill
          value={greenCount}
          label="healthy"
          tone="bg-emerald-500/8 text-emerald-400 border-emerald-500/20"
        />
        <StatPill
          value={redCount}
          label="failing"
          tone="bg-red-500/8 text-red-400 border-red-500/20"
        />
        <StatPill
          value={totalBackups}
          label="backups"
          tone="bg-blue-500/8 text-blue-400 border-blue-500/20"
        />
        {totalBytes > 0 && (
          <StatPill
            value={formatBytes(totalBytes)}
            label="stored"
            tone="bg-purple-500/8 text-purple-400 border-purple-500/20"
          />
        )}

        {/* Storage backend indicator */}
        {storageStatus?.configured ? (
          <span className="ml-auto text-2xs text-slate-500 hidden sm:inline">
            {storageStatus.default_backend_name}
          </span>
        ) : (
          <span className="ml-auto text-2xs text-amber-400 hidden sm:inline">
            No storage backend
          </span>
        )}
      </div>
    </div>
  )
}
