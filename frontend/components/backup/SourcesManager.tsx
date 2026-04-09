'use client'

import { Loader2, Play } from 'lucide-react'
import { useMemo, useState } from 'react'
import { SourceCard } from './SourceCard'
import {
  type Backup,
  type BackupHealthItem,
  type BackupSource,
  createBackupSource,
  createSourceBackup,
  updateBackupSource,
} from '@/lib/api/backups'

// ─── Infrastructure Setup Card ───────────────────────────────────

function InfraSetupCard({
  isCreating,
  onCreate,
}: {
  isCreating: boolean
  onCreate: () => void
}) {
  return (
    <div className="rounded-lg border-l-[3px] border-l-slate-600 border border-slate-700/60 bg-slate-800/40 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-slate-600 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-400">System Backup</span>
            <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-emerald-400 border border-emerald-500/20">
              system
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            PostgreSQL roles, databases, and server configuration
          </p>
        </div>
        <button
          type="button"
          onClick={onCreate}
          disabled={isCreating}
          className="text-2xs px-2.5 py-1 rounded bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 disabled:opacity-40 transition-colors flex items-center gap-1.5 shrink-0"
        >
          {isCreating ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Play className="w-3 h-3" />
          )}
          Set up & run
        </button>
      </div>
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────────

interface SourcesManagerProps {
  sources: BackupSource[]
  healthItems: BackupHealthItem[]
  recentBackups: Backup[]
  onSourceChanged: () => void
  onBackupTriggered: () => void
  showHeader?: boolean
}

export function SourcesManager({
  sources,
  healthItems,
  recentBackups,
  onSourceChanged,
  onBackupTriggered,
  showHeader = true,
}: SourcesManagerProps) {
  const [backingUpId, setBackingUpId] = useState<string | null>(null)
  const [creatingInfra, setCreatingInfra] = useState(false)

  const hasInfraSource = sources.some(
    (s) => s.source_type === 'infrastructure',
  )

  const healthMap = useMemo(() => {
    const map: Record<string, BackupHealthItem> = {}
    for (const h of healthItems) map[h.source_id] = h
    return map
  }, [healthItems])

  const backupsBySource = useMemo(() => {
    const map: Record<string, Backup[]> = {}
    for (const b of recentBackups) {
      if (!map[b.source_id]) map[b.source_id] = []
      if (map[b.source_id].length < 3) map[b.source_id].push(b)
    }
    return map
  }, [recentBackups])

  const handleBackupNow = async (sourceId: string) => {
    setBackingUpId(sourceId)
    try {
      await createSourceBackup(sourceId)
      onBackupTriggered()
    } catch {
      /* parent refetch will show state */
    }
    setBackingUpId(null)
  }

  const handleCreateInfra = async () => {
    setCreatingInfra(true)
    try {
      const source = await createBackupSource({
        id: 'infrastructure',
        name: 'System Backup',
        path: '/',
        source_type: 'infrastructure',
      })
      await updateBackupSource(source.id, {
        enabled: true,
        frequency: 'daily',
        retention_days: 30,
      })
      await createSourceBackup(source.id)
      onBackupTriggered()
      onSourceChanged()
    } catch {
      /* ignore */
    }
    setCreatingInfra(false)
  }

  return (
    <section className="space-y-3">
      {showHeader && (
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
            Sources & Schedules
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            What gets backed up and when
          </p>
        </div>
      )}

      <div className="space-y-2">
        {sources.map((source) => (
          <SourceCard
            key={source.id}
            source={source}
            health={healthMap[source.id]}
            recentBackups={backupsBySource[source.id] ?? []}
            isBackingUp={backingUpId === source.id}
            onBackupNow={() => handleBackupNow(source.id)}
            onSaved={onSourceChanged}
          />
        ))}

        {!hasInfraSource && (
          <InfraSetupCard
            isCreating={creatingInfra}
            onCreate={handleCreateInfra}
          />
        )}
      </div>
    </section>
  )
}
